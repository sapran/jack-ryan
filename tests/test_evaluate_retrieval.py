"""The retrieval evaluation harness: its set, its metrics, and its gate.

The harness itself needs the real embedder and so cannot run in this suite. What
can be tested here is everything around that: that the query set is admissible
and not trivially satisfied, that the metrics are arithmetic rather than
opinion, that judgements survive a reingest, and that the baseline gate can
actually fail.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent


def _load_harness():
    spec = importlib.util.spec_from_file_location(
        "evaluate_retrieval", REPO / "scripts" / "evaluate_retrieval.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    # Registered before it is executed: `dataclasses` resolves a class's module
    # through `sys.modules`, and a module absent from it fails to define one.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


harness = _load_harness()


# --- the evaluation set ----------------------------------------------------


def test_every_judgement_names_a_document_in_the_set():
    for judgement in harness.JUDGEMENTS:
        assert judgement.filename in harness.DOCUMENTS, judgement.query


def test_every_judgement_phrase_appears_in_its_document():
    """A phrase that is not in the document would make the query unanswerable,
    and the metric would report a retrieval failure that is really a typo."""
    for judgement in harness.JUDGEMENTS:
        body = harness._normalise(harness.DOCUMENTS[judgement.filename])
        assert harness._normalise(judgement.phrase) in body, judgement.phrase


def test_all_three_working_languages_are_represented():
    languages = {j.language for j in harness.JUDGEMENTS}
    assert languages == {"en", "uk", "ru"}


def test_the_corpus_carries_documents_that_answer_nothing():
    """Without distractors recall is satisfied by a corpus in which everything
    is relevant."""
    answering = {j.filename for j in harness.JUDGEMENTS}
    distractors = set(harness.DOCUMENTS) - answering
    assert len(distractors) >= 2


def test_each_language_has_a_query_sharing_no_word_with_its_answer():
    """A query that repeats the target's words is answered by keyword search
    alone and says nothing about semantic retrieval."""
    for language in ("en", "uk", "ru"):
        disjoint = [
            j
            for j in harness.JUDGEMENTS
            if j.language == language
            and not (
                harness.content_words(j.query, language)
                & harness.content_words(j.phrase, language)
            )
        ]
        assert disjoint, f"no query in {language} avoids the words of its own answer"


# --- metrics ---------------------------------------------------------------


@pytest.mark.parametrize(
    "relevance,k,expected",
    [
        ([True, False, False], 1, 1.0),
        ([False, False, True], 1, 0.0),
        ([False, False, True], 3, 1.0),
        ([False, False, True], 2, 0.0),
        ([False, False, False], 10, 0.0),
        ([], 10, 0.0),
    ],
)
def test_recall_at_k(relevance, k, expected):
    assert harness.recall_at_k(relevance, k) == expected


@pytest.mark.parametrize(
    "relevance,expected",
    [
        ([True, False], 1.0),
        ([False, True], 0.5),
        ([False, False, False, True], 0.25),
        ([False] * 20, 0.0),
        ([], 0.0),
    ],
)
def test_mrr_at_k(relevance, expected):
    assert harness.mrr_at_k(relevance, harness.MRR_AT) == expected


def test_mrr_ignores_a_hit_beyond_the_cut_off():
    beyond = [False] * harness.MRR_AT + [True]
    assert harness.mrr_at_k(beyond, harness.MRR_AT) == 0.0


def test_aggregate_averages_over_queries():
    figures = harness.aggregate([[True], [False]])
    assert figures["recall@1"] == 0.5
    assert figures[f"mrr@{harness.MRR_AT}"] == 0.5


def test_relevance_needs_both_the_document_and_the_phrase():
    judgement = harness.Judgement(
        query="q", language="en", filename="a.md", phrase="the harbour lease"
    )
    assert harness.is_relevant(judgement, "a.md", "about the harbour lease today")
    assert not harness.is_relevant(judgement, "b.md", "about the harbour lease today")
    assert not harness.is_relevant(judgement, "a.md", "about something else")


def test_a_phrase_split_across_lines_still_matches():
    """Chunk text wraps; a judgement written on one line must still resolve."""
    judgement = harness.Judgement(
        query="q", language="en", filename="a.md", phrase="the harbour lease"
    )
    assert harness.is_relevant(judgement, "a.md", "signed the harbour\nlease in March")


# --- measuring through the service layer -----------------------------------


@pytest.fixture
def evaluated(context, tmp_path):
    """The harness's own corpus, ingested through the real pipeline."""
    corpus = tmp_path / "evaluation-corpus"
    harness.write_corpus(corpus, harness.DOCUMENTS)
    casefile = context.casefiles.create("Retrieval Evaluation")
    report = context.ingestion.ingest(casefile.short_id, corpus)
    assert not report.failed
    return context, casefile, corpus


