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
from .ingestion.containers import rar_status
from .ingestion.legacy_office import converter_status
from .app import build_context
from .errors import JackRyanError
from .rendering import render_casefile, render_document, render_hit, render_report
from .services.ingestion import locations_verdict
from .services.search import DEFAULT_CARRIER_PAGE
from .storage.port import Casefile, Document, SearchHit


def _render(casefile: Casefile) -> dict[str, Any]:
    return render_casefile(casefile)


def _render_document(document: Document) -> dict[str, Any]:
    """The shared fields, plus the three this surface adds and REST does not.

    Kept as its own function rather than aliased to `render_document`, because
    the extras below are what make it the CLI's: each is added only when it says
    something, so a table stays the width the corpus warrants.
    """
    row = render_document(document)
    if document.containment_path and document.containment_path != document.filename:
        # Where it was found, because an attachment's own name identifies
        # nothing without the message and archive that carried it.
        row["found_at"] = document.containment_path
    if document.child_count:
        row["children"] = document.child_count
    # Only when it says something, like `children` above: a document found in
    # one place is the ordinary case and adding a column of ones would widen
    # every table for nothing.
    # Asked of the document rather than computed here: whether its own place
    # is among the recorded ones depends on when its record began, and a rule
    # spelled once in the domain object cannot drift between two adapters.
    if document.additional_locations:
        row["locations"] = document.location_count
    # The count alone over-claims where the record began late: its one
    # observation may be the document's own place, and nothing in the row would
    # say so. The verdict travels beside the count for that reason — a listing
    # never builds a location record, so this is its only qualifier.
        row["locations_recorded"] = locations_verdict(document)
    if document.summary:
        # Added only when present, so a table for a corpus ingested without a
        # summariser keeps the shape it has today. Model-written, so the producer
        # travels with it rather than being inferred from current configuration.
        row["summary"] = document.summary
        row["summary_by"] = document.summary_by
    return row


