"""Dividing extracted text into retrievable units.

Chunking is governed by the corpus contract and is deterministic: the same text
and contract always produce the same chunks, which is what makes the contract
fingerprint a meaningful statement about a corpus.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_PARAGRAPH_BREAK = re.compile(r"\n\s*\n")
_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")


@dataclass(frozen=True)
class TextChunk:
    """A span of text with its position in the source and the headings above it."""

    ordinal: int
    text: str
    char_start: int
    char_end: int
    heading_path: str


def _heading_at(line: str) -> tuple[int, str] | None:
    match = _HEADING.match(line.strip())
    if not match:
        return None
    return len(match.group(1)), match.group(2).strip()


def _heading_path_for(text: str, upto: int) -> str:
    """The heading trail above a position, so a passage keeps its context."""
    trail: dict[int, str] = {}
    for line in text[:upto].splitlines():
        found = _heading_at(line)
        if found:
            level, title = found
            trail = {lvl: t for lvl, t in trail.items() if lvl < level}
            trail[level] = title
    return " > ".join(trail[lvl] for lvl in sorted(trail))


def chunk_text(text: str, *, max_chars: int, overlap_chars: int) -> list[TextChunk]:
    """Split text into overlapping windows, preferring paragraph boundaries."""
    if max_chars < 1:
        raise ValueError("max_chars must be positive")
    if overlap_chars >= max_chars:
        raise ValueError("overlap_chars must be smaller than max_chars")

    if not text.strip():
        return []

    chunks: list[TextChunk] = []
    position = 0
    ordinal = 0
    length = len(text)

    while position < length:
        window_end = min(position + max_chars, length)

        # Prefer a paragraph break inside the back half of the window, so
        # passages tend to end where the writing does.
        if window_end < length:
            search_from = position + (max_chars // 2)
            candidates = [m.end() for m in _PARAGRAPH_BREAK.finditer(text, search_from, window_end)]
            if candidates:
                window_end = candidates[-1]

        piece = text[position:window_end]
        if piece.strip():
            chunks.append(
                TextChunk(
                    ordinal=ordinal,
                    text=piece.strip(),
                    char_start=position,
                    char_end=window_end,
                    heading_path=_heading_path_for(text, position),
                )
            )
            ordinal += 1

        if window_end >= length:
            break
        # Step forward by at least one character, so progress is guaranteed
        # however the boundary search landed.
        position = max(window_end - overlap_chars, position + 1)

    return chunks