def _conditions(**overrides):
    base = {
        "embedder": "deterministic",
        "reranker": "none",
        "query_set": "built-in",
        "limit": 10,
    }
    return base | overrides


def _chunk_ids(context, casefile, query: str) -> list[str]:
    hits = context.search.search(casefile.short_id, query, limit=10)
    return [hit.chunk.id for hit in hits]


def test_judgements_resolve_the_same_after_a_reingest(evaluated):
    """Chunk ids are minted afresh on every rebuild. A judgement pinned to one
    would measure nothing the second time it is run."""
    context, casefile, corpus = evaluated
    probe = harness.JUDGEMENTS[0].query
    before = _chunk_ids(context, casefile, probe)
    first = harness.measure(
        context, casefile.short_id, harness.JUDGEMENTS, limit=10, conditions=_conditions()
    )

    context.ingestion.ingest(casefile.short_id, corpus)
    after = _chunk_ids(context, casefile, probe)
    second = harness.measure(
        context, casefile.short_id, harness.JUDGEMENTS, limit=10, conditions=_conditions()
    )

    # Without this the test would pass on a store that never rebuilt anything,
    # and would say nothing about what it claims to protect.
    assert before and after and before != after, "the reingest did not mint new chunk ids"
    assert first.metrics == second.metrics
    assert [q["rank"] for q in first.per_query] == [q["rank"] for q in second.per_query]


def test_the_harness_reports_the_order_the_service_gave_it(evaluated, monkeypatch):
    """A harness with its own copy of the ranking rules measures that copy."""
    context, casefile, _ = evaluated
    judgement = harness.JUDGEMENTS[0]
    real = context.search.search(casefile.short_id, judgement.query, limit=10)
    assert real, "the fixture query must retrieve something for this test to mean anything"

    # Hand back the service's own hits, reversed. A harness that re-ranked what
    # it was given would recover the original position; one that reports what it
    # was handed cannot.
    reversed_hits = list(reversed(real))
    monkeypatch.setattr(
        context.search, "search", lambda *args, **kwargs: list(reversed_hits)
    )
    measured = harness.measure(
        context, casefile.short_id, (judgement,), limit=10, conditions=_conditions()
    )

    expected = next(
        (
            index
            for index, hit in enumerate(reversed_hits, start=1)
            if harness.is_relevant(judgement, hit.document.filename, hit.chunk.text)
        ),
        None,
    )
    assert measured.per_query[0]["rank"] == expected


def test_measurement_reports_both_legs_and_every_language(evaluated):
    context, casefile, _ = evaluated
    measured = harness.measure(
        context, casefile.short_id, harness.JUDGEMENTS, limit=10, conditions=_conditions()
    )
    assert set(measured.metrics) == {"keyword", "vector", "fused"}
    assert set(measured.by_language) == {"en", "uk", "ru"}
    for figures in measured.metrics.values():
        assert set(figures) == {f"recall@{k}" for k in harness.RECALL_AT} | {
            f"mrr@{harness.MRR_AT}"
        }


def test_a_stand_in_run_is_marked_as_not_a_quality_claim(evaluated, capsys):
    context, casefile, _ = evaluated
    measured = harness.measure(
        context, casefile.short_id, harness.JUDGEMENTS[:2], limit=10, conditions=_conditions()
    )
    harness.print_report(measured)
    printed = capsys.readouterr().out
    assert "not retrieval quality" in printed
    assert "embedder=deterministic" in printed
    assert "reranker=none" in printed


def test_a_real_embedder_run_is_not_marked_as_mechanism_only(evaluated, capsys):
    context, casefile, _ = evaluated
    measured = harness.measure(
        context,
        casefile.short_id,
        harness.JUDGEMENTS[:2],
        limit=10,
        conditions=_conditions(embedder="model"),
    )
    harness.print_report(measured)
    assert "not retrieval quality" not in capsys.readouterr().out


# --- the baseline gate -----------------------------------------------------


