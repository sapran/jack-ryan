"""Hybrid search: two retrievers, fused by rank, scoped to one casefile."""

from __future__ import annotations

import pytest

from jackryan.errors import ValidationError
from jackryan.mentions import MENTION_KINDS
from jackryan.services.search import RRF_K, _parsed_mention


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


# --- mention filter --------------------------------------------------------
#
# Both retrievers are asked for a bounded depth of candidates.  The mention
# predicate MUST be applied inside that query: removing non-matching candidates
# from its output would discard every match that ranked below the depth
# unfiltered, and the caller would be told the casefile contains nothing while
# the store held exactly what they asked for.


IBAN_GOOD = "GB82 WEST 1234 5698 7654 32"
IBAN_NORMALISED = "GB82WEST12345698765432"
PHONE_RAW = "+38 (044) 123-45.67"
PHONE_NORMALISED = "+380441234567"


@pytest.fixture
def depth_loaded(context, tmp_path):
    """Twenty documents saturated with the query term, plus one carrying an IBAN.

    With ``limit=2`` the candidate depth is 10.  The carrier ranks 21st in
    both legs and never appears in the unfiltered result at that depth — which
    is the precondition the depth test asserts rather than assumes.
    """
    folder = tmp_path / "depth"
    folder.mkdir()
    for n in range(1, 21):
        (folder / f"ledger-{n:02d}.md").write_text(
            f"# Ledger {n:02d}\n\n"
            "Payment payment payment. A payment ledger of payment entries; "
            "each payment follows a payment.\n",
            encoding="utf-8",
        )
    (folder / "buried.md").write_text(
        "# Cormorant Watch\n\n"
        "Kingfisher pontoon mooring buoy dredger crane windlass bollard trawler "
        "gantry quayside jetty slipway capstan hawser fender chandlery pennant "
        "spinnaker gunwale keelson taffrail bulwark scupper transom coaming.\n\n"
        f"One payment was settled against account {IBAN_GOOD}.\n",
        encoding="utf-8",
    )
    casefile = context.casefiles.create("Depth Probe")
    context.ingestion.ingest(casefile.short_id, folder)
    return context, casefile


@pytest.fixture
def mention_loaded(context, tmp_path):
    """Eight documents at varying query densities, alternating phone carrier.

    Even-numbered files carry the phone identifier; odd ones do not.
    """
    folder = tmp_path / "mentions"
    folder.mkdir()
    for n in range(1, 9):
        carries = n % 2 == 0
        tail = f" Reached on {PHONE_RAW}." if carries else ""
        (folder / f"file-{n:02d}.md").write_text(
            f"# Invoice {n:02d}\n\n"
            + "Payment " * n
            + f"about the dredging survey {n}.{tail}\n",
            encoding="utf-8",
        )
    casefile = context.casefiles.create("Mention Probe")
    context.ingestion.ingest(casefile.short_id, folder)
    return context, casefile


def test_a_filtered_search_returns_a_passage_that_ranks_below_the_unfiltered_depth(
    depth_loaded,
):
    """The single most important test of this change.

    If the mention predicate were applied to the retrievers' output rather than
    inside their queries, a passage carrying the target identifier but ranking
    below the candidate depth for the query would never be returned.  The caller
    would be told the casefile does not mention that identifier, which is false.

    The oracle is trustworthy because the precondition is asserted, not assumed:
    an unfiltered search at the same limit genuinely does not return the target.
    If the precondition fails, the fixture is not exercising the case, and the
    test proves nothing regardless of what the filtered search returns.
    """
    context, casefile = depth_loaded
    limit = 2  # depth = limit * 5 = 10; the carrier ranks 21st

    unfiltered = context.search.search(casefile.short_id, "payment", limit=limit)
    target_filenames = {h.document.filename for h in unfiltered}
    assert "buried.md" not in target_filenames, (
        "precondition violated: 'buried.md' appeared in the unfiltered top-2, "
        "so the fixture is not exercising the below-depth case and the test "
        "would pass regardless of where the predicate is applied"
    )

    filtered = context.search.search(
        casefile.short_id, "payment", limit=limit, mention=IBAN_NORMALISED
    )
    assert any(h.document.filename == "buried.md" for h in filtered), (
        "a passage carrying the filtered identifier was not returned even "
        "though the store holds it — the predicate is being applied to the "
        "retrievers' output rather than inside their queries"
    )


