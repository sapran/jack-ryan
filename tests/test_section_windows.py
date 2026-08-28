"""Section windows: a result's text is wider than the passage that matched it.

The passage stays the unit that is addressed and cited; only what is read grows.
These tests hold both halves of that: the window is a real slice of the document,
and the matched chunk keeps its identity and its offsets.
"""

from __future__ import annotations

import pytest

from jackryan.services.search import (
    MAX_RESPONSE_CHARS,
    _avoid,
    _section_bounds,
    _widen,
)
from jackryan.storage.port import Chunk

ALPHA = " ".join(f"Alpha sentence {n} about the dredging survey." for n in range(1, 26))
BETA = " ".join(f"Beta sentence {n} about the tariff schedule." for n in range(1, 26))
# Long enough that one matched passage still has unmatched neighbours to grow
# into, and carrying one word that appears nowhere else so a query can pick out
# a single passage of it.
FLAT = " ".join(
    f"Plain line {n} recording the harbour watch."
    if n != 30
    else "Plain line 30 recording a cormorant on the mooring buoy."
    for n in range(1, 61)
)


@pytest.fixture
def sectioned(context, tmp_path):
    """One document with two headed sections, and one with no headings at all."""
    folder = tmp_path / "windows"
    folder.mkdir()
    (folder / "report.md").write_text(
        f"# Survey Report\n\n## Alpha\n\n{ALPHA}\n\n## Beta\n\n{BETA}\n",
        encoding="utf-8",
    )
    (folder / "watch.txt").write_text(FLAT + "\n", encoding="utf-8")
    casefile = context.casefiles.create("Windows")
    report = context.ingestion.ingest(casefile.short_id, folder)
    assert not report.failed
    return context, casefile


def _chunk(ordinal: int, start: int, end: int, heading: str = "h") -> Chunk:
    return Chunk(
        id=f"c{ordinal}",
        document_id="doc",
        casefile_id="cf",
        ordinal=ordinal,
        heading_path=heading,
        text="x" * (end - start),
        char_start=start,
        char_end=end,
    )


# --- the rules, in isolation ----------------------------------------------


def test_section_bounds_stop_at_a_heading_change():
    matched = _chunk(1, 100, 200, heading="Doc > Alpha")
    neighbours = [
        _chunk(0, 0, 100, heading="Doc > Alpha"),
        matched,
        _chunk(2, 200, 300, heading="Doc > Beta"),
    ]
    assert _section_bounds(matched, neighbours) == (0, 200)


def test_section_bounds_do_not_jump_a_gap_to_a_repeated_heading():
    """A document that uses one heading twice must not pull distant text in."""
    matched = _chunk(2, 200, 300, heading="Doc > Alpha")
    neighbours = [
        _chunk(0, 0, 100, heading="Doc > Alpha"),
        _chunk(1, 100, 200, heading="Doc > Other"),
        matched,
        _chunk(3, 300, 400, heading="Doc > Alpha"),
    ]
    assert _section_bounds(matched, neighbours) == (200, 400)


def test_a_document_without_headings_has_one_section():
    matched = _chunk(1, 100, 200, heading="")
    neighbours = [_chunk(0, 0, 100, ""), matched, _chunk(2, 200, 300, "")]
    assert _section_bounds(matched, neighbours) == (0, 300)


def test_widening_grows_both_ways_within_the_budget():
    matched = _chunk(1, 100, 200)
    assert _widen(matched, 0, 400, budget=200) == (50, 250)


def test_widening_gives_the_far_side_what_the_near_one_cannot_use():
    """A passage at the start of a section still gets its whole budget."""
    matched = _chunk(0, 0, 100)
    assert _widen(matched, 0, 400, budget=200) == (0, 200)


def test_widening_never_leaves_the_section():
    matched = _chunk(1, 100, 200)
    assert _widen(matched, 90, 210, budget=1000) == (90, 210)


def test_a_budget_no_larger_than_the_chunk_widens_nothing():
    matched = _chunk(1, 100, 200)
    assert _widen(matched, 0, 400, budget=100) == (100, 200)


def test_avoiding_covered_text_pulls_the_window_back():
    assert _avoid((50, 250), (100, 200), [(0, 80)]) == (80, 250)
    assert _avoid((50, 250), (100, 200), [(220, 400)]) == (50, 220)


