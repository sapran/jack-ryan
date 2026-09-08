"""Chunking is contract-governed, deterministic, and locatable."""

from __future__ import annotations

import pytest

from jackryan.ingestion.chunker import chunk_text

TEXT = (
    "# Harbour Lease\n\n"
    "Northgate Holdings was awarded the lease in March 2021.\n\n"
    "## Conditions\n\n"
    "The award carried dredging obligations and an annual tariff review.\n\n"
    "## Objections\n\n"
    "Two councillors recorded objections on procedural grounds.\n"
)


def test_chunking_is_reproducible():
    assert chunk_text(TEXT, max_chars=120, overlap_chars=20) == chunk_text(
        TEXT, max_chars=120, overlap_chars=20
    )


def test_offsets_locate_each_chunk_in_the_source():
    for chunk in chunk_text(TEXT, max_chars=120, overlap_chars=20):
        assert TEXT[chunk.char_start : chunk.char_end] == chunk.text


def test_offsets_select_a_chunk_whose_window_opened_on_whitespace():
    """Catches offsets that name the window rather than the text stored from it.

    The whitespace sits at exactly the offset the second window starts from —
    `max_chars - overlap_chars`, where the chunker steps back to — so the second
    chunk's stored text begins three characters after its window does. A single
    newline throughout: a blank line would be a paragraph break, the boundary
    would move, and the fixture would stop proving anything.
    """
    text = "A" * 350 + " \n " + "B" * 400
    assert text[400 - 50].isspace(), (
        "the second window does not open on whitespace, so this fixture cannot "
        "tell a window's offsets from its text's"
    )

    chunks = chunk_text(text, max_chars=400, overlap_chars=50)

    assert len(chunks) > 1, "one chunk cannot show an overlapping window's offsets"
    for chunk in chunks:
        assert text[chunk.char_start : chunk.char_end] == chunk.text, (
            f"chunk {chunk.ordinal}'s offsets select "
            f"{text[chunk.char_start : chunk.char_end]!r}, not its stored text"
        )


def test_chunks_are_ordered_and_numbered_from_zero():
    chunks = chunk_text(TEXT, max_chars=120, overlap_chars=20)
    assert [c.ordinal for c in chunks] == list(range(len(chunks)))
    assert all(a.char_start < b.char_start for a, b in zip(chunks, chunks[1:]))


def test_a_smaller_contract_produces_more_chunks():
    assert len(chunk_text(TEXT, max_chars=80, overlap_chars=10)) > len(
        chunk_text(TEXT, max_chars=400, overlap_chars=10)
    )


def test_short_text_is_one_chunk():
    assert len(chunk_text("A single short line.", max_chars=400, overlap_chars=50)) == 1


def test_blank_text_produces_nothing():
    assert chunk_text("   \n\n  ", max_chars=400, overlap_chars=50) == []


def test_headings_above_a_chunk_are_recorded():
    chunks = chunk_text(TEXT, max_chars=100, overlap_chars=10)
    assert any("Harbour Lease" in c.heading_path for c in chunks[1:])


def test_overlap_must_be_smaller_than_the_window():
    with pytest.raises(ValueError, match="smaller"):
        chunk_text(TEXT, max_chars=100, overlap_chars=100)


def test_chunking_always_advances():
    # A window that lands badly must still terminate rather than loop.
    chunks = chunk_text("x" * 5000, max_chars=100, overlap_chars=99)
    assert len(chunks) > 0
    assert chunks[-1].char_end == 5000