def test_a_mention_filter_changes_candidacy_and_not_ranking(mention_loaded):
    """The filter decides which passages are candidates; it must not influence
    how those candidates rank.

    Each hit's score must equal the RRF sum of its reported keyword and vector
    ranks — no extra rank leg, no score bonus.  Absolute scores between the
    filtered and unfiltered runs differ because the filter changes each
    retriever's ranking positions, and RRF scores are computed from those
    positions.  So absolute equality is not the right oracle.  At each retriever
    level, the filtered ids are a subsequence of the unfiltered ids — the SQL
    ordering is unchanged and the predicate only removes rows — and in the fused
    result the common passages preserve their relative order.
    """
    context, casefile = mention_loaded

    unfiltered = context.search.search(casefile.short_id, "payment", limit=10)
    filtered = context.search.search(
        casefile.short_id, "payment", limit=10, mention=PHONE_NORMALISED
    )

    # Guard: the unfiltered result must include at least one passage that does
    # not carry the identifier, otherwise the test is vacuous.
    unfiltered_files = [h.document.filename for h in unfiltered]
    filtered_files = [h.document.filename for h in filtered]
    assert set(filtered_files) < set(unfiltered_files), (
        "every unfiltered passage carries the identifier, so the filter cannot "
        "demonstrably change candidacy"
    )

    # Every score equals the RRF formula applied to the reported ranks — no
    # bonus term from the mention filter.
    for h in filtered:
        expected = 0.0
        if h.keyword_rank is not None:
            expected += 1.0 / (RRF_K + h.keyword_rank)
        if h.vector_rank is not None:
            expected += 1.0 / (RRF_K + h.vector_rank)
        assert h.score == pytest.approx(expected, abs=1e-12), (
            f"score {h.score} for {h.document.filename} does not equal the RRF "
            f"sum of its ranks (keyword={h.keyword_rank}, vector={h.vector_rank}); "
            f"the filter may be contributing a score bonus"
        )

    # The common passages appear in the same relative order.
    common_from_unfiltered = [f for f in unfiltered_files if f in set(filtered_files)]
    common_from_filtered = [f for f in filtered_files if f in set(unfiltered_files)]
    assert common_from_filtered == common_from_unfiltered, (
        f"the relative order of passages common to both results changed: "
        f"unfiltered {common_from_unfiltered}, filtered {common_from_filtered}"
    )


def test_both_retrievers_honour_the_mention_filter_independently(mention_loaded):
    """Each retriever must apply the filter in its own query.

    Testing only through SearchService would let one leg ignore the filter
    entirely while fusion hid it — the other leg's results would still all carry
    the identifier.  Calling each leg directly proves both apply it.

    The oracle is the store's own ids: every returned chunk id must belong to a
    passage whose text contains the identifier as originally written.
    """
    context, casefile = mention_loaded
    store = context.store

    depth = 100
    kw_ids = store.search_keyword(
        casefile.id, "payment", depth, "", PHONE_NORMALISED
    )
    vec_ids = store.search_vector(
        casefile.id,
        context.embedder.embed_query("payment"),
        depth,
        "",
        PHONE_NORMALISED,
    )
    assert kw_ids, "keyword search returned nothing for a known identifier"
    assert vec_ids, "vector search returned nothing for a known identifier"

    chunks = store.get_chunks(list(set(kw_ids + vec_ids)))
    for label, ids in [("keyword", kw_ids), ("vector", vec_ids)]:
        for cid in ids:
            chunk = chunks[cid]
            assert PHONE_RAW in chunk.text, (
                f"{label} retriever returned chunk {cid[:8]} whose text does "
                f"not contain the phone number; the filter is not applied "
                f"inside this retriever's query"
            )

    # At each retriever level, filtered ids are a subsequence of unfiltered ids.
    kw_all = store.search_keyword(casefile.id, "payment", depth)
    vec_all = store.search_vector(
        casefile.id, context.embedder.embed_query("payment"), depth
    )
    kw_positions = [kw_all.index(i) for i in kw_ids]
    vec_positions = [vec_all.index(i) for i in vec_ids]
    assert kw_positions == sorted(kw_positions), (
        "filtered keyword ids are not a subsequence of the unfiltered ranking"
    )
    assert vec_positions == sorted(vec_positions), (
        "filtered vector ids are not a subsequence of the unfiltered ranking"
    )


def test_a_bare_mention_value_matches_any_kind(mention_loaded):
    """A value with no kind prefix matches the identifier under any kind.

    The requirement says a bare value matches any kind, so an analyst who
    pastes an identifier without knowing its category still gets results.
    """
    context, casefile = mention_loaded
    hits = context.search.search(
        casefile.short_id, "payment", limit=10, mention=PHONE_NORMALISED
    )
    assert hits, (
        "a bare value search returned nothing for a known phone identifier"
    )


def test_a_kinded_mention_filter_matches_only_that_kind(mention_loaded):
    """An explicit ``phone:<value>`` matches only phone mentions.

    If the same value existed under a different kind, this would exclude it.
    The fixture has the phone under kind ``phone`` only, so this confirms the
    kind parameter is threaded through.
    """
    context, casefile = mention_loaded
    hits = context.search.search(
        casefile.short_id, "payment", limit=10,
        mention=f"phone:{PHONE_NORMALISED}",
    )
    assert hits, (
        "phone:<value> returned nothing for a known phone identifier"
    )