def _measurement(**metrics):
    return harness.Measurement(
        conditions=_conditions(),
        metrics={"fused": {"recall@1": 0.8, "mrr@10": 0.9} | metrics},
        by_language={},
    )


def test_a_metric_below_the_baseline_is_reported_with_its_size():
    baseline = {"metrics": {"fused": {"recall@1": 0.8, "mrr@10": 0.9}}}
    fallen = harness.compare(_measurement(**{"recall@1": 0.5}), baseline, harness.TOLERANCE)
    assert len(fallen) == 1
    assert "recall@1" in fallen[0]
    assert "0.500" in fallen[0] and "0.800" in fallen[0] and "-0.300" in fallen[0]


def test_a_metric_at_the_baseline_is_not_a_regression():
    baseline = {"metrics": {"fused": {"recall@1": 0.8, "mrr@10": 0.9}}}
    assert harness.compare(_measurement(), baseline, harness.TOLERANCE) == []


def test_a_hair_below_the_baseline_is_within_tolerance():
    baseline = {"metrics": {"fused": {"recall@1": 0.8, "mrr@10": 0.9}}}
    measured = _measurement(**{"recall@1": 0.8 - harness.TOLERANCE / 2})
    assert harness.compare(measured, baseline, harness.TOLERANCE) == []


def test_a_metric_the_baseline_records_but_the_run_lacks_is_reported():
    baseline = {"metrics": {"fused": {"recall@1": 0.8}, "rerank": {"recall@1": 0.9}}}
    fallen = harness.compare(_measurement(), baseline, harness.TOLERANCE)
    assert any("not measured in this run" in line for line in fallen)


def test_a_baseline_recorded_under_other_conditions_is_not_compared():
    """Comparing a real-embedder run against a stand-in baseline would report a
    regression that is nothing of the kind, or hide one that is."""
    baseline = {"conditions": _conditions(embedder="model"), "metrics": {}}
    differing = harness.conditions_match(_measurement(), baseline)
    assert any("embedder" in line for line in differing)


def test_matching_conditions_compare_cleanly():
    baseline = {"conditions": _conditions(), "metrics": {}}
    assert harness.conditions_match(_measurement(), baseline) == []


def run_harness(monkeypatch, *args) -> int:
    """Drive `main()` the way the command line would."""
    monkeypatch.setattr(sys, "argv", ["evaluate_retrieval.py", *args])
    return harness.main()


def test_an_ordinary_run_leaves_the_baseline_untouched(tmp_path, monkeypatch, capsys):
    """Recording a baseline is a deliberate act, not something a run performs
    because the numbers changed."""
    baseline = tmp_path / "baseline.json"
    original = {"conditions": _conditions(), "metrics": {"fused": {"recall@1": 0.1}}}
    baseline.write_text(json.dumps(original), encoding="utf-8")

    run_harness(monkeypatch, "--embedder", "deterministic", "--baseline", str(baseline))
    capsys.readouterr()

    assert json.loads(baseline.read_text(encoding="utf-8")) == original


def test_record_writes_the_baseline(tmp_path, monkeypatch, capsys):
    baseline = tmp_path / "baseline.json"
    assert (
        run_harness(
            monkeypatch,
            "--embedder",
            "deterministic",
            "--baseline",
            str(baseline),
            "--record",
        )
        == 0
    )
    capsys.readouterr()
    written = json.loads(baseline.read_text(encoding="utf-8"))
    assert written["conditions"]["embedder"] == "deterministic"
    assert written["metrics"]["fused"]["recall@1"] >= 0.0


def test_a_run_below_its_baseline_exits_non_zero(tmp_path, monkeypatch, capsys):
    """The gate must be able to fail, or it certifies nothing."""
    baseline = tmp_path / "baseline.json"
    import sys as _sys

    monkeypatch.setattr(
        _sys,
        "argv",
        [
            "evaluate_retrieval.py",
            "--embedder",
            "deterministic",
            "--baseline",
            str(baseline),
            "--record",
        ],
    )
    harness.main()
    recorded = json.loads(baseline.read_text(encoding="utf-8"))

    # Raise the recorded figures out of reach, then run again unchanged.
    for figures in recorded["metrics"].values():
        for metric in figures:
            figures[metric] = 1.0
    baseline.write_text(json.dumps(recorded), encoding="utf-8")

    monkeypatch.setattr(
        _sys,
        "argv",
        ["evaluate_retrieval.py", "--embedder", "deterministic", "--baseline", str(baseline)],
    )
    assert harness.main() == 1
    assert "below the baseline" in capsys.readouterr().out


