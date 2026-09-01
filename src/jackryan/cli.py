"""CLI adapter.

Like the REST layer, this is a translation surface only: it parses arguments,
calls the service layer, and prints. Keeping it over services rather than over
HTTP means the CLI works on an instance that is not serving.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Sequence

from . import __version__
from .ingestion.legacy_office import converter_status
from .ingestion.quality_gate import read_as
from .app import build_context
from .errors import JackRyanError
from .storage.port import Casefile, Document, SearchHit


def _render(casefile: Casefile) -> dict[str, Any]:
    return {
        "id": casefile.id,
        "short_id": casefile.short_id,
        "slug": casefile.slug,
        "title": casefile.title,
        "description": casefile.description,
        "created_at": casefile.created_at.isoformat(),
        "updated_at": casefile.updated_at.isoformat(),
    }


def _render_document(document: Document) -> dict[str, Any]:
    row = {
        "id": document.id,
        "short_id": document.short_id,
        "filename": document.filename,
        "media_type": document.media_type,
        "byte_size": document.byte_size,
        "extractor": document.extractor,
        # How the text was obtained. The analyst is the one who decides whether
        # a document is worth re-scanning, so they need this at least as much as
        # the assistant does — and under the same name the assistant sees.
        "read_as": read_as(document.text_source),
        "characters": len(document.extracted_text),
        "created_at": document.created_at.isoformat(),
    }
    if document.containment_path and document.containment_path != document.filename:
        # Where it was found, because an attachment's own name identifies
        # nothing without the message and archive that carried it.
        row["found_at"] = document.containment_path
    if document.child_count:
        row["children"] = document.child_count
    return row


def _render_hit(hit: SearchHit) -> dict[str, Any]:
    return {
        "chunk_id": hit.chunk.id,
        "document_id": hit.document.id,
        "document": hit.document.filename,
        "score": round(hit.score, 6),
        "rerank_score": round(hit.rerank_score, 6) if hit.rerank_score is not None else None,
        "ranking": hit.ranking,
        "keyword_rank": hit.keyword_rank,
        "vector_rank": hit.vector_rank,
        "heading_path": hit.chunk.heading_path,
        # The span returned, and the passage inside it that matched.
        "char_start": hit.char_start,
        "char_end": hit.char_end,
        "matched_char_start": hit.chunk.char_start,
        "matched_char_end": hit.chunk.char_end,
        "narrowed": hit.narrowed,
        "read_as": read_as(hit.document.text_source),
        "text": hit.text,
    }


def _print(payload: Any, as_json: bool, empty_message: str = "Nothing to show.") -> None:
    if as_json:
        print(json.dumps(payload, indent=2))
        return
    if isinstance(payload, list):
        if not payload:
            print(empty_message)
            return
        for item in payload:
            if "slug" in item:
                print(f"{item['short_id']}  {item['slug']:<28}  {item['title']}")
            elif "filename" in item:
                print(
                    f"{item['short_id']}  {item['filename']:<38}  "
                    f"{item['characters']:>8} chars  {item['read_as']}"
                )
            else:
                print(item)
        return
    for key, value in payload.items():
        print(f"{key:<12} {value}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="jackryan", description="Jack Ryan investigation workbench")
    parser.add_argument("--version", action="version", version=f"jackryan {__version__}")
    parser.add_argument("--json", action="store_true", help="emit JSON instead of a table")

    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status", help="show instance configuration and health")

    casefile = sub.add_parser("casefile", help="manage casefiles").add_subparsers(
        dest="casefile_command", required=True
    )

    create = casefile.add_parser("create", help="create a casefile")
    create.add_argument("title")
    create.add_argument("--description", default="")
    create.add_argument("--slug", default=None)

    casefile.add_parser("list", help="list casefiles")

    show = casefile.add_parser("show", help="show one casefile by id, short id, or slug")
    show.add_argument("reference")

    update = casefile.add_parser("update", help="update a casefile")
    update.add_argument("reference")
    update.add_argument("--title", default=None)
    update.add_argument("--description", default=None)
    update.add_argument("--slug", default=None)

    delete = casefile.add_parser("delete", help="delete a casefile")
    delete.add_argument("reference")

    serve = sub.add_parser(
        "serve-mcp", help="serve the agent tool surface over stdio"
    )
    serve.add_argument(
        "--profile", default=None,
        help="tool surface to advertise (default: the configured one)",
    )

    ingest = sub.add_parser("ingest", help="ingest a file or folder into a casefile")
    ingest.add_argument("casefile")
    ingest.add_argument("path")

    search = sub.add_parser("search", help="search a casefile")
    search.add_argument("casefile")
    search.add_argument("query")
    search.add_argument("--limit", type=int, default=10)

    document = sub.add_parser("document", help="inspect ingested documents").add_subparsers(
        dest="document_command", required=True
    )
    doc_list = document.add_parser("list", help="list a casefile's documents")
    doc_list.add_argument("casefile")
    doc_list.add_argument(
        "--expanded",
        action="store_true",
        help="include documents expanded out of archives, mailboxes, and messages",
    )
    doc_show = document.add_parser("show", help="show one document")
    doc_show.add_argument("casefile")
    doc_show.add_argument("reference")

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        # Composition itself can fail — a bad profile, or a store built under a
        # different contract — and those are exactly the errors an operator
        # needs stated plainly rather than as a traceback.
        context = build_context()
    except JackRyanError as exc:
        print(f"{exc.code}: {exc}", file=sys.stderr)
        return 1
    try:
        if args.command == "status":
            _print(
                {
                    "version": __version__,
                    "profile": context.config.profile.name,
                    "data_dir": str(context.config.data_dir),
                    "database": str(context.config.db_path),
                    "contract": context.corpus_fingerprint,
                    # Reported rather than enforced at startup: a host that
                    # ingests no legacy Office file must not be stopped by a
                    # converter it will never use, so an operator finds out
                    # here instead of 256 times into a run.
                    "legacy_office": converter_status(),
                    "casefiles": len(context.casefiles.list()),
                },
                args.json,
            )
            return 0

        if args.command == "serve-mcp":
            from .interfaces.mcp import build_mcp_server

            # Runs until the client disconnects; stdout belongs to the protocol
            # from here on, so nothing else may print to it.
            build_mcp_server(context, args.profile).run(transport="stdio")
            return 0

        if args.command == "ingest":
            report = context.ingestion.ingest(args.casefile, args.path)
            if args.json:
                _print(
                    {
                        "ingested": report.ingested,
                        "failed": report.failed,
                        "outcomes": [
                            {
                                "path": o.path,
                                "status": o.status,
                                "document_id": o.document_id,
                                "chunks": o.chunks,
                                "detail": o.detail,
                            }
                            for o in report.outcomes
                        ],
                    },
                    True,
                )
            else:
                for outcome in report.outcomes:
                    suffix = f" — {outcome.detail}" if outcome.detail else ""
                    name = outcome.path.rsplit("/", 1)[-1]
                    print(f"{outcome.status:<10} {name} ({outcome.chunks} chunks){suffix}")
                print(f"\n{report.ingested} ingested, {report.failed} failed")
            return 1 if report.failed and not report.ingested else 0

        if args.command == "search":
            hits = context.search.search(args.casefile, args.query, args.limit)
            if args.json:
                _print([_render_hit(h) for h in hits], True, "")
            elif not hits:
                print("No matches.")
            else:
                if hits[0].ranking == "rerank-unavailable":
                    # The order is the fused one and the operator asked for
                    # better. Said once, above the results, rather than left to
                    # be noticed.
                    print("A reranker is configured but did not run; showing the fused order.\n")
                for i, hit in enumerate(hits, 1):
                    where = f" · {hit.chunk.heading_path}" if hit.chunk.heading_path else ""
                    print(f"{i}. {hit.document.filename}{where}  [{hit.chunk.short_id}]")
                    body = " ".join(hit.text.split())
                    print(f"   {body[:180]}{'…' if len(body) > 180 else ''}\n")
            return 0

        if args.command == "document":
            if args.document_command == "list":
                _print(
                    [
                        _render_document(d)
                        for d in context.ingestion.list_documents(
                            args.casefile, include_expanded=args.expanded
                        )
                    ],
                    args.json,
                    "No documents yet. Add some with: jackryan ingest <casefile> <path>",
                )
            else:
                _print(_render_document(context.ingestion.resolve_document(args.casefile, args.reference)), args.json)
            return 0

        service = context.casefiles
        if args.casefile_command == "create":
            _print(_render(service.create(args.title, args.description, args.slug)), args.json)
        elif args.casefile_command == "list":
            _print(
                [_render(c) for c in service.list()],
                args.json,
                "No casefiles yet. Create one with: jackryan casefile create <title>",
            )
        elif args.casefile_command == "show":
            _print(_render(service.resolve(args.reference)), args.json)
        elif args.casefile_command == "update":
            _print(
                _render(
                    service.update(
                        args.reference,
                        title=args.title,
                        description=args.description,
                        slug=args.slug,
                    )
                ),
                args.json,
            )
        elif args.casefile_command == "delete":
            _print(_render(service.delete(args.reference)), args.json)
        return 0
    except JackRyanError as exc:
        print(f"{exc.code}: {exc}", file=sys.stderr)
        return 1
    finally:
        context.close()


if __name__ == "__main__":
    raise SystemExit(main())
