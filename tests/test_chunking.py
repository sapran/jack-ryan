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
        assert TEXT[chunk.char_start : chunk.char_end].strip() == chunk.text


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
