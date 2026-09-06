"""The window rule, exercised on documents written out here rather than ingested.

Every other window test drives `context.search.search(...)`, so what the rule is
given depends on what a fixture happened to produce. `CLAUDE.md` records the cost
of that: three window tests once passed while proving nothing, because the corpus
they ran against had one passage per document and a window over a single passage
is the whole document.

Here the neighbouring passages are a list in the test. A test that widens nothing
says so, because the input that would have widened is visible three lines up.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from jackryan.services.windowing import Windower
from jackryan.storage.port import Chunk, Document, SearchHit

CASEFILE = "case-1"
DOCUMENT = "doc-1"


def _laid_out(parts: list[str]) -> tuple[str, list[tuple[int, int]]]:
    """Join parts with a blank line; return the text and each part's own span."""
    text = ""
    spans: list[tuple[int, int]] = []
    for part in parts:
        if text:
            text += "\n\n"
        start = len(text)
        text += part
        spans.append((start, len(text)))
    return text, spans


def _document(text: str) -> Document:
    stamp = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return Document(
        id=DOCUMENT,
        casefile_id=CASEFILE,
        content_hash="0" * 64,
        filename="report.md",
        media_type="text/markdown",
        byte_size=len(text.encode("utf-8")),
        extracted_text=text,
        extractor="test",
        created_at=stamp,
        updated_at=stamp,
    )


def _chunk(text: str, ordinal: int, span: tuple[int, int], heading: str = "Survey") -> Chunk:
    start, end = span
    return Chunk(
        id=f"chunk-{ordinal}",
        document_id=DOCUMENT,
        casefile_id=CASEFILE,
        ordinal=ordinal,
        heading_path=heading,
        # Stripped, because that is what the ingestion pipeline stores and what
        # `_slice` compares the offsets against.
        text=text[start:end].strip(),
        char_start=start,
        char_end=end,
    )


def _neighbours_of(chunks: list[Chunk]):
    """The one question the window rule asks a store, answered from a list."""

    def lookup(document_id: str, ordinal: int, radius: int) -> list[Chunk]:
        return [
            chunk
            for chunk in chunks
            if chunk.document_id == document_id and abs(chunk.ordinal - ordinal) <= radius
        ]

    return lookup


def _hit(chunk: Chunk, document: Document, rank: int) -> SearchHit:
    return SearchHit(
        chunk=chunk,
        document=document,
        score=1.0 / rank,
        keyword_rank=rank,
        vector_rank=None,
    )


# A document with one section: four paragraphs under one heading, each carrying a
# word that appears nowhere else so an assertion can name what a window reached.
PARAGRAPHS = [
    "# Survey",
    "The dredging began in spring and the contractor reported no obstruction.",
    "A second barge arrived and the mooring buoy was replaced that same week.",
    "The kingfisher was recorded twice near the eastern bank of the channel.",
    "A cormorant was seen on the pontoon on the final day of the survey.",
]


@pytest.fixture
def one_section() -> tuple[Document, list[Chunk]]:
    """Four passages in one section, ordinals 0-3, the heading line outside them."""
    text, spans = _laid_out(PARAGRAPHS)
    document = _document(text)
    chunks = [_chunk(text, ordinal, spans[ordinal + 1]) for ordinal in range(4)]
    return document, chunks


def test_a_window_is_wider_than_the_passage_that_matched(one_section):
    """The point of the whole rule, and the thing a fixture can silently defeat."""
    document, chunks = one_section
    windower = Windower(_neighbours_of(chunks), budget=4000)

    matched = chunks[1]
    window = windower.for_passage(matched, document)

    assert window is not None, "no window at all: nothing was widened"
    passage_width = matched.char_end - matched.char_start
    window_width = window.char_end - window.char_start
    assert window_width > passage_width, (
        f"the window is {window_width} characters and the passage it grew from is "
        f"{passage_width}; the rule returned the passage back"
    )


def test_the_window_is_a_slice_of_the_documents_own_text(one_section):
    """Never assembled from chunk texts: chunks overlap, and a join repeats it."""
    document, chunks = one_section
    windower = Windower(_neighbours_of(chunks), budget=4000)

    window = windower.for_passage(chunks[1], document)

    assert window is not None
    assert window.text == document.extracted_text[window.char_start : window.char_end]


def test_a_window_contains_the_passage_that_matched(one_section):
    """Widening what is read never changes what matched."""
    document, chunks = one_section
    windower = Windower(_neighbours_of(chunks), budget=4000)

    matched = chunks[2]
    window = windower.for_passage(matched, document)

    assert window is not None
    assert window.char_start <= matched.char_start
    assert window.char_end >= matched.char_end
    assert matched.text in window.text


