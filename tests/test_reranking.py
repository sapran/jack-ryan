"""Reranking: a stage after fusion that improves an answer or stands aside.

Two failures are held apart here, deliberately. A reranker the instance cannot
build is a misconfiguration and stops the search; a reranker that fails while
scoring one response leaves the fused order in place and says so. Collapsing
them either way loses something: a fatal transient fault makes retrieval quality
a condition of retrieval, and a silent misconfiguration serves worse results
than the operator asked for with nothing to show it.
"""

from __future__ import annotations

import pytest

from jackryan.config import load_config
from jackryan.errors import ConfigError
from jackryan.reranking import build_reranker
from jackryan.reranking.port import RerankError
from jackryan.services.search import (
    RANKED_BY_FUSION,
    RANKED_BY_RERANK,
    RANKED_BY_RERANK_UNAVAILABLE,
    SearchService,
)


class StubReranker:
    """Records what it was asked, and scores by a rule the test chooses."""

    def __init__(self, rule=None, fail_score=False, fail_check=False):
        self.name = "stub-reranker"
        self.calls: list[tuple[str, list[str]]] = []
        self.checked = 0
        self._rule = rule or (lambda index, passage: 0.0)
        self._fail_score = fail_score
        self._fail_check = fail_check

    def check(self) -> None:
        self.checked += 1
        if self._fail_check:
            raise ConfigError("stub reranker cannot be built")

    def score(self, query: str, passages):
        self.calls.append((query, list(passages)))
        if self._fail_score:
            raise RerankError("stub reranker fell over")
        return [self._rule(index, passage) for index, passage in enumerate(passages)]


@pytest.fixture
def reranked(context, sectioned_corpus):
    """One store, one casefile, and a search service per reranker under test.

    Several services over the same store rather than several stores: chunk ids
    are minted per ingest, so two corpora built from the same folder cannot be
    compared passage by passage, and comparing orderings is the whole point here.
    """
    casefile = context.casefiles.create("Rerank")
    context.ingestion.ingest(casefile.short_id, sectioned_corpus)

    def make(reranker=None, **kwargs):
        service = SearchService(
            context.store,
            context.casefiles,
            context.embedder,
            reranker=reranker,
            **kwargs,
        )
        return service, casefile

    return make


# --- off by default --------------------------------------------------------


def test_an_instance_with_no_reranker_searches_as_before(reranked):
    search, casefile = reranked(None)
    hits = search.search(casefile.short_id, "dredging survey", limit=5)
    assert hits
    assert all(hit.ranking == RANKED_BY_FUSION for hit in hits)
    assert all(hit.rerank_score is None for hit in hits)


def test_no_reranker_is_built_when_none_is_named(config):
    assert build_reranker(config) is None