def test_a_valid_kind_with_a_value_from_another_kind_returns_nothing(mention_loaded):
    """Filtering by ``email:<phone_value>`` returns nothing, not an error.

    The kind is valid so there is no validation failure; the value simply does
    not appear under that kind.  This is distinct from an unknown kind, which
    is a ``ValidationError``.
    """
    context, casefile = mention_loaded
    hits = context.search.search(
        casefile.short_id, "payment", limit=10,
        mention=f"email:{PHONE_NORMALISED}",
    )
    assert hits == [], (
        "expected no results when filtering by a valid kind that does not "
        "carry the given value"
    )


def test_an_unknown_mention_kind_on_search_is_a_validation_error(mention_loaded):
    """An unknown kind must be refused, naming the kinds that exist.

    An empty result would tell the analyst the casefile contains no such
    identifier, which is a different claim and a false one — there is no such
    *kind* of identifier, and the analyst needs to be told so they can correct
    the query rather than draw a conclusion from its silence.
    """
    context, casefile = mention_loaded
    with pytest.raises(ValidationError, match="passport") as exc_info:
        context.search.search(
            casefile.short_id, "payment", limit=10, mention="passport:12345"
        )
    message = str(exc_info.value)
    for kind in MENTION_KINDS:
        assert kind in message, (
            f"the error message does not name the valid kind {kind!r}; the "
            f"analyst cannot know what to correct"
        )


def test_an_empty_mention_filter_returns_the_unfiltered_result(mention_loaded):
    """An empty or whitespace-only ``mention`` argument is no filter.

    This is the default: every call that does not pass ``mention`` exercises
    this path, but an explicit assertion prevents a regression that would
    refuse an empty string instead of treating it as absent.
    """
    context, casefile = mention_loaded
    baseline = context.search.search(casefile.short_id, "payment", limit=10)
    for empty in ("", "   "):
        hits = context.search.search(
            casefile.short_id, "payment", limit=10, mention=empty
        )
        assert [h.document.filename for h in hits] == [
            h.document.filename for h in baseline
        ], f"mention={empty!r} should be the same as no filter"


def test_a_kind_with_no_value_is_refused():
    """``email:`` with nothing after the colon is refused.

    The caller plainly meant to filter by kind and gave no value; treating
    ``email:`` as a literal value search is not what they intended.
    """
    with pytest.raises(ValidationError, match="needs a value"):
        _parsed_mention("email:")


def test_a_colon_bearing_value_with_an_unrecognised_prefix_is_refused():
    """A value like ``a:b@example.com`` is refused rather than searched.

    The code splits on the first colon. If the left side is non-empty and is not
    a recognised kind, it is treated as an attempted kind name and refused.
    This means identifiers whose literal text contains a colon with a
    non-kind prefix cannot be searched.  The design argues this is better than
    a silent empty result: ``passport:12345`` as a value search matches nothing
    and would read as an answer.

    NOTE: this contradicts the ``_parsed_mention`` docstring's claim that a
    value may contain a colon ("an identifier may contain one — a value is not
    guaranteed to be colon-free and the kind is").  In practice, if the text
    before the colon is not a known kind, the code raises rather than treating
    the whole string as a bare value.  This is reported as a production defect
    (docstring/behaviour mismatch) without fixing the code.
    """
    with pytest.raises(ValidationError, match="'a'"):
        _parsed_mention("a:b@example.com")


def test_a_mention_filter_is_scoped_to_its_casefile(context, tmp_path):
    """The same identifier in two casefiles; each sees only its own.

    Without casefile scoping on the mention subquery, a pivot on an identifier
    would pull in chunks from every casefile that contains it, crossing the
    compartment boundary the whole store enforces.
    """
    email = "billing@acme.example"

    folder_a = tmp_path / "scope-a"
    folder_a.mkdir()
    (folder_a / "mine.md").write_text(
        f"# Mine\n\nPayment queries go to {email}.\n", encoding="utf-8"
    )
    mine = context.casefiles.create("Scope Mine")
    context.ingestion.ingest(mine.short_id, folder_a)

    folder_b = tmp_path / "scope-b"
    folder_b.mkdir()
    (folder_b / "theirs.md").write_text(
        f"# Theirs\n\nPayment queries go to {email} as well.\n", encoding="utf-8"
    )
    theirs = context.casefiles.create("Scope Theirs")
    context.ingestion.ingest(theirs.short_id, folder_b)

    mine_hits = context.search.search(mine.short_id, "payment", limit=5, mention=email)
    theirs_hits = context.search.search(
        theirs.short_id, "payment", limit=5, mention=email
    )

    assert [h.document.filename for h in mine_hits] == ["mine.md"], (
        "filtered search in casefile 'mine' returned the wrong documents"
    )
    assert [h.document.filename for h in theirs_hits] == ["theirs.md"], (
        "filtered search in casefile 'theirs' returned the wrong documents"
    )