def test_avoiding_gives_up_when_the_chunk_itself_was_already_returned():
    """There is nothing to pull back to: the overlap is the result itself."""
    assert _avoid((50, 250), (100, 200), [(150, 300)]) is None


def test_avoiding_leaves_a_window_that_touches_nothing():
    assert _avoid((50, 250), (100, 200), [(300, 400)]) == (50, 250)


# --- through the shipped search -------------------------------------------


def test_a_result_carries_more_than_the_matched_chunk(sectioned):
    context, casefile = sectioned
    hits = context.search.search(casefile.short_id, "dredging survey sentence", limit=3)
    widened = [h for h in hits if h.is_widened]
    assert widened, "nothing widened, so this test says nothing"

    hit = widened[0]
    assert hit.chunk.text.strip() in hit.text
    assert len(hit.text) > len(hit.chunk.text)


def test_the_window_is_a_slice_of_the_document(sectioned):
    """Never assembled from chunk texts: chunks overlap, so joining repeats."""
    context, casefile = sectioned
    hits = context.search.search(casefile.short_id, "dredging survey sentence", limit=3)
    for hit in hits:
        source = hit.document.extracted_text[hit.char_start : hit.char_end]
        assert hit.text == source


def test_the_window_does_not_cross_into_the_next_section(context, sectioned_corpus):
    """One hit, so its neighbours are not results and the window has room.

    Asked with a wider limit this examined nothing: every passage of the document
    was itself a result, so none could widen, and the loop skipped them all while
    the test reported success.
    """
    casefile = context.casefiles.create("Boundary")
    assert not context.ingestion.ingest(casefile.short_id, sectioned_corpus).failed

    hits = context.search.search(casefile.short_id, "cormorant", limit=1)
    assert hits and hits[0].document.filename == "sections.md"
    hit = hits[0]
    assert hit.is_widened, "nothing widened, so this test says nothing"
    assert "Beta" in hit.chunk.heading_path
    assert "Alpha sentence" not in hit.text


def test_the_matched_chunk_keeps_its_own_span(sectioned):
    """Widening what is read must not widen what is quoted."""
    context, casefile = sectioned
    hit = context.search.search(casefile.short_id, "dredging survey", limit=1)[0]
    quoted = hit.document.extracted_text[hit.chunk.char_start : hit.chunk.char_end]
    assert quoted.strip() == hit.chunk.text
    assert hit.char_start <= hit.chunk.char_start
    assert hit.char_end >= hit.chunk.char_end


def test_a_document_with_no_headings_still_widens(sectioned):
    """There the character budget is the only bound, and it must still apply."""
    context, casefile = sectioned
    hits = context.search.search(casefile.short_id, "cormorant", limit=1)
    assert hits and hits[0].document.filename == "watch.txt"
    hit = hits[0]
    assert hit.chunk.heading_path == ""
    assert hit.is_widened
    assert hit.text == hit.document.extracted_text[hit.char_start : hit.char_end]


def test_no_text_is_returned_twice_in_one_response(sectioned):
    context, casefile = sectioned
    hits = context.search.search(casefile.short_id, "sentence about the", limit=10)
    spans: dict[str, list[tuple[int, int]]] = {}
    for hit in hits:
        for start, end in spans.setdefault(hit.document.id, []):
            overlap = min(end, hit.char_end) - max(start, hit.char_start)
            # Adjacent chunks overlap by configuration, so a passage may share
            # its edges with its neighbour. What must not happen is a widened
            # window carrying a stretch of text another result already carried.
            assert overlap <= context.config.contract.chunk_overlap_chars
        spans[hit.document.id].append((hit.char_start, hit.char_end))


def test_a_response_that_hits_its_bound_narrows_and_says_so(sectioned, monkeypatch):
    """The bound is not silent: a caller must be able to tell it was applied."""
    import jackryan.services.search as search_module

    context, casefile = sectioned
    generous = context.search.search(casefile.short_id, "sentence about the", limit=10)

    monkeypatch.setattr(search_module, "MAX_RESPONSE_CHARS", 1200)
    hits = context.search.search(casefile.short_id, "sentence about the", limit=10)

    narrowed = [h for h in hits if h.narrowed]
    assert narrowed, "the bound was never reached, so this test says nothing"
    assert all(h.text == h.chunk.text for h in narrowed)
    assert not any(h.is_widened for h in narrowed)
    # Nothing is dropped to meet the bound: an analyst cannot miss what they were
    # never shown, so it governs the context added, not the passages found.
    assert [h.chunk.id for h in hits] == [h.chunk.id for h in generous]
    assert sum(len(h.text) for h in hits) < sum(len(h.text) for h in generous)


