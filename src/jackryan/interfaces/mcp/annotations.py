"""How each tool is stamped.

One table rather than a decorator at each definition: thirty scattered
declarations drift, and a single table can be reviewed at a glance. A tool the
table does not name is a failure, because advertising a tool without describing
its risk is worse than not advertising it.

Each tool is stamped by its *worst reachable* mode, not its typical one.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Stamp:
    read_only: bool
    destructive: bool
    open_world: bool


# `open_world` is False throughout: every tool here reads this instance's own
# store and reaches nothing beyond it.
ANNOTATIONS: dict[str, Stamp] = {
    "case_list_casefiles": Stamp(read_only=True, destructive=False, open_world=False),
    "case_casefile_overview": Stamp(read_only=True, destructive=False, open_world=False),
    "case_list_documents": Stamp(read_only=True, destructive=False, open_world=False),
    "case_search": Stamp(read_only=True, destructive=False, open_world=False),
    "case_get_passage": Stamp(read_only=True, destructive=False, open_world=False),
    "case_read_document": Stamp(read_only=True, destructive=False, open_world=False),
    "case_cite": Stamp(read_only=True, destructive=False, open_world=False),
    "case_mentions": Stamp(read_only=True, destructive=False, open_world=False),
}


class UnstampedToolError(RuntimeError):
    """A tool exists that the annotations table does not describe."""


def stamp_for(tool_name: str) -> Stamp:
    try:
        return ANNOTATIONS[tool_name]
    except KeyError as exc:
        raise UnstampedToolError(
            f"tool {tool_name!r} is not named in the annotations table; "
            "add it there rather than letting it be advertised unstamped"
        ) from exc
