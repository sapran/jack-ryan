"""The window rule: how far a result's text grows around the passage that matched.

Everything here is arithmetic over character spans plus one slice of a
document's own text. The single outside question — which passages sit either
side of this one — arrives as a callable, so this module reaches no store and
needs no corpus to exercise. That is deliberate: a window rule that can only be
tested through a search is one whose fixtures decide what it proves, and three
window tests once passed for exactly that reason.

What is *not* here, and must not move here: the reranker scores the matched
passage, never a window. It runs in `search.py` before any widening, because the
reranking library truncates a query-and-passage pair at the model's own limit
with no override, and a window would be cut inside it.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import replace

from ..storage.port import Chunk, Document, SearchHit, Window

# Answers "which passages surround this one": document id, the matched
# passage's ordinal, and how many either side to return — the three arguments
# `StorePort.get_document_chunks_around` takes, in its order.
Neighbours = Callable[[str, int, int], list[Chunk]]

DEFAULT_WINDOW_MAX_CHARS = 3000

# How much corpus text one response may carry, over every result together. A
# bound on the number of results was enough only while a result was one chunk;
# once a result may be widened, a permitted count no longer implies a permitted
# quantity of text.
MAX_RESPONSE_CHARS = 60_000

# A window reaches at most this many chunks either side of the matched one,
# whatever the character budget allows. The budget bounds how much text an agent
# is handed; this bounds how far a single result may wander from what actually
# matched, which is a different question.
WINDOW_MAX_CHUNKS_EITHER_SIDE = 3


# The same heading line the chunker reads when it builds a heading trail
# (`src/jackryan/ingestion/chunker.py`). Markdown only, which is the limit of
# what this codebase knows about document structure: a scan or a plain text file
# has no headings, and there the character budget is the only bound.
_HEADING_LINE = re.compile(r"^#{1,6}\s+\S", re.MULTILINE)


def _section_bounds(chunk: Chunk, neighbours: list[Chunk]) -> tuple[int, int]:
    """How far the matched chunk's section reaches, in document characters.

    Section membership is decided by the heading trail the chunker recorded, and
    only the run of chunks contiguous with the matched one counts: a document
    that repeats a heading elsewhere must not pull distant text into the window.

    A document with no headings — a scan, a plain text file — has an empty trail
    on every chunk, and every neighbour then belongs to the same section. That is
    the honest answer for a document with no sections to respect: the character
    budget is the only bound left.
    """
    low, high = chunk.char_start, chunk.char_end
    by_ordinal = {c.ordinal: c for c in neighbours}

    for step in (-1, 1):
        ordinal = chunk.ordinal + step
        while ordinal in by_ordinal:
            neighbour = by_ordinal[ordinal]
            if neighbour.heading_path != chunk.heading_path:
                break
            low = min(low, neighbour.char_start)
            high = max(high, neighbour.char_end)
            ordinal += step
    return low, high


def _clip_to_headings(text: str, span: tuple[int, int], chunk: Chunk) -> tuple[int, int]:
    """Cut the window at any heading line it would cross.

    The chunk's recorded heading trail is not enough on its own. A chunk may
    straddle a heading — it begins in one section and runs past the next
    heading — and it carries the trail of where it began, so a window built from
    trails alone reaches into a section it should not. The heading line in the
    text is the boundary itself, and it is the same `#` line the chunker read.

    A heading immediately before the matched passage is kept: it names the
    section the passage is in, which is context rather than intrusion. A heading
    inside the matched chunk is left alone — that text is the result.
    """
    start, end = span
    before = text[start : chunk.char_start]
    matches = list(_HEADING_LINE.finditer(before))
    if matches:
        start += matches[-1].start()

    after = text[chunk.char_end : end]
    following = _HEADING_LINE.search(after)
    if following:
        end = chunk.char_end + following.start()
    return start, end


def _widen(chunk: Chunk, low: int, high: int, budget: int) -> tuple[int, int]:
    """Grow the chunk's span toward the section's edges, within the budget.

    Grown both ways rather than forward only: a passage is as likely to need the
    sentence before it as the one after. What one side cannot use, the other
    takes, so a chunk at the very start of a section still gains its full budget
    from below.
    """
    room = budget - (chunk.char_end - chunk.char_start)
    if room <= 0:
        return chunk.char_start, chunk.char_end

    before_available = chunk.char_start - low
    after_available = high - chunk.char_end
    before = min(room // 2, before_available)
    after = min(room - before, after_available)
    # Whatever the far side could not use comes back to this one.
    before = min(before_available, room - after)
    return chunk.char_start - before, chunk.char_end + after


def _keep_clear(
    low: int, high: int, chunk: Chunk, blocked: list[tuple[int, int]]
) -> tuple[int, int]:
    """Never grow across a passage another result in this response matched.

    Known before any widening happens, because the whole ranking is in hand: a
    window that swallowed a later result's passage would make the same text
    arrive twice, once as context and once as a hit.

    A passage that already overlaps this one — adjacent chunks share
    `chunk_overlap_chars` by configuration — still stops the window at its own
    edge, clamped so that this chunk never loses text of its own. Skipping such
    a neighbour entirely would let a window run straight through the passage it
    overlaps, which is the case this exists to prevent.
    """
    for start, end in blocked:
        if start > chunk.char_start:
            high = min(high, max(start, chunk.char_end))
        if end < chunk.char_end:
            low = max(low, min(end, chunk.char_start))
    return low, high


def _avoid(
    span: tuple[int, int], chunk_span: tuple[int, int], covered: list[tuple[int, int]]
) -> tuple[int, int] | None:
    """Pull a window back so it does not repeat text already returned.

    Never inside the matched chunk: that text is the result. When something
    already returned overlaps the chunk itself there is nothing to pull back to,
    and the caller falls back to the chunk alone.
    """
    start, end = span
    chunk_start, chunk_end = chunk_span
    for covered_start, covered_end in covered:
        if covered_end <= start or covered_start >= end:
            continue
        if covered_end <= chunk_start:
            start = max(start, covered_end)
        elif covered_start >= chunk_end:
            end = min(end, covered_start)
        else:
            return None
    return start, end


def _slice(document: Document, chunk: Chunk, span: tuple[int, int]) -> Window | None:
    """One contiguous slice of the document's own text, or nothing.

    Nothing when the span adds nothing but whitespace to the passage: a window
    identical to the passage is not a window, and saying so keeps "was this
    widened" a question with an answer. Compared by text rather than by span,
    because the two are not the same test. A chunk's offsets now select its
    stored text exactly, so a section's last passage is followed by the
    paragraph break its own span no longer covers, and clipping at the next
    heading leaves a span two characters wider than the chunk's own — a window
    whose whole content is `\\n\\n`. Comparing spans reported that as widened.

    Nothing, too, when the stored offsets no longer select the stored
    passage. Ingestion writes a document and its chunks in two transactions
    with a fallible embedding call between them, so a run that fails in the
    middle leaves new text against old offsets. Widening on those would
    return a passage from elsewhere in the document as the result's body,
    fenced as evidence, under provenance naming a span it never occupied.
    The chunk's own text is still right, so the result falls back to it.

    Both comparisons trim before comparing, which is also what lets one rule
    serve a corpus holding rows written under either convention.
    """
    text = document.extracted_text
    if text[chunk.char_start : chunk.char_end].strip() != chunk.text:
        return None
    start = max(0, span[0])
    end = min(len(text), span[1])
    if start >= end or text[start:end].strip() == chunk.text:
        return None
    return Window(text=text[start:end], char_start=start, char_end=end)


class Windower:
    """The window rule, holding a budget and a way to find neighbouring passages.

    Takes a callable rather than a `StorePort` because it asks the store one
    question out of the nineteen the port declares. A test can answer that
    question with a list; satisfying the port means building a corpus.
    """

    def __init__(self, neighbours: Neighbours, budget: int) -> None:
        self._neighbours = neighbours
        self._budget = int(budget)

    @property
    def budget(self) -> int:
        """The character budget actually in force.

        Readable so that a caller wanting to assert on the configured budget can
        read the value this rule applies, rather than a copy kept beside it. A
        copy is what lets a wiring test keep passing while the budget it names
        reaches nothing.
        """
        return self._budget

    def for_passage(self, chunk: Chunk, document: Document) -> Window | None:
        """The window around one passage, asked for on its own.

        The second half of `around`'s answer is discarded because there is no
        response for another result to have narrowed this one against.
        """
        window, _ = self.around(chunk, document, self._budget)
        return window

    def around(
        self,
        chunk: Chunk,
        document: Document,
        budget: int,
        blocked: list[tuple[int, int]] | None = None,
    ) -> tuple[Window | None, bool]:
        """The window, and whether other results in the response reduced it.

        The second value is what a caller reports as `narrowed`. Without it a
        result cut back to make room for a neighbour looks exactly like one that
        had no more context to give, which is the confusion the flag exists to
        prevent.
        """
        if budget <= chunk.char_end - chunk.char_start:
            return None, False

        neighbours = self._neighbours(
            chunk.document_id, chunk.ordinal, WINDOW_MAX_CHUNKS_EITHER_SIDE
        )
        low, high = _section_bounds(chunk, neighbours)
        text = document.extracted_text

        kept_low, kept_high = _keep_clear(low, high, chunk, blocked or [])
        span = _clip_to_headings(text, _widen(chunk, kept_low, kept_high, budget), chunk)
        window = _slice(document, chunk, span)

        if (kept_low, kept_high) == (low, high):
            return window, False
        # Cheap because both are pure arithmetic over spans already in hand: ask
        # what this result would have carried with the response to itself.
        alone = _clip_to_headings(text, _widen(chunk, low, high, budget), chunk)
        return window, alone != span

    def for_results(self, hits: list[SearchHit]) -> list[SearchHit]:
        """Widen each result in rank order, repeating no text and staying bounded.

        Rank order matters: the best result gets its full window, and a lower one
        gives way. The alternative — widening everything and merging afterwards —
        would let a weak result decide what a strong one is allowed to carry.
        """
        covered: dict[str, list[tuple[int, int]]] = {}
        spent = 0
        widened: list[SearchHit] = []

        # Every matched passage in this response, so no window grows across one.
        matched: dict[str, list[tuple[int, int]]] = {}
        for hit in hits:
            matched.setdefault(hit.document.id, []).append(
                (hit.chunk.char_start, hit.chunk.char_end)
            )

        for hit in hits:
            others = [
                span
                for span in matched.get(hit.document.id, [])
                if span != (hit.chunk.char_start, hit.chunk.char_end)
            ]
            # `narrowed` starts from whether another result's passage already
            # cost this one context — not only from the two checks below.
            window, narrowed = self.around(
                hit.chunk, hit.document, self._budget, blocked=others
            )

            if window is not None:
                kept = _avoid(
                    (window.char_start, window.char_end),
                    (hit.chunk.char_start, hit.chunk.char_end),
                    covered.get(hit.document.id, []),
                )
                if kept is None:
                    window, narrowed = None, True
                elif kept != (window.char_start, window.char_end):
                    window = _slice(hit.document, hit.chunk, kept)
                    narrowed = True

            if window is not None and spent + len(window.text) > MAX_RESPONSE_CHARS:
                window, narrowed = None, True

            hit = replace(hit, window=window, narrowed=narrowed)
            spent += len(hit.text)
            covered.setdefault(hit.document.id, []).append((hit.char_start, hit.char_end))
            widened.append(hit)

        return widened
