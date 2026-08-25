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


def _one_line(text: str, limit: int = 160) -> str:
    collapsed = " ".join(text.split())
    return collapsed if len(collapsed) <= limit else collapsed[: limit - 1] + "…"


def search_payload(hits: list[SearchHit], query: str, casefile_id: str) -> dict[str, Any]:
    """Search results: an index to scan, and each passage body exactly once."""
    nonce = new_nonce()
    lines: list[str] = []
    results: list[dict[str, Any]] = []

    for index, hit in enumerate(hits, start=1):
        where = f" · {hit.chunk.heading_path}" if hit.chunk.heading_path else ""
        lines.append(
            f"{index}. [{hit.chunk.short_id}] {hit.document.filename}{where} — "
            f"{_one_line(hit.chunk.text, 110)}"
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
                # The body appears here and nowhere else in the payload.
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