def test_widening_never_takes_a_response_past_its_bound(sectioned):
    """The bound applies to the context added, not to the passages found."""
    context, casefile = sectioned
    hits = context.search.search(casefile.short_id, "sentence", limit=100)
    added = sum(len(h.text) - len(h.chunk.text) for h in hits)
    assert added >= 0
    assert sum(len(h.text) for h in hits) <= MAX_RESPONSE_CHARS


def test_widening_is_switched_off_by_a_budget_at_the_chunk_size(context, tmp_path):
    """An operator who does not want windows sets the budget to a chunk."""
    from jackryan.services.search import SearchService

    folder = tmp_path / "narrow"
    folder.mkdir()
    (folder / "report.md").write_text(f"# Survey\n\n{ALPHA}\n", encoding="utf-8")
    casefile = context.casefiles.create("No Windows")
    context.ingestion.ingest(casefile.short_id, folder)

    narrow = SearchService(
        context.store, context.casefiles, context.embedder, window_max_chars=1
    )
    hits = narrow.search(casefile.short_id, "dredging survey", limit=5)
    assert hits
    assert not any(h.is_widened for h in hits)
    assert all(h.text == h.chunk.text for h in hits)


def test_a_window_never_runs_past_a_heading_it_would_cross(context, sectioned_corpus):
    """A passage that straddles a heading carries the trail of where it began.

    A window built from recorded heading trails alone therefore reaches into the
    next section: the straddling passage belongs to the first section by its
    trail, and its own text already runs past the boundary. The heading line in
    the document is what stops it.
    """
    casefile = context.casefiles.create("Straddle")
    report = context.ingestion.ingest(casefile.short_id, sectioned_corpus)
    assert not report.failed

    hits = context.search.search(casefile.short_id, "kingfisher", limit=1)
    assert hits and hits[0].document.filename == "straddle.md"
    hit = hits[0]
    assert hit.is_widened, "nothing widened, so this test says nothing"

    beyond = hit.text[hit.chunk.char_end - hit.char_start :]
    assert beyond, "the window did not extend past the passage, so nothing is tested"
    assert not any(line.startswith("#") for line in beyond.splitlines()), beyond
    assert "pelican" not in hit.text


def test_a_result_clipped_by_another_result_says_it_was_narrowed(context, sectioned_corpus):
    """A result cut back to leave room for a neighbour must not look like one
    that had no more context to give — that is the confusion the flag exists to
    prevent, and it applies to the top-ranked result as much as to any other."""
    casefile = context.casefiles.create("Clipped")
    assert not context.ingestion.ingest(casefile.short_id, sectioned_corpus).failed

    hits = context.search.search(casefile.short_id, "Alpha sentence concerns", limit=10)
    same_document = [h for h in hits if h.document.filename == "sections.md"]
    assert len(same_document) > 1, "need two results in one document to contest a window"

    for hit in same_document:
        alone, _ = context.search._window_for(
            hit.chunk, hit.document, context.search._window_max_chars
        )
        if alone is not None and not hit.is_widened:
            assert hit.narrowed, (
                "a result whose window was given up for a neighbour reported "
                "narrowed=False"
            )


def test_a_stale_offset_is_not_widened(context, sectioned_corpus):
    """Ingestion writes a document and its chunks in two transactions, so a run
    that fails between them leaves new text against old offsets. Widening on
    those would return a passage from elsewhere in the document as evidence,
    under provenance naming a span it never occupied."""
    from dataclasses import replace as replace_fields

    casefile = context.casefiles.create("Stale")
    assert not context.ingestion.ingest(casefile.short_id, sectioned_corpus).failed
    hit = context.search.search(casefile.short_id, "cormorant", limit=1)[0]
    assert hit.is_widened, "this passage must widen normally, or nothing is tested"

    # The document's text moves on; the chunk's offsets do not. Same length, so
    # the span is still in range — the offsets simply describe other words now.
    text = hit.document.extracted_text
    shifted = replace_fields(hit.document, extracted_text="x" * len(text))

    window, _ = context.search._window_for(
        hit.chunk, shifted, context.search._window_max_chars
    )
    assert window is None, "widened a span the stored passage no longer occupies"