def test_the_workspace_is_removed_when_the_run_ends(tmp_path, monkeypatch, capsys):
    """The corpus and store it built must not survive the run.

    A measurement that leaves a corpus behind is a measurement that fills a disk,
    and this one writes invented case material — it should exist for as long as
    the figures take to compute and no longer.
    """
    import glob
    import tempfile

    before = set(glob.glob(f"{tempfile.gettempdir()}/jackryan-evaluate-*"))
    run_harness(
        monkeypatch, "--embedder", "deterministic", "--baseline", str(tmp_path / "b.json")
    )
    capsys.readouterr()
    after = set(glob.glob(f"{tempfile.gettempdir()}/jackryan-evaluate-*"))
    assert after == before


def test_the_workspace_is_kept_when_asked(tmp_path, monkeypatch, capsys):
    import glob
    import shutil
    import tempfile

    before = set(glob.glob(f"{tempfile.gettempdir()}/jackryan-evaluate-*"))
    run_harness(
        monkeypatch,
        "--embedder",
        "deterministic",
        "--baseline",
        str(tmp_path / "b.json"),
        "--keep",
    )
    capsys.readouterr()
    kept = set(glob.glob(f"{tempfile.gettempdir()}/jackryan-evaluate-*")) - before
    try:
        assert len(kept) == 1
    finally:
        for path in kept:
            shutil.rmtree(path, ignore_errors=True)


# --- an operator's own material --------------------------------------------


def _operator_set(tmp_path):
    """A tiny corpus and its judgements, in the shape an operator would supply."""
    corpus = tmp_path / "mine"
    corpus.mkdir()
    (corpus / "award.md").write_text(
        "# Award\n\nThe berth was awarded to Northgate Holdings in March.\n",
        encoding="utf-8",
    )
    (corpus / "variation.md").write_text(
        "# Variation\n\nThe berth held by Northgate Holdings gains a weighbridge.\n",
        encoding="utf-8",
    )
    (corpus / "kitchen.txt").write_text(
        "Notes about baking bread and grinding coffee.\n", encoding="utf-8"
    )
    queries = tmp_path / "queries.json"
    queries.write_text(
        json.dumps(
            [
                {
                    "query": "Who holds the berth?",
                    "language": "en",
                    "filename": "award.md",
                    "phrase": "awarded to Northgate Holdings",
                    "also": [
                        {
                            "filename": "variation.md",
                            "phrase": "held by Northgate Holdings",
                        }
                    ],
                }
            ]
        ),
        encoding="utf-8",
    )
    return corpus, queries


def test_an_operator_can_measure_their_own_material(tmp_path, monkeypatch, capsys):
    """The requirement is that this works without modifying the harness.

    `--no-recognition` is part of that: the recognition engine is built before the
    first document is read, so a text-only corpus would otherwise need model
    weights on disk for no reason.
    """
    corpus, queries = _operator_set(tmp_path)
    code = run_harness(
        monkeypatch,
        "--embedder",
        "deterministic",
        "--baseline",
        str(tmp_path / "none.json"),
        "--corpus",
        str(corpus),
        "--queries",
        str(queries),
        "--no-recognition",
    )
    printed = capsys.readouterr().out
    assert code == 0
    assert "query_set=operator" in printed
    assert "queries=1" in printed


def test_an_operator_judgement_may_name_alternative_answers(tmp_path):
    """Near-duplicates are the ordinary case in a real corpus, so an operator's
    judgements need the same escape the built-in set uses."""
    _, queries = _operator_set(tmp_path)
    judgements = harness.load_judgements(queries)

    assert len(judgements) == 1
    judgement = judgements[0]
    assert judgement.also == (("variation.md", "held by Northgate Holdings"),)
    # Either passage answers it.
    assert harness.is_relevant(judgement, "award.md", "awarded to Northgate Holdings")
    assert harness.is_relevant(judgement, "variation.md", "held by Northgate Holdings")
    assert not harness.is_relevant(judgement, "kitchen.txt", "baking bread")


def test_a_corpus_without_judgements_is_refused(tmp_path, monkeypatch):
    """The two go together: someone else's corpus needs someone else's answers."""
    corpus, _ = _operator_set(tmp_path)
    with pytest.raises(SystemExit):
        run_harness(monkeypatch, "--corpus", str(corpus))
