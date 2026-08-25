"""The shape every tool result takes.

A list-shaped payload separates a scannable index from the bodies: an agent
reads `formatted` to decide where to look, and pays for prose only where it
committed. Each entry carries the identifiers that address it, so one call
chains into the next without the caller reconstructing references.
"""

from __future__ import annotations

from typing import Any

from ...storage.port import SearchHit
from .fencing import NOTICE, fence, new_nonce, provenance


def one_line(text: str, limit: int = 160) -> str:
    """Collapse a value to a single line.

    Applied to every document-derived value that reaches a line-oriented block.
    Filenames and headings come from the corpus, so a newline in one would
    otherwise forge extra rows in an index the agent is told to read first.
    """
    collapsed = " ".join((text or "").split())
    return collapsed if len(collapsed) <= limit else collapsed[: limit - 1] + "…"


def search_payload(hits: list[SearchHit], query: str, casefile_id: str) -> dict[str, Any]:
    """Search results: an index to scan, and each passage body exactly once."""
    nonce = new_nonce()
    lines: list[str] = []
    results: list[dict[str, Any]] = []

    for index, hit in enumerate(hits, start=1):
        heading = one_line(hit.chunk.heading_path, 60)
        where = f" · {heading}" if heading else ""
        # The index carries no passage prose. Everything the agent reads here is
        # metadata; the body lives under `results`, fenced, and appears once.
        lines.append(
            f"{index}. [{hit.chunk.short_id}] {one_line(hit.document.filename, 80)}{where} "
            f"({len(hit.chunk.text)} chars, score {round(hit.score, 4)})"
        )
        results.append(
            {
                "chunk_id": hit.chunk.id,
                "document_id": hit.document.id,
                "document": hit.document.filename,
                "score": round(hit.score, 6),
                "found_by": {
                    "keyword_rank": hit.keyword_rank,
                    "vector_rank": hit.vector_rank,
                },
                "provenance": provenance(
                    casefile_id=casefile_id,
                    document_id=hit.document.id,
                    filename=hit.document.filename,
                    char_start=hit.chunk.char_start,
                    char_end=hit.chunk.char_end,
                    heading_path=hit.chunk.heading_path,
                ),
                # The only place a passage body appears, and it is fenced.
                "text": fence(hit.chunk.text, nonce),
            }
        )

    return {
        "query": query,
        "total": len(hits),
        "formatted": "\n".join(lines) if lines else "No matching passages.",
        "results": results,
        "content_notice": NOTICE,
        "fence_nonce": nonce,
    }


def listing_payload(
    rows: list[dict[str, Any]], *, formatted: str, total: int | None = None
) -> dict[str, Any]:
    """A listing that carries no corpus prose, so it needs no fence."""
    return {
        "total": len(rows) if total is None else total,
        "formatted": formatted,
        "results": rows,
    }
