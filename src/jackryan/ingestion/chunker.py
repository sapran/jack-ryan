"""Dividing extracted text into retrievable units.

Chunking is governed by the corpus contract and is deterministic: the same text
and contract always produce the same chunks, which is what makes the contract
fingerprint a meaningful statement about a corpus.
"""

from __future__ import annotations

import re
from bisect import bisect_right
from dataclasses import dataclass

_PARAGRAPH_BREAK = re.compile(r"\n\s*\n")
_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")

# Heading text is document content, so it is untrusted and unbounded. It is
# copied into every chunk beneath it, which turns one long heading into storage
# proportional to heading length times chunk count. Capping it at the source is
# what keeps a chunk's context small relative to the chunk itself.
MAX_HEADING_CHARS = 200
MAX_HEADING_PATH_CHARS = 512


@dataclass(frozen=True)
class TextChunk:
    """A span of text with its position in the source and the headings above it.

    The offsets select `text` exactly: `source[char_start:char_end] == text`.
    They name the trimmed span rather than the window it came from, because a
    document position derived from them plus an offset inside `text` is
    otherwise wrong by the whitespace that was trimmed.
    """

    ordinal: int
    text: str
    char_start: int
    char_end: int
    heading_path: str


def _heading_trails(text: str) -> tuple[list[int], list[str]]:
    """Scan the document once, resolving the heading trail at every heading.

    Both the scan and the trail resolution happen here, so chunking never walks
    back over text or headings it has already seen — the difference between
    linear and quadratic on a large document.
    """
    offsets: list[int] = []
    trails: list[str] = []
    trail: dict[int, str] = {}
    position = 0
    for line in text.splitlines(keepends=True):
        match = _HEADING.match(line.strip())
        if match:
            level = len(match.group(1))
            trail = {lvl: t for lvl, t in trail.items() if lvl < level}
            trail[level] = match.group(2).strip()[:MAX_HEADING_CHARS]
            offsets.append(position)
            trails.append(
                " > ".join(trail[lvl] for lvl in sorted(trail))[:MAX_HEADING_PATH_CHARS]
            )
        position += len(line)
    return offsets, trails


def _trail_at(offsets: list[int], trails: list[str], line_start: int) -> str:
    """The heading trail governing a chunk that begins at ``line_start``.

    Only headings whose own line starts strictly before the chunk count, so a
    heading can never label the chunk it introduces from behind, and a heading
    split across a boundary cannot contribute a fragment.
    """
    index = bisect_right(offsets, line_start - 1)
    return trails[index - 1] if index else ""


def _line_start(text: str, position: int) -> int:
    """Snap back to the start of the line containing ``position``."""
    if position <= 0:
        return 0
    newline = text.rfind("\n", 0, position)
    return 0 if newline == -1 else newline + 1


def chunk_text(text: str, *, max_chars: int, overlap_chars: int) -> list[TextChunk]:
    """Split text into overlapping windows, preferring paragraph boundaries."""
    if max_chars < 1:
        raise ValueError("max_chars must be positive")
    if overlap_chars >= max_chars:
        raise ValueError("overlap_chars must be smaller than max_chars")

    if not text.strip():
        return []

    offsets, trails = _heading_trails(text)

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
        # The stored text is the window trimmed, so what is recorded must be the
        # trimmed span and not the window. A start naming the window is wrong by
        # the leading whitespace, and anything that adds an in-chunk offset to it
        # — a mention's document position — lands before the characters it claims
        # to address. Two overlapping windows that trimmed unequal whitespace
        # then disagree about where one occurrence sits, and the identifier
        # inventory counts it twice.
        body = piece.strip()
        if body:
            start = position + (len(piece) - len(piece.lstrip()))
            chunks.append(
                TextChunk(
                    ordinal=ordinal,
                    text=body,
                    char_start=start,
                    char_end=start + len(body),
                    # Resolved from the window's own start, deliberately not from
                    # `start`: a trimmed start can sit past a heading its window
                    # opened on, which would move the heading path recorded for
                    # chunks this change is not about.
                    heading_path=_trail_at(offsets, trails, _line_start(text, position)),
                )
            )
            ordinal += 1

        if window_end >= length:
            break
        # Step back by the overlap, but never past half the window actually
        # taken. A fixed step-back can otherwise crawl a character at a time
        # when a boundary lands early, turning one document into millions of
        # near-identical chunks.
        taken = window_end - position
        step_back = min(overlap_chars, taken // 2)
        position = max(window_end - step_back, position + 1)

    return chunks