def test_a_heading_line_stops_a_window_that_would_cross_it():
    """The heading trail is not enough on its own: the `#` line is the boundary.

    Both documents give every passage the same heading path, so the section
    bounds do not stop the window. The only difference is whether the line
    between the third and fourth passages begins with `#`.
    """
    tail = "The cormorant was seen on the pontoon on the final day."
    with_heading, spans_a = _laid_out([*PARAGRAPHS[:4], "## Tariffs", tail])
    without_heading, spans_b = _laid_out([*PARAGRAPHS[:4], "Tariffs were agreed.", tail])

    def widened(text: str, spans: list[tuple[int, int]]) -> str:
        document = _document(text)
        # Ordinals 0-2 are the three paragraphs; ordinal 3 is the line that
        # differs; ordinal 4 is the tail the window may or may not reach.
        chunks = [_chunk(text, ordinal, spans[ordinal + 1]) for ordinal in range(4)]
        windower = Windower(_neighbours_of(chunks), budget=4000)
        window = windower.for_passage(chunks[2], document)
        assert window is not None, "nothing widened, so this comparison says nothing"
        return window.text

    assert "Tariffs" not in widened(with_heading, spans_a), (
        "the window crossed a heading line"
    )
    assert "Tariffs" in widened(without_heading, spans_b), (
        "the window stopped short without a heading to stop it, so the other "
        "assertion proves nothing about headings"
    )


def test_a_passage_with_no_neighbours_is_not_widened(one_section):
    """The store answering 'nothing surrounds this' must not become a window."""
    document, chunks = one_section
    alone = Windower(lambda *_: [], budget=4000)

    assert alone.for_passage(chunks[1], document) is None
    # And the same call with the neighbours present does widen, so the assertion
    # above is about the empty answer rather than about the budget.
    assert Windower(_neighbours_of(chunks), budget=4000).for_passage(
        chunks[1], document
    ) is not None


def test_a_budget_at_the_passage_size_widens_nothing(one_section):
    """An operator who does not want windows sets the budget to a passage."""
    document, chunks = one_section
    windower = Windower(_neighbours_of(chunks), budget=1)

    assert windower.for_passage(chunks[1], document) is None


def test_another_results_passage_narrows_this_one_and_the_flag_says_so(one_section):
    """`narrowed` separates 'gave way to a neighbour' from 'had nothing to give'."""
    document, chunks = one_section
    windower = Windower(_neighbours_of(chunks), budget=4000)

    blocked = [(chunks[2].char_start, chunks[2].char_end)]
    narrow, was_narrowed = windower.around(chunks[1], document, 4000, blocked=blocked)
    wide, not_narrowed = windower.around(chunks[1], document, 4000)

    assert wide is not None and narrow is not None
    assert not not_narrowed
    assert was_narrowed, "a window cut short by another result did not say so"
    assert narrow.char_end < wide.char_end, (
        "the blocked span changed the flag without changing the window"
    )


def test_no_text_is_returned_twice_across_one_response(one_section):
    """Two results in one document must not hand the same characters over twice."""
    document, chunks = one_section
    windower = Windower(_neighbours_of(chunks), budget=4000)

    hits = windower.for_results([_hit(chunks[0], document, 1), _hit(chunks[3], document, 2)])

    spans = [(hit.char_start, hit.char_end) for hit in hits]
    (first_start, first_end), (second_start, second_end) = spans
    assert first_end <= second_start or second_end <= first_start, (
        f"the two results overlap: {spans}"
    )


def test_the_response_bound_drops_context_and_never_a_result(one_section, monkeypatch):
    """Bounded text, unbounded evidence: nothing is withheld to meet the bound."""
    import jackryan.services.windowing as windowing_module

    document, chunks = one_section
    windower = Windower(_neighbours_of(chunks), budget=4000)

    generous = windower.for_results([_hit(chunk, document, n + 1) for n, chunk in enumerate(chunks)])
    monkeypatch.setattr(windowing_module, "MAX_RESPONSE_CHARS", 120)
    bounded = windower.for_results([_hit(chunk, document, n + 1) for n, chunk in enumerate(chunks)])

    assert [hit.chunk.id for hit in bounded] == [hit.chunk.id for hit in generous]
    assert any(hit.narrowed for hit in bounded), "the bound was never reached"
    assert sum(len(hit.text) for hit in bounded) < sum(len(hit.text) for hit in generous)
    # `narrowed` does not imply "window withdrawn" — a result cut back to make
    # room for a neighbour keeps a smaller one. What holds in every case is that
    # the passage itself is still carried, because the bound governs the context
    # added and never the evidence found.
    assert all(hit.chunk.text in hit.text for hit in bounded)


def test_a_stale_offset_is_not_widened(one_section):
    """New text against old offsets means the span selects somebody else's words."""
    document, chunks = one_section
    windower = Windower(_neighbours_of(chunks), budget=4000)
    shifted = _document("x" * len(document.extracted_text))

    assert windower.for_passage(chunks[1], shifted) is None
