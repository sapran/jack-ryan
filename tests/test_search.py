"""Hybrid search: two retrievers, fused by rank, scoped to one casefile."""

from __future__ import annotations

import pytest

from jackryan.errors import ValidationError


@pytest.fixture
def loaded(context, corpus):
    casefile = context.casefiles.create("Harbour Inquiry")
    context.ingestion.ingest(casefile.short_id, corpus)
    return context, casefile


def test_the_relevant_document_ranks_first(loaded):
    context, casefile = loaded
    hits = context.search.search(casefile.short_id, "harbour lease Northgate", limit=5)
    assert hits
    assert hits[0].document.filename == "lease.md"


def test_both_retrievers_contribute(loaded):
    context, casefile = loaded
    hits = context.search.search(casefile.short_id, "harbour lease Northgate", limit=5)
    top = hits[0]
    # The obvious match is found by keyword and by vector alike.
    assert top.keyword_rank is not None
    assert top.vector_rank is not None


def test_agreement_between_retrievers_outranks_a_single_one(loaded):
    context, casefile = loaded
    hits = context.search.search(casefile.short_id, "dredging contracts tariff", limit=5)
    both = [h for h in hits if h.keyword_rank and h.vector_rank]
    single = [h for h in hits if bool(h.keyword_rank) != bool(h.vector_rank)]
    if both and single:
        assert min(h.score for h in both) > max(h.score for h in single)


def test_a_result_resolves_to_its_source(loaded):
    context, casefile = loaded
    hit = context.search.search(casefile.short_id, "harbour lease", limit=1)[0]
    document = context.ingestion.resolve_document(casefile.short_id, hit.document.id)
    excerpt = document.extracted_text[hit.chunk.char_start : hit.chunk.char_end]
    assert excerpt.strip() == hit.chunk.text
    assert hit.chunk.id and hit.document.id


def test_search_is_scoped_to_one_casefile(context, corpus):
    mine = context.casefiles.create("Mine")
    theirs = context.casefiles.create("Theirs")
    context.ingestion.ingest(mine.short_id, corpus)

    assert context.search.search(mine.short_id, "harbour lease", limit=5)
    assert context.search.search(theirs.short_id, "harbour lease", limit=5) == []


def test_results_are_bounded(loaded):
    context, casefile = loaded
    assert len(context.search.search(casefile.short_id, "the", limit=2)) <= 2


def test_an_over_large_limit_is_clamped_not_rejected(loaded):
    context, casefile = loaded
    # An agent surface has no validation layer of its own, so this must not raise.
    hits = context.search.search(casefile.short_id, "harbour", limit=10_000)
    assert len(hits) <= 100


def test_an_empty_query_is_refused(loaded):
    context, casefile = loaded
    with pytest.raises(ValidationError, match="query is required"):
        context.search.search(casefile.short_id, "   ")


def test_query_text_is_matched_as_words_not_operators(loaded):
    context, casefile = loaded
    # FTS5 syntax in user text must not blow up or be executed as a query.
    for hostile in ['harbour OR "', "lease AND (", "NEAR/2 tariff", "*", '"'] :
        context.search.search(casefile.short_id, hostile, limit=3)


def test_search_finds_nothing_in_an_empty_casefile(context):
    empty = context.casefiles.create("Nothing Here")
    assert context.search.search(empty.short_id, "anything") == []
