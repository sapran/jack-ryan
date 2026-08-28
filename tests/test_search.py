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


# --- how a tie is broken ---------------------------------------------------
#
# Reciprocal rank fusion ties routinely: a chunk ranked first by keyword and
# second by vector scores exactly what one ranked second and first scores. What
# breaks that tie decides whether the same corpus ranks the same way twice, so
# these tests fabricate the tie rather than hoping a corpus produces one.


def _tied_store(
    context,
    monkeypatch,
    ids: tuple[str, str],
    document_ids: tuple[str, str] = ("doc-a", "doc-b"),
):
    """Two chunks, in two documents, fused to exactly the same score.

    Both the chunk ids and the document ids are supplied by the caller, so a
    test can put either in the opposite order to the passages themselves. That
    is the whole point: an ordering that falls back to an identifier is then
    visibly wrong, rather than right half the time by luck.

    Neither identifier is a property of the corpus. Chunk ids are minted afresh
    on every reingest, and two stores built from the same documents give those
    documents different ids.
    """
    from datetime import datetime, timezone

    from jackryan.storage.port import Chunk, Document

    now = datetime.now(timezone.utc)
    first_doc, second_doc = document_ids
    chunks = {
        ids[0]: Chunk(
            id=ids[0], document_id=first_doc, casefile_id="cf", ordinal=0,
            heading_path="", text="first", char_start=0, char_end=5,
        ),
        ids[1]: Chunk(
            id=ids[1], document_id=second_doc, casefile_id="cf", ordinal=0,
            heading_path="", text="second", char_start=0, char_end=6,
        ),
    }
    documents = {
        first_doc: Document(
            id=first_doc, casefile_id="cf", content_hash="a", filename="a.md",
            media_type="text/markdown", byte_size=5, extracted_text="first",
            extractor="text", created_at=now, updated_at=now,
        ),
        second_doc: Document(
            id=second_doc, casefile_id="cf", content_hash="b", filename="b.md",
            media_type="text/markdown", byte_size=6, extracted_text="second",
            extractor="text", created_at=now, updated_at=now,
        ),
    }
    # Ranked first and second by one retriever, second and first by the other.
    monkeypatch.setattr(context.store, "search_keyword", lambda *a, **k: [ids[0], ids[1]])
    monkeypatch.setattr(context.store, "search_vector", lambda *a, **k: [ids[1], ids[0]])
    monkeypatch.setattr(context.store, "get_chunks", lambda wanted: dict(chunks))
    monkeypatch.setattr(context.store, "get_document", lambda doc_id: documents.get(doc_id))


def test_a_tied_score_is_broken_by_the_corpus_not_by_an_identifier(loaded, monkeypatch):
    """Ties must not be broken by the chunk id.

    Ids are minted afresh on every reingest, so an ordering that falls back to
    them ranks a rebuilt corpus differently from the one it replaced, and no
    measurement of retrieval quality could be reproduced. The ids here are
    deliberately in the opposite order to the passages.
    """
    context, casefile = loaded
    _tied_store(context, monkeypatch, ("zzzz0001", "aaaa0002"))

    hits = context.search.search(casefile.short_id, "anything", limit=10)

    assert len(hits) == 2
    assert hits[0].score == hits[1].score, "these two must genuinely tie"
    assert [h.document.filename for h in hits] == ["a.md", "b.md"]


def test_the_fused_order_does_not_change_when_the_identifiers_do(loaded, monkeypatch):
    """The same corpus ranks the same way in a store built afresh.

    A reingest mints new chunk ids; a second store built from the same documents
    also gives those documents new ids. Ordering by either would rank a corpus
    that has not changed differently from one that has — which is what made the
    first measurement of this project unreproducible between two runs.
    """
    context, casefile = loaded

    _tied_store(context, monkeypatch, ("zzzz0001", "aaaa0002"), ("doc-a", "doc-b"))
    before = [
        h.document.filename
        for h in context.search.search(casefile.short_id, "anything", limit=10)
    ]
    monkeypatch.undo()

    # The same two passages in a store built from scratch: every identifier is
    # different, and both orders now disagree with the passages themselves.
    _tied_store(context, monkeypatch, ("aaaa0003", "zzzz0004"), ("doc-z", "doc-y"))
    after = [
        h.document.filename
        for h in context.search.search(casefile.short_id, "anything", limit=10)
    ]

    assert before == after == ["a.md", "b.md"]