def _render_hit(hit: SearchHit) -> dict[str, Any]:
    """Rounded, because a terminal table of unrounded floats is unreadable.

    REST does not round; the difference is a parameter of the shared renderer
    rather than a second copy of the seventeen fields.
    """
    return render_hit(hit, round_scores=True)


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
    search.add_argument(
        "--mention",
        default="",
        metavar="KIND:VALUE",
        help=(
            "narrow to passages carrying an identifier; a bare value matches any kind"
        ),
    )

    mentions = sub.add_parser(
        "mentions", help="the identifiers a casefile contains, counted"
    )
    mentions.add_argument("casefile")
    mentions.add_argument("--kind", default="", help="one identifier kind, or all")
    mentions.add_argument("--limit", type=int, default=50)

    # A separate top-level command rather than a subgroup, because `mentions`
    # is already a leaf command and cannot also be a group.
    carriers = sub.add_parser(
        "mention-documents",
        help="every document carrying one identifier, a page at a time",
    )
    carriers.add_argument("casefile")
    carriers.add_argument("mention", metavar="KIND:VALUE")
    carriers.add_argument("--offset", type=int, default=0)
    carriers.add_argument("--limit", type=int, default=DEFAULT_CARRIER_PAGE)

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

    repair = sub.add_parser(
        "repair", help="recompute derived data an earlier ingest recorded wrongly"
    ).add_subparsers(dest="repair_command", required=True)
    offsets = repair.add_parser(
        "mention-offsets",
        help="recompute where each identifier sits in its document",
    )
    offsets.add_argument("casefile")

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
                    # Same reasoning, same vocabulary: a host that ingests no
                    # archive must not be stopped by a reader it will never call.
                    "rar": rar_status(),
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
                _print(render_report(report), True)
            else:
                for outcome in report.outcomes:
                    suffix = f" — {outcome.detail}" if outcome.detail else ""
                    name = outcome.path.rsplit("/", 1)[-1]
                    print(f"{outcome.status:<10} {name} ({outcome.chunks} chunks){suffix}")
                print(f"\n{report.ingested} ingested, {report.failed} failed")
                if not report.complete:
                    print("\nThis run did not cover everything it was offered:")
                    for line in report.limitations:
                        print(f"  {line}")
                # A separate block below the limitations one, and phrased as a
                # finding rather than a shortfall: the run is still complete.
                # A copy found somewhere new was read and stored.
                if report.new_locations:
                    print(
                        "\nAlready in this casefile, and now recorded at a "
                        "location it had not been seen at:"
                    )
                    for path in report.new_locations:
                        print(f"  {path}")
            return 1 if report.failed and not report.ingested else 0

        if args.command == "search":
            hits = context.search.search(
                args.casefile, args.query, args.limit, args.mention
            )
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

        if args.command == "mentions":
            facets = context.search.mention_facets(
                args.casefile, args.kind, args.limit
            )
            rows = [
                {
                    "kind": f.kind,
                    "value": f.value,
                    "mentions": f.mentions,
                    "documents": f.documents,
                }
                for f in facets
            ]
            if args.json:
                _print(rows, True, "")
            elif not rows:
                # Said as "none found", never as "none present": the shipped
                # extractors prefer precision, and a casefile ingested before
                # mentions existed has none until it is reingested.
                print("No identifiers extracted from this casefile.")
            else:
                print(f"{'mentions':>8}  {'docs':>5}  {'kind':<20} value")
                for row in rows:
                    print(
                        f"{row['mentions']:>8}  {row['documents']:>5}  "
                        f"{row['kind']:<20} {row['value']}"
                    )
            return 0

        if args.command == "mention-documents":
            page = context.search.mention_documents(
                args.casefile, args.mention, args.offset, args.limit
            )
            envelope = {
                "mention": args.mention,
                "kind": page.kind,
                "value": page.value,
                "total": len(page.carriers),
                "offset": page.offset,
                "total_matching": page.total_matching,
                "truncated": page.truncated,
                "continue_from": page.continue_from,
                "documents": [
                    {
                        **_render_document(carrier.document),
                        "mentions": carrier.mentions,
                        "chunk_id": carrier.chunk_id,
                    }
                    for carrier in page.carriers
                ],
            }
            if args.json:
                # The envelope, not a bare row list as `mentions` prints: the
                # paging counts are the point of a paged command, and a list
                # drops them.
                _print(envelope, True, "")
            elif page.beyond_the_end:
                # Never the absence claim below: this page is empty because it
                # began past the carrier set, and saying "no document carries
                # this" of it is a false negative — the one this command exists
                # to remove. The decision is the page's own, so this and the
                # agent surface cannot diverge again.
                print(
                    f"No documents at offset {page.offset}; "
                    f"{page.total_matching} carry {page.value}."
                )
            elif not page.carriers:
                print(
                    f"No document in this casefile carries {page.value}. The "
                    "inventory records what the extractors found."
                )
            else:
                print(
                    f"{page.value}"
                    + (f" ({page.kind})" if page.kind else "")
                    + f" — {page.total_matching} document(s) carry it"
                )
                print(f"{'mentions':>8}  {'passage':<10}  document")
                for row in envelope["documents"]:
                    print(
                        f"{row['mentions']:>8}  {row['chunk_id'][:8]:<10}  "
                        f"{row.get('found_at') or row['filename']}"
                    )
                if page.truncated:
                    print(
                        f"\n{len(page.carriers)} of {page.total_matching} shown; "
                        f"continue with --offset {page.continue_from}"
                    )
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
                record = context.ingestion.document_locations(
                    args.casefile, args.reference
                )
                row = _render_document(record.document)
                row["locations_recorded"] = record.verdict
                # Set unconditionally here, unlike the listing above: this is a
                # single document's full record, and a person reading it needs
                # `1` to mean one rather than having to infer it from an absent
                # key.
                row["locations"] = record.recorded.total
                if args.json:
                    row["observed_at"] = [
                        location.path for location in record.observed_at
                    ]
                    row["locations_truncated"] = record.truncated
                    if record.note:
                        row["locations_note"] = record.note
                    _print(row, True)
                else:
                    _print(row, False)
                    # Every recorded location, each with its root, rather
                    # than "the others": the document's own path above is
                    # relative to a root no column holds, so listing only the
                    # rest would show a different set depending on which copy
                    # was ingested first.
                    for location in record.observed_at:
                        print(f"observed at {location.path}")
                    if record.truncated:
                        print(f"… {record.recorded.total} locations recorded in total")
                    # The wording comes from the record, never written out here:
                    # one caveat, one spelling, on every surface.
                    if record.note:
                        print(record.note)
            return 0

        if args.command == "repair":
            report = context.ingestion.repair_mention_offsets(args.casefile)
            _print(
                {
                    "documents_examined": report.documents_examined,
                    "chunks_examined": report.chunks_examined,
                    "chunks_unlocatable": report.chunks_unlocatable,
                    "mentions_corrected": report.mentions_corrected,
                },
                args.json,
            )
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