def test_a_named_reranker_is_built(tmp_path, monkeypatch):
    path = tmp_path / "config.yaml"
    path.write_text(
        "profiles:\n  local:\n    reranker_model: Xenova/ms-marco-MiniLM-L-6-v2\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("JACKRYAN_CONFIG", str(path))
    monkeypatch.delenv("JACKRYAN_PROFILE", raising=False)
    reranker = build_reranker(load_config())
    # Constructed, not loaded: no weights are fetched until a search needs them.
    assert reranker is not None
    assert reranker.name == "Xenova/ms-marco-MiniLM-L-6-v2"


# --- reordering ------------------------------------------------------------


def test_reranking_reorders_the_fused_candidates(reranked):
    """The reranker decides the order; fusion decides what it may choose from."""
    plain_search, casefile = reranked(None)
    fused = [h.chunk.id for h in plain_search.search(casefile.short_id, "sentence", limit=5)]
    assert len(fused) > 1

    # Scored so that the fused order is preserved, then so that it is reversed.
    keeping, _ = reranked(StubReranker(rule=lambda index, passage: float(-index)))
    kept = [h.chunk.id for h in keeping.search(casefile.short_id, "sentence", limit=5)]

    reversing, _ = reranked(StubReranker(rule=lambda index, passage: float(index)))
    flipped = [h.chunk.id for h in reversing.search(casefile.short_id, "sentence", limit=5)]

    assert kept == fused, "scores following the fused order must leave it alone"
    assert flipped != fused
    # Not the same set: the reranker sees a deeper pool than the caller's limit,
    # so reversing its scores surfaces passages fusion had below the cut.
    assert set(flipped) - set(fused)


def test_every_returned_passage_came_from_a_retriever(reranked):
    """Reranking reorders what fusion produced; it introduces nothing."""
    stub = StubReranker(rule=lambda index, passage: float(index))
    search, casefile = reranked(stub)
    hits = search.search(casefile.short_id, "dredging survey", limit=5)
    assert hits
    for hit in hits:
        assert hit.keyword_rank is not None or hit.vector_rank is not None


def test_the_reranker_sees_more_candidates_than_the_caller_asked_for(reranked):
    stub = StubReranker()
    search, casefile = reranked(stub, rerank_depth=50)
    search.search(casefile.short_id, "the", limit=1)
    assert stub.calls
    _, passages = stub.calls[0]
    assert len(passages) > 1


def test_the_reranker_is_given_the_passage_not_a_window(reranked):
    """The library truncates the pair silently, so a window would be cut inside
    it and the score would describe a fragment nobody chose."""
    stub = StubReranker()
    search, casefile = reranked(stub, window_max_chars=100_000)
    hits = search.search(casefile.short_id, "cormorant", limit=1)
    assert stub.calls
    _, passages = stub.calls[0]
    assert hits[0].is_widened, "nothing widened, so this test says nothing"
    for hit in hits:
        assert hit.chunk.text in passages
        assert hit.text not in passages


def test_the_fusion_score_survives_reranking(reranked):
    plain, casefile = reranked(None)
    # Deep enough to cover whatever the reranker promotes: it chooses from a
    # larger pool than the caller's limit.
    before = {
        h.chunk.id: h.score for h in plain.search(casefile.short_id, "sentence", limit=50)
    }

    search, _ = reranked(StubReranker(rule=lambda index, passage: float(index)))
    after = search.search(casefile.short_id, "sentence", limit=5)

    assert all(hit.ranking == RANKED_BY_RERANK for hit in after)
    for hit in after:
        assert hit.rerank_score is not None
        assert hit.score == pytest.approx(before[hit.chunk.id])


# --- the two failures ------------------------------------------------------


def test_a_reranker_that_cannot_be_built_stops_the_search(reranked):
    """A misconfiguration is loud. An instance quietly serving the fused order
    would have hidden it."""
    search, casefile = reranked(StubReranker(fail_check=True))
    with pytest.raises(ConfigError):
        search.search(casefile.short_id, "sentence", limit=5)


def test_a_reranker_that_fails_while_scoring_degrades_to_the_fused_order(reranked):
    plain, casefile = reranked(None)
    fused = [h.chunk.id for h in plain.search(casefile.short_id, "sentence", limit=5)]

    search, _ = reranked(StubReranker(fail_score=True))
    hits = search.search(casefile.short_id, "sentence", limit=5)

    assert [h.chunk.id for h in hits] == fused
    assert all(hit.ranking == RANKED_BY_RERANK_UNAVAILABLE for hit in hits)
    assert all(hit.rerank_score is None for hit in hits)


def test_a_degraded_response_is_distinguishable_from_an_unconfigured_one(reranked):
    """Same ordering, but one of them is a promise that was not kept."""
    plain, casefile = reranked(None)
    off = plain.search(casefile.short_id, "sentence", limit=5)

    search, _ = reranked(StubReranker(fail_score=True))
    degraded = search.search(casefile.short_id, "sentence", limit=5)

    assert off[0].ranking != degraded[0].ranking


# --- configuration ---------------------------------------------------------


def write_config(tmp_path, body: str) -> str:
    path = tmp_path / "config.yaml"
    path.write_text(body, encoding="utf-8")
    return str(path)


def test_an_empty_reranker_model_means_off(tmp_path, monkeypatch):
    path = write_config(tmp_path, 'profiles:\n  local:\n    reranker_model: ""\n')
    monkeypatch.setenv("JACKRYAN_CONFIG", path)
    monkeypatch.delenv("JACKRYAN_PROFILE", raising=False)
    assert load_config().profile.reranker_model == ""


def test_a_mistyped_rerank_key_is_fatal(tmp_path, monkeypatch):
    """A profile setting quietly ignored costs more than a rejected one."""
    path = write_config(tmp_path, "profiles:\n  local:\n    rerank_model: something\n")
    monkeypatch.setenv("JACKRYAN_CONFIG", path)
    monkeypatch.delenv("JACKRYAN_PROFILE", raising=False)
    with pytest.raises(ConfigError) as exc:
        load_config()
    assert "rerank_model" in str(exc.value)


@pytest.mark.parametrize("value", ["0", "-5", "0.5", "many"])
def test_a_rerank_depth_below_one_is_refused(tmp_path, monkeypatch, value):
    """Zero reads as "no limit" and would behave as its opposite."""
    path = write_config(tmp_path, f"profiles:\n  local:\n    rerank_depth: {value}\n")
    monkeypatch.setenv("JACKRYAN_CONFIG", path)
    monkeypatch.delenv("JACKRYAN_PROFILE", raising=False)
    with pytest.raises(ConfigError) as exc:
        load_config()
    assert "rerank_depth" in str(exc.value)


@pytest.mark.parametrize("value", ["0", "-1", "none"])
def test_a_window_budget_below_one_is_refused(tmp_path, monkeypatch, value):
    path = write_config(tmp_path, f"profiles:\n  local:\n    window_max_chars: {value}\n")
    monkeypatch.setenv("JACKRYAN_CONFIG", path)
    monkeypatch.delenv("JACKRYAN_PROFILE", raising=False)
    with pytest.raises(ConfigError):
        load_config()


def test_a_store_opens_under_changed_retrieval_settings(config, gate, corpus):
    """Retrieval settings write nothing, so no store is refused for them.

    This is a stronger claim than the one extraction settings get. Those change
    stored text and are kept out of the contract on a deliberate trade; a
    reranker and a window budget leave no residue at all.
    """
    from conftest import TEST_DIMENSIONS
    from jackryan.app import build_context
    from jackryan.config import Config, Profile
    from jackryan.embedding.deterministic import DeterministicEmbedder

    def open_with(**profile_kwargs):
        wired = Config(
            contract=config.contract,
            profile=Profile(name="test", embedder="deterministic", **profile_kwargs),
            data_dir=config.data_dir,
        )
        return build_context(
            wired, embedder=DeterministicEmbedder(TEST_DIMENSIONS), gate=gate
        )

    first = open_with(window_max_chars=3000)
    casefile = first.casefiles.create("Settings")
    first.ingestion.ingest(casefile.short_id, corpus)
    identity = first.corpus_fingerprint
    first.close()

    # A reranker named, a different depth and a different window budget: the
    # store still opens and reports the identity it recorded. Not searched here,
    # because a named reranker is built when a search first needs it and there
    # are no weights in this suite — that refusal is its own test above.
    named = open_with(
        reranker_model="Xenova/ms-marco-MiniLM-L-6-v2",
        rerank_depth=25,
        window_max_chars=500,
    )
    try:
        assert named.corpus_fingerprint == identity
    finally:
        named.close()

    # And with the settings merely changed, the corpus is searchable as before.
    changed = open_with(window_max_chars=500, rerank_depth=25)
    try:
        assert changed.corpus_fingerprint == identity
        assert changed.search.search(casefile.short_id, "dredging survey", limit=3)
    finally:
        changed.close()
