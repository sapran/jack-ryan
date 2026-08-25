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
from .app import build_context
from .errors import JackRyanError
from .storage.port import Casefile


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


def _print(payload: Any, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, indent=2))
        return
    if isinstance(payload, list):
        if not payload:
            print("No casefiles yet. Create one with: jackryan casefile create <title>")
            return
        for item in payload:
            print(f"{item['short_id']}  {item['slug']:<28}  {item['title']}")
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

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    context = build_context()
    try:
        if args.command == "status":
            _print(
                {
                    "version": __version__,
                    "profile": context.config.profile.name,
                    "data_dir": str(context.config.data_dir),
                    "database": str(context.config.db_path),
                    "contract": context.config.contract.fingerprint(),
                    "casefiles": len(context.casefiles.list()),
                },
                args.json,
            )
            return 0

        service = context.casefiles
        if args.casefile_command == "create":
            _print(_render(service.create(args.title, args.description, args.slug)), args.json)
        elif args.casefile_command == "list":
            _print([_render(c) for c in service.list()], args.json)
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
