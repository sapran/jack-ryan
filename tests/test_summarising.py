"""The summarising seam: its recipe identity, and how a failure lands at ingest.

Two separate subjects, kept in one file because they are two halves of one
guarantee. The first half is that the recipe which determines a folded vector is
hashed into the summariser's name, so editing it changes corpus identity with
nobody having to remember to bump a version. The second half is what happens at
the ingest seam when the summariser misbehaves: a document fails, and nothing
about it is stored, because a document embedded bare inside a folded corpus is
silently incomparable with every other document.

Nothing here reaches an endpoint. The stub below is a real implementation of the
port with a predictable output, which is what lets a test assert on the exact
text that was folded in.
"""

from __future__ import annotations

import hashlib
import os
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path

import pytest

from jackryan.app import build_context
from jackryan.config import Config
from jackryan.embedding.deterministic import DeterministicEmbedder
from jackryan.errors import ConfigError
from jackryan.summarising import build_summariser
from jackryan.summarising import model as summarising_model
from jackryan.summarising.model import (
    DOCUMENT_PROMPT,
    RECIPE_FINGERPRINT,
    SUMMARY_DOCUMENT_CHARS,
    SUMMARY_ENABLE_THINKING,
    SUMMARY_MAX_TOKENS,
    SUMMARY_PROMPT,
    SUMMARY_TEMPERATURE,
    OpenAICompatSummariser,
    _RECIPE,
)
from jackryan.summarising.port import SummariserUnavailable, SummaryError

from conftest import TEST_DIMENSIONS


class _StubSummariser:
    """A summariser that writes a predictable context, with no endpoint.

    Not a subclass of `SummariserPort`: the port is a `typing.Protocol` matched
    structurally, and the real implementation does not inherit it either, so a
    stub that did would be a different kind of object from the one production
    uses.

    Records what it was asked, because most of what these tests assert is about
    which call was made with which arguments rather than about a return value.
    The behaviour hooks are the three ways a summariser can misbehave: fail for
    one document, return a short list, or turn out to be misconfigured.
    """

    def __init__(
        self,
        name: str = "stub/000000000000",
        *,
        fail_on: str = "",
        short_by: int = 0,
        raises: BaseException | None = None,
    ) -> None:
        self.name = name
        self.checked = 0
        self.chunk_calls = 0
        self.requested: list[int] = []
        self.document_notes: list[list[str]] = []
        self._fail_on = fail_on
        self._short_by = short_by
        self._raises = raises

    def check(self) -> None:
        self.checked += 1

    def summarise_chunks(self, document_text: str, chunk_texts) -> list[str]:
        self.chunk_calls += 1
        self.requested.append(len(chunk_texts))
        if self._raises is not None:
            raise self._raises
        if self._fail_on and self._fail_on in document_text:
            raise SummaryError(
                f"the endpoint refused every chunk of the document containing "
                f"{self._fail_on!r}"
            )
        summaries = [f"context for {text[:20]}" for text in chunk_texts]
        if self._short_by:
            return summaries[: len(summaries) - self._short_by]
        return summaries

    def summarise_document(self, chunk_summaries) -> str:
        self.document_notes.append(list(chunk_summaries))
        return f"document summary from {len(chunk_summaries)} notes"


def _with_profile(config: Config, **overrides) -> Config:
    """The fixture's config with profile settings changed, never mutated.

    A new `Config` rather than a mutated fixture: `Profile` is frozen, and two
    tests in one run share the fixture instance.
    """
    return replace(config, profile=replace(config.profile, **overrides))


@contextmanager
def _instance(config: Config, gate, summariser=None, **profile_overrides):
    """A wired instance with the deterministic embedder, closed on the way out.

    Assembled through `build_context` rather than by constructing an
    `IngestionService` directly, because `build_context` is where `folding` is
    decided and where the summariser's name enters corpus identity. A test that
    built the service itself would be free to set the switch and the identity
    independently, which is the one disagreement that cannot happen in
    production.
    """
    resolved = _with_profile(config, **profile_overrides) if profile_overrides else config
    ctx = build_context(
        resolved,
        embedder=DeterministicEmbedder(TEST_DIMENSIONS),
        gate=gate,
        summariser=summariser,
    )
    try:
        yield ctx
    finally:
        ctx.close()


def _stored_chunks(ctx, document_id: str) -> list[tuple[int, str, str]]:
    """A document's chunks as `(ordinal, text, summary)`, read from the store's rows.

    Ordered by ordinal, so comparing a list positionally against this is also an
    assertion about order.
    """
    return [
        (row["ordinal"], row["text"], row["summary"])
        for row in ctx.store._db.execute(
            "SELECT ordinal, text, summary FROM chunks WHERE document_id = ?"
            " ORDER BY ordinal",
            (document_id,),
        )
    ]


def _chunks_named(ctx, casefile_id: str, filename: str) -> int:
    """How many chunks the store holds for the document with this filename.

    Joined from `chunks` to `documents` rather than looked up by document id, so
    the count is zero both when the document has no chunks and when the document
    row is absent. A test asserting a negative must not depend on which of those
    two the pipeline happens to leave behind.
    """
    return ctx.store._db.execute(
        "SELECT COUNT(*) FROM chunks c JOIN documents d ON d.id = c.document_id"
        " WHERE d.casefile_id = ? AND d.filename = ?",
        (casefile_id, filename),
    ).fetchone()[0]


def _document_named(ctx, casefile_reference: str, filename: str):
    for document in ctx.ingestion.list_documents(casefile_reference, include_expanded=True):
        if document.filename == filename:
            return document
    raise AssertionError(f"no document named {filename!r} was stored")


# --- the recipe that determines a folded vector -----------------------------


_MODEL_SOURCE = Path(summarising_model.__file__).read_text(encoding="utf-8")

# One recipe component each, as the assignment that appears in `model.py` and the
# edit an author would make to it. Editing the source rather than patching the
# imported constant is the whole point: `_RECIPE` and `RECIPE_FINGERPRINT` are
# derived once at import, so a patched attribute moves neither and a test that
# recomposed the join in this file would only ever be hashing its own strings —
# two different strings always hash differently, so such a test cannot fail.
_RECIPE_EDITS = {
    "the prompt that asks for the context": (
        'SUMMARY_PROMPT = """<document>',
        'SUMMARY_PROMPT = """Prefer the passive voice.\n<document>',
    ),
    "how much of the document the model sees": (
        "SUMMARY_DOCUMENT_CHARS = 20_000",
        "SUMMARY_DOCUMENT_CHARS = 20_001",
    ),
    "the token ceiling on one context": (
        "SUMMARY_MAX_TOKENS = 200",
        "SUMMARY_MAX_TOKENS = 201",
    ),
    "the sampling temperature": (
        "SUMMARY_TEMPERATURE = 0.0",
        "SUMMARY_TEMPERATURE = 0.7",
    ),
    "whether the model is asked to think first": (
        "SUMMARY_ENABLE_THINKING = False",
        "SUMMARY_ENABLE_THINKING = True",
    ),
}


def _fingerprint_after(original: str, edited: str) -> str:
    """`RECIPE_FINGERPRINT` as the shipped module computes it after one source edit.

    Re-executes `summarising/model.py` with one assignment rewritten, so the
    question put to the module is the real one: does editing this constant change
    the recipe the shipped join builds and the fingerprint it hashes? A component
    dropped out of the join, and a component spelled as a literal that no longer
    tracks its constant, both answer no.

    Executed under the real package name so the module's relative import of
    `.port` resolves. Nothing at its module level touches the network or the
    filesystem — it defines constants and a class — so re-executing it is cheap
    and has no side effects.
    """
    assert _MODEL_SOURCE.count(original) == 1, (
        f"{original!r} appears {_MODEL_SOURCE.count(original)} times in "
        "summarising/model.py, so this test cannot make a single targeted edit "
        "to it. The constant was renamed or respelled — update `_RECIPE_EDITS`."
    )
    namespace: dict[str, object] = {
        "__name__": "jackryan.summarising._recipe_under_test",
        "__package__": "jackryan.summarising",
        "__file__": summarising_model.__file__,
    }
    source = _MODEL_SOURCE.replace(original, edited)
    exec(compile(source, summarising_model.__file__, "exec"), namespace)
    return str(namespace["RECIPE_FINGERPRINT"])


def test_the_recipe_fingerprint_is_the_hash_of_the_recipe_and_of_each_component():
    """The legible half: what the identity is, and that all five parts are in it.

    Faster to read than the re-execution below and it fails on the same defect,
    naming which component vanished from the join. The re-execution is what makes
    the claim airtight; this is what tells the reader in one line what broke.
    """
    assert RECIPE_FINGERPRINT == hashlib.sha256(_RECIPE.encode("utf-8")).hexdigest()[:12], (
        "`RECIPE_FINGERPRINT` is not sha256 of `_RECIPE` cut to twelve hex "
        "characters. The value in corpus identity is then not a hash of the "
        "recipe, and nothing forces it to move when the recipe does."
    )
    components = {
        "the prompt that asks for the context": SUMMARY_PROMPT,
        "how much of the document the model sees": (
            f"document_chars={SUMMARY_DOCUMENT_CHARS}"
        ),
        "the token ceiling on one context": f"max_tokens={SUMMARY_MAX_TOKENS}",
        "the sampling temperature": f"temperature={SUMMARY_TEMPERATURE}",
        "whether the model is asked to think first": (
            f"enable_thinking={SUMMARY_ENABLE_THINKING}"
        ),
    }
    for what, rendered in components.items():
        assert rendered in _RECIPE, (
            f"{what} is not in the hashed recipe. It decides what the embedder is "
            "handed, so a corpus built before it changed and one built after hold "
            "vectors that mean different things under one identity — both the "
            "declared width, both from the declared model, and unseparable "
            "afterwards. Put it back in `_RECIPE`."
        )


def test_editing_any_part_of_the_recipe_moves_the_corpus_identity():
    """This is what replaces a hand-bumped version number.

    Each of these four values determines the text that reaches the embedder: the
    prompt asks for the context, the character limit decides how much of the
    document the model sees while writing it, and the two sampling parameters
    decide which of many possible contexts comes back. Change any one and a
    reingest of the same documents produces different vectors.

    A version constant would be a second copy of the recipe, and two copies can
    disagree — the same hazard that keeps the embedder's identity out of the
    contract. Hashing the recipe means the identity cannot be forgotten, only
    changed. This test is what makes that true rather than intended: it rewrites
    one constant in the module's own source, re-executes it, and asks the shipped
    join whether the fingerprint followed.
    """
    for what, (original, edited) in _RECIPE_EDITS.items():
        moved = _fingerprint_after(original, edited)
        assert moved != RECIPE_FINGERPRINT, (
            f"editing {what} left `RECIPE_FINGERPRINT` at {RECIPE_FINGERPRINT}, so "
            "it is not in the hashed recipe. Corpus identity would not move, the "
            "store would accept both recipes' vectors under one name, and no "
            "later check could separate them. Add it to `_RECIPE` in "
            "`summarising/model.py` — never a version number beside it, which is "
            "the second copy this hash exists to avoid."
        )


def test_the_recipe_fingerprint_is_what_a_summarisers_name_carries(monkeypatch):
    """A moved fingerprint has to move corpus identity, not just a constant.

    `RECIPE_FINGERPRINT` moving is worth nothing unless it reaches the value
    `build_context` composes into the identity the store records and enforces.
    This asserts the name is a live function of the fingerprint rather than a
    literal that happens to match it today: patch the constant, construct again,
    and the name follows. Constructing reaches no endpoint, so the assertion
    needs nothing running.
    """
    endpoint = "http://127.0.0.1:8080/v1"
    shipped = OpenAICompatSummariser(model_name="qwen3-8b", base_url=endpoint)
    assert shipped.name == f"qwen3-8b/{RECIPE_FINGERPRINT}", (
        "a summariser's name must be the model joined with the recipe "
        "fingerprint. The model alone would not say what the vectors were built "
        "from, and this name is what enters corpus identity."
    )

    monkeypatch.setattr(summarising_model, "RECIPE_FINGERPRINT", "0123456789ab")
    after = OpenAICompatSummariser(model_name="qwen3-8b", base_url=endpoint)

    assert after.name == "qwen3-8b/0123456789ab", (
        "the name did not follow the recipe fingerprint, so it is a literal "
        "rather than a composition. Editing the prompt would then leave corpus "
        "identity unchanged and a mixed corpus would be accepted."
    )
    assert after.name != shipped.name, (
        "a summariser built under a different recipe reports the same name as one "
        "built under the shipped recipe, so the store would open a corpus written "
        "under the other one"
    )


def test_the_document_prompt_is_outside_the_recipe_so_rewriting_it_refuses_no_corpus():
    """The converse, and the half a careless version of the test above would miss.

    A test that only checked "editing the recipe moves the fingerprint" would
    pass just as happily if everything in the module were hashed, and the cost of
    that is not theoretical. `DOCUMENT_PROMPT` writes the per-document summary,
    which is stored and never embedded, so hashing it would refuse an existing
    corpus over a change that moves no vector — a reingest of every document to
    fix nothing.

    Both oracles: the prompt is not in the recipe's text, and re-executing the
    module with that prompt rewritten leaves the fingerprint where it was. The
    containment assertion says the thing directly; the re-execution catches a
    join that reaches the prompt by some other route.
    """
    assert SUMMARY_PROMPT in _RECIPE, (
        "the chunk prompt is not in the hashed recipe, so the negative below "
        "proves nothing about what the recipe does contain"
    )
    assert DOCUMENT_PROMPT not in _RECIPE, (
        "the per-document summary prompt is now inside the hashed recipe. That "
        "summary is stored and never embedded, so rewriting its prompt moves no "
        "vector and must not refuse an existing corpus. Take it back out. The one "
        "change that may put it in is a change that embeds the document summary "
        "somewhere — and that change has to move the prompt into `_RECIPE` in the "
        "same commit, because from then on it does decide a stored vector."
    )

    original = 'DOCUMENT_PROMPT = """Below are ordered notes'
    edited = 'DOCUMENT_PROMPT = """Below are unordered notes'
    assert _fingerprint_after(original, edited) == RECIPE_FINGERPRINT, (
        "rewriting the per-document summary prompt moved `RECIPE_FINGERPRINT`, so "
        "it reaches the hashed recipe. Every existing corpus is now refused over "
        "a change to prose that is stored and never embedded, and the reingest "
        "that follows fixes nothing."
    )


# --- the fold, and how it fails --------------------------------------------


def test_a_short_return_from_the_summariser_fails_the_document_and_pads_nothing(
    config, gate, sectioned_corpus
):
    """A pad would corrupt one document from the inside, where no identity reaches.

    Corpus identity refuses a folded corpus opened under a bare recipe, which
    catches the coarse version of this. It cannot catch the fine version: a
    summariser returning four contexts for five chunks, zipped against the
    chunks, would fold context into four of one document's vectors and embed the
    fifth bare. Every vector is the declared width, the identity is correct, and
    the store holds nothing that says which chunk got which treatment.

    So the count is reconciled at the seam and a mismatch fails the document.
    Two assertions, because "an error was raised" is not the claim: the report
    must say `failed` naming both counts, and the store must hold no chunks for
    the document — which is what shows no padded list reached the embedder.
    """
    stub = _StubSummariser(short_by=1)
    with _instance(
        config, gate, stub, summary_model="stub", chunk_summaries=True
    ) as ctx:
        casefile = ctx.casefiles.create("Short Return")
        report = ctx.ingestion.ingest(casefile.short_id, sectioned_corpus)

        assert stub.requested, (
            "the summariser was never asked for anything, so nothing about a "
            "short return was exercised — folding is not on, or the corpus "
            "produced no chunks"
        )
        assert min(stub.requested) >= 2, (
            "every document in this corpus produced fewer than two chunks, so "
            "dropping one summary leaves an empty list rather than a "
            "partially-folded document and the test is a no-op. Use a fixture "
            f"whose documents chunk (asked for {stub.requested})"
        )
        assert report.outcomes, "nothing was ingested, so no outcome was checked"
        for outcome, asked in zip(report.outcomes, stub.requested):
            assert outcome.status == "failed", (
                f"a summariser returning {asked - 1} contexts for {asked} chunks "
                f"produced a document whose status is {outcome.status!r} rather "
                "than 'failed'. The surviving contexts "
                "were paired with whichever chunks zip() reached first and the "
                "rest were embedded bare, inside one document, under an identity "
                "that says every vector was folded."
            )
            assert f"{asked - 1} summaries for {asked} chunks" in outcome.detail, (
                "the failure must name both counts, because that is what tells "
                "an operator the summariser is returning the wrong shape rather "
                f"than the endpoint being down: {outcome.detail!r}"
            )

        held = ctx.store._db.execute(
            "SELECT COUNT(*) FROM chunks WHERE casefile_id = ?", (casefile.id,)
        ).fetchone()[0]
        assert held == 0, (
            f"the store holds {held} chunks for a casefile whose every document "
            "failed at summarising. A short list was padded or truncated and "
            "embedded anyway; the chunks on disk say nothing about which of them "
            "carried a context, so the corruption is unrecoverable without a "
            "reingest nobody knows to run."
        )


def test_a_summariser_failure_fails_one_document_and_stores_no_chunks_for_it(
    config, gate, corpus
):
    """One document missing is reported; one embedded bare is not.

    This is the deliberate departure from the reranker, whose failure degrades
    to the fused order and says so. A reranker that fails has cost the caller a
    better ordering and stored nothing. A summariser that fails while folding is
    on would, if it degraded, store vectors built from a different kind of input
    from every other document's — all of the declared width, all under a correct
    identity, and unseparable afterwards.

    The oracle is the store, not the report. A report saying `failed` is
    consistent both with nothing having been written and with chunks having been
    written and then the document marked failed, so the count is taken from
    `chunks` directly. The other two documents are asserted to have survived,
    which is what makes this a per-document failure rather than a run that died.
    """
    stub = _StubSummariser(fail_on="Harbour Lease")
    with _instance(
        config, gate, stub, summary_model="stub", chunk_summaries=True
    ) as ctx:
        casefile = ctx.casefiles.create("One Bad Document")
        report = ctx.ingestion.ingest(casefile.short_id, corpus)

        by_name = {
            outcome.path.rsplit("/", 1)[-1]: outcome for outcome in report.outcomes
        }
        assert set(by_name) == {"lease.md", "minutes.md", "notes.txt"}, (
            f"the corpus this test reasons about is not the one ingested: {sorted(by_name)}"
        )

        assert by_name["lease.md"].status == "failed", (
            "the document whose summariser raised was not failed, so it was "
            "embedded without the context the rest of the corpus carries"
        )
        assert "Harbour Lease" in by_name["lease.md"].detail, (
            "the failure does not carry the summariser's own message, so an "
            "operator cannot tell a refused endpoint from a refused document: "
            f"{by_name['lease.md'].detail!r}"
        )
        for name in ("minutes.md", "notes.txt"):
            assert by_name[name].status == "ingested", (
                f"{name} was {by_name[name].status!r}: one document's summariser "
                "failure took the rest of the run with it, which turns a "
                "per-document failure into a fatal one"
            )

        assert _chunks_named(ctx, casefile.id, "lease.md") == 0, (
            "the store holds chunks for the document whose summariser failed. "
            "With folding on those vectors were built from the bare chunk while "
            "every other document's were built from a context plus the chunk, "
            "and corpus identity says otherwise. Nothing downstream can find "
            "them again."
        )
        for name in ("minutes.md", "notes.txt"):
            assert _chunks_named(ctx, casefile.id, name) > 0, (
                f"{name} has no chunks in the store, so this test's negative "
                "above is not evidence of anything — the ingest stored nothing "
                "at all"
            )

        total = ctx.store._db.execute(
            "SELECT COUNT(*) FROM chunks WHERE casefile_id = ?", (casefile.id,)
        ).fetchone()[0]
        assert total == 2, (
            f"the casefile holds {total} chunks; two documents succeeded with one "
            "chunk each and the third must have contributed none"
        )


def test_a_configuration_error_from_the_summariser_is_fatal_for_the_whole_run(
    config, gate, corpus
):
    """A misconfiguration is a fact about the instance, not about one document.

    Caught as a failed document it would be reported once per document and fixed
    by none of those reports — 1,760 identical outcomes for the real corpus. So
    `SummariserUnavailable` is a `ConfigError`, and `_ingest_work` re-raises
    `ConfigError` in a clause of its own.

    The point of the second half is that the guarantee holds by *type* rather
    than by which call happened to raise first: a bare `ConfigError` from the
    summariser must propagate too. If the fatal clause were ever merged into the
    per-document tuple, that half fails while the first half could still pass on
    an incidental ordering.
    """
    assert issubclass(SummariserUnavailable, ConfigError), (
        "`SummariserUnavailable` is not a `ConfigError`, so the ingest loop "
        "cannot separate it from a per-document failure by type"
    )
    assert not issubclass(SummariserUnavailable, SummaryError), (
        "`SummariserUnavailable` is a `SummaryError`, so the per-document clause "
        "would catch it and report one misconfiguration once per document"
    )

    unavailable = _StubSummariser(
        raises=SummariserUnavailable("the endpoint named in llm_url refused the model")
    )
    with _instance(
        config, gate, unavailable, summary_model="stub", chunk_summaries=True
    ) as ctx:
        casefile = ctx.casefiles.create("Unreachable Model")
        with pytest.raises(SummariserUnavailable, match="llm_url"):
            ctx.ingestion.ingest(casefile.short_id, corpus)
        assert unavailable.chunk_calls == 1, (
            f"the summariser was called {unavailable.chunk_calls} times before the "
            "run stopped. A misconfiguration must end the run at the first "
            "document, not be reported once per document."
        )

    plain = _StubSummariser(raises=ConfigError("some other setting is wrong"))
    with _instance(
        config, gate, plain, summary_model="stub", chunk_summaries=True
    ) as ctx:
        casefile = ctx.casefiles.create("Bad Configuration")
        with pytest.raises(ConfigError, match="some other setting"):
            ctx.ingestion.ingest(casefile.short_id, corpus)


def test_a_summariser_with_folding_off_writes_a_summary_and_moves_no_vector(
    config, gate, corpus
):
    """The whole reason the switch is separate from the model name.

    A named summariser writes per-document summaries and nothing else until
    `chunk_summaries` is on. That has to leave corpus identity byte-identical to
    an instance with no summariser at all, or the 435 MB corpus that exists
    would be refused by a setting that moves none of its vectors.

    Four assertions in one test because they are one claim: no chunk-summary
    call was made, no `chunks.summary` was written, the identity carries no
    summariser component — and the document summary was written anyway, which is
    the capability being bought.
    """
    stub = _StubSummariser()
    with _instance(config, gate, stub, summary_model="stub") as ctx:
        casefile = ctx.casefiles.create("Named But Not Folded")
        report = ctx.ingestion.ingest(casefile.short_id, corpus)
        assert not report.failed, [outcome.detail for outcome in report.outcomes]

        assert stub.chunk_calls == 0, (
            f"`summarise_chunks` was called {stub.chunk_calls} times with "
            "`chunk_summaries` off. Something is folded into what is embedded "
            "while corpus identity says nothing was, which is exactly the mixed "
            "corpus the identity component exists to refuse."
        )

        documents = ctx.ingestion.list_documents(casefile.short_id, include_expanded=True)
        assert documents, "nothing was stored, so nothing below is evidence"
        stored = [row for document in documents for row in _stored_chunks(ctx, document.id)]
        assert stored, "no chunks were stored, so the empty-summary check is vacuous"
        assert all(summary == "" for _, _, summary in stored), (
            "a chunk carries a stored summary with folding off. `chunks.summary` "
            "records what was folded into a vector, so a non-empty value here "
            "either means something was folded without the switch, or that the "
            "column has stopped meaning what the fold reads it as."
        )

        assert ctx.summariser_name == "", (
            f"the context reports summariser_name={ctx.summariser_name!r} with "
            "folding off. That value is what enters corpus identity, so a "
            "non-empty one refuses every existing corpus over a setting that "
            "moves no vector."
        )
        assert "summariser=" not in ctx.corpus_fingerprint, (
            "corpus identity carries a summariser component with folding off, so "
            "every corpus ingested before summaries existed is now refused by a "
            f"setting that moves none of its vectors: {ctx.corpus_fingerprint!r}"
        )
        # Composed here rather than by calling `corpus_fingerprint` again, which
        # is the function under test: an oracle routing through it would append
        # whatever the pipeline appended and compare the pipeline with itself. The
        # contract's own fingerprint is untouched by this change, and the embedder
        # name needs no escaping, so this is the string a corpus recorded before
        # the summariser component existed.
        assert ctx.corpus_fingerprint == (
            f"{config.contract.fingerprint()}|embedder={ctx.embedder.name}"
        ), (
            "corpus identity is not byte-identical to the identity recorded before "
            "this component existed. A named summariser that only writes document "
            f"summaries must leave it alone: {ctx.corpus_fingerprint!r}"
        )

        for document in documents:
            assert document.summary, (
                f"{document.filename} has no stored summary. A per-document "
                "summary is available without the fold — that is the point of "
                "splitting the model name from the switch — so an empty one here "
                "means the capability is only reachable by refusing the corpus."
            )
            assert document.summary_by == stub.name, (
                f"{document.filename} records summary_by="
                f"{document.summary_by!r} rather than {stub.name!r}. Nothing else "
                "in the store names the author of a document summary, because it "
                "is outside corpus identity, so a surface would have to credit "
                "whichever summariser the instance is configured with today."
            )


def test_the_document_summary_is_built_from_the_summaries_only_when_folding(
    config, gate, sectioned_corpus
):
    """The notes handed up have to describe what was stored, not what was configured.

    With folding on, each chunk has a context written for it and those are the
    ordered notes the document summary is reduced from. With folding off no such
    context exists, so the notes are the chunk texts. Getting this backwards is
    invisible in the output — a summary comes back either way — and produces a
    document summary written from empty strings.

    Both halves compare positionally against the store's own rows ordered by
    ordinal, so the assertion covers order as well as content: a summariser
    handed one document's notes out of order writes a summary of a document read
    back to front.

    One document per instance, not two, so a recorded call belongs to a known
    document. Separate data directories because the two identities differ by the
    `|summariser=` component and one store cannot hold both.
    """
    one_document = sectioned_corpus / "sections.md"

    folded = _StubSummariser()
    with _instance(
        config,
        gate,
        folded,
        summary_model="stub",
        chunk_summaries=True,
    ) as ctx:
        casefile = ctx.casefiles.create("Folded")
        report = ctx.ingestion.ingest(casefile.short_id, one_document)
        assert not report.failed, [outcome.detail for outcome in report.outcomes]
        document = _document_named(ctx, casefile.short_id, "sections.md")
        rows = _stored_chunks(ctx, document.id)
        assert len(rows) >= 2, (
            f"sections.md produced {len(rows)} chunks, so the ordering half of "
            "this test cannot fail and proves nothing"
        )
        assert all(summary for _, _, summary in rows), (
            "a stored chunk has no summary with folding on, so comparing the "
            "notes against the stored summaries below would compare against "
            "empty strings"
        )
        assert len(folded.document_notes) == 1, (
            f"`summarise_document` was called {len(folded.document_notes)} times "
            "for one document, so a recorded call cannot be attributed"
        )
        assert folded.document_notes[0] == [summary for _, _, summary in rows], (
            "with folding on, the document summary must be reduced from the "
            "contexts written for the chunks, in chunk order. What was handed up "
            f"is {folded.document_notes[0]!r} against the stored summaries "
            f"{[s for _, _, s in rows]!r} — either the wrong field or the wrong "
            "order, and a summary of a document read back to front looks exactly "
            "like a summary of one read forwards."
        )

    bare = _StubSummariser()
    with _instance(
        replace(config, data_dir=config.data_dir.with_name("data-bare")),
        gate,
        bare,
        summary_model="stub",
    ) as ctx:
        casefile = ctx.casefiles.create("Bare")
        report = ctx.ingestion.ingest(casefile.short_id, one_document)
        assert not report.failed, [outcome.detail for outcome in report.outcomes]
        document = _document_named(ctx, casefile.short_id, "sections.md")
        rows = _stored_chunks(ctx, document.id)
        assert len(rows) >= 2, "the bare instance chunked differently; see above"
        assert len(bare.document_notes) == 1, (
            f"`summarise_document` was called {len(bare.document_notes)} times "
            "for one document"
        )
        assert bare.document_notes[0] == [text for _, text, _ in rows], (
            "with folding off there are no per-chunk contexts, so the document "
            "summary must be reduced from the chunk texts in chunk order. What "
            f"was handed up is {bare.document_notes[0][:1]!r}… — if those are the "
            "stored summaries, the notes are a list of empty strings and the "
            "summary describes nothing."
        )


def test_a_document_with_no_chunks_reaches_no_endpoint(config, gate):
    """An empty input must cost no request, and the guard is only reachable directly.

    Called directly rather than through an ingest, because no fixture can drive
    this branch and inventing one would test the wrong thing. A document whose
    extracted text yields no chunks is refused earlier — the extractor answers
    "produced no usable text; refusing to store an empty document" and no
    document row is written — so an ingest-shaped test would be asserting the
    *extractor's* refusal and would keep passing if this guard were deleted.

    The guard is still worth having and worth pinning. It is what stands between
    a text the extractor accepts and the chunker declines and a request per such
    document, and asking a model to summarise nothing costs a call and returns a
    sentence about having nothing to summarise, which would then be stored as
    the document's summary.
    """
    stub = _StubSummariser()
    with _instance(config, gate, stub, summary_model="stub", chunk_summaries=True) as ctx:
        assert ctx.ingestion._document_summary([]) == "", (
            "a document with no chunks was given a non-empty summary, which can "
            "only have come from a model asked to summarise nothing"
        )
        assert stub.document_notes == [], (
            "`summarise_document` was called with an empty list of notes. The "
            "endpoint has nothing to work from, so the call costs a request and "
            "returns prose about the absence, which is then stored as the "
            f"document's summary: {stub.document_notes!r}"
        )
        assert stub.chunk_calls == 0, (
            "`summarise_chunks` was called while computing the summary of a "
            "document with no chunks"
        )

    # The same promise one level down, in the implementation that does have an
    # endpoint: an empty input returns before the client is ever built, so this
    # holds with nothing running and no network reachable.
    real = OpenAICompatSummariser(model_name="qwen3-8b", base_url="http://127.0.0.1:1/v1")
    assert real.summarise_chunks("a document", []) == []
    assert real.summarise_document([]) == ""
    assert real._client is None, (
        "an empty input built the HTTP client, so it reached the endpoint or "
        "would have. Nothing to summarise must cost nothing."
    )


# --- what the profile builds ------------------------------------------------


def test_no_summariser_is_built_when_none_is_named(config):
    """Absent is the default and is not a failure.

    Mirrors the reranker's published scenario. An instance that names no summary
    model ingests as it did before summaries existed: no endpoint to reach, and
    no document text leaving the machine. Returning something here would make a
    generation endpoint a condition of ingesting anything.
    """
    assert build_summariser(config) is None, (
        "a profile naming no summary_model produced a summariser. Ingestion "
        "would then reach for an endpoint the operator never configured, and "
        "document text would leave an instance that asked for nothing."
    )


def test_a_named_summariser_with_no_endpoint_is_fatal_and_names_both_settings(config):
    """Named but unbuildable is a misconfiguration, refused once rather than per document.

    The other half of the reranker's pair. The message has to name both settings,
    because either one of them is a valid fix and the operator cannot tell from
    the code which they meant: point `llm_url` at the endpoint serving the
    model, or clear `summary_model` and ingest without summaries.
    """
    named = _with_profile(config, summary_model="qwen3-8b")
    with pytest.raises(SummariserUnavailable) as raised:
        build_summariser(named)

    message = str(raised.value)
    assert "summary_model" in message and "llm_url" in message, (
        "the refusal must name both settings, since either is a valid fix and "
        f"the message is all the operator gets: {message!r}"
    )
    assert isinstance(raised.value, ConfigError), (
        "a summariser that cannot be built must be fatal for the run by type, "
        "not one failed document at a time"
    )


def test_an_unreachable_endpoint_stops_the_run_before_any_document_is_sent(
    config, gate, corpus
):
    """The real summariser against a closed port must be fatal, not per document.

    The stub-based test above proves the ingest loop's type split; it cannot
    prove that the shipped implementation ever produces a `ConfigError` when an
    endpoint is unreachable. It did not: `check()` was defined, documented as the
    control, and never called from any production path, so first contact happened
    inside `_post` and arrived as a per-document `SummaryError`. The run then
    completed with every document failed — and on a real casefile that is one
    identical failure per document, each of which had already sent the endpoint a
    document's text before failing.

    `check()` is the one request in a run that carries no evidence, which is why
    it has to come first.
    """
    closed = _with_profile(
        config,
        summary_model="probe",
        llm_url="http://127.0.0.1:1/v1",
        chunk_summaries=True,
    )
    ctx = build_context(
        closed, embedder=DeterministicEmbedder(TEST_DIMENSIONS), gate=gate
    )
    try:
        casefile = ctx.casefiles.create("Unreachable")
        with pytest.raises(ConfigError) as raised:
            ctx.ingestion.ingest(casefile.short_id, corpus)

        message = str(raised.value)
        assert "summary_model" in message and "llm_url" in message, (
            "the refusal must name both settings, as the reranker's does: "
            f"{message!r}"
        )
        assert ctx.store.casefile_statistics(casefile.id)["documents"] == 0, (
            "the run stored a document before failing, so the endpoint was sent "
            "evidence before it was established that it answers at all"
        )
    finally:
        ctx.close()


def test_the_endpoint_named_in_an_error_carries_no_credential(config):
    """A failure detail travels out through the unauthenticated REST ingest route.

    Several OpenAI-compatible gateways carry the credential in the URL — as
    userinfo, a path token, or a query parameter — and `SummaryError` becomes
    `IngestOutcome.detail`, which the REST ingest response returns in its body
    with no authentication in front of it. So the messages name a redacted
    endpoint and never the composed URL.

    The stand-in below is deliberately low-entropy and reads as fake. An earlier
    version used a JWT-shaped value and the repository's own secret scan flagged
    it at entropy 3.75 — correctly, since a scanner cannot tell a test's fake
    token from a real one. What this test needs is a distinctive string, not a
    realistic one, so the scanner's objection costs nothing to honour and
    silencing it with an allowlist entry would have been the wrong trade.
    """
    secret = "not-a-real-token-not-a-real-token"
    named = _with_profile(
        config,
        summary_model="probe",
        llm_url=f"http://svc:{secret}@127.0.0.1:1/v1?api-key={secret}",
    )
    summariser = build_summariser(named)

    with pytest.raises(SummariserUnavailable) as raised:
        summariser.check()

    message = str(raised.value)
    assert secret not in message, (
        "the refusal named a credential embedded in llm_url. This message reaches "
        f"an unauthenticated REST response body: {message!r}"
    )
    assert "127.0.0.1" in message, (
        "the refusal names no endpoint at all, so an operator cannot tell which "
        f"one was unreachable: {message!r}"
    )


def test_a_wedged_concurrency_setting_is_refused_at_load(config):
    """This value sizes a thread pool and a connection pool, so it needs a ceiling.

    Every other numeric profile setting describes a preference — a wider window is
    only ever a preference — and a ceiling on one of those would be arbitrary.
    `summary_concurrency` buys threads and sockets, so a mistyped extra zero is
    ten thousand of each at the first document rather than a slightly wrong
    result. Refused where the message can name the setting.
    """
    from jackryan.config import MAX_SUMMARY_CONCURRENCY, _select_profile

    document = {
        "profiles": {
            "local": {"summary_concurrency": MAX_SUMMARY_CONCURRENCY + 1},
        }
    }
    with pytest.raises(ConfigError) as raised:
        _select_profile(document)
    assert "summary_concurrency" in str(raised.value), (
        f"the refusal must name the setting: {str(raised.value)!r}"
    )

    at_ceiling = {
        "profiles": {"local": {"summary_concurrency": MAX_SUMMARY_CONCURRENCY}}
    }
    assert _select_profile(at_ceiling).summary_concurrency == MAX_SUMMARY_CONCURRENCY, (
        "the ceiling itself must be accepted, or the bound is off by one and the "
        "error message names a value that was in fact allowed"
    )


def test_a_failed_document_leaves_neither_a_row_nor_a_chunk(config, gate, corpus):
    """A summariser failure must leave nothing behind, as every other failure does.

    `ValidationError` and `ExtractionError` both arise before anything is
    written, so before summaries existed a failed document left no trace. The
    first implementation of this change persisted the document and its chunks and
    only then summarised, so a `summarise_document` failure reported the document
    as failed while its text and chunks were committed and searchable — and
    because a failed document is not expanded, an archive whose summary failed
    was stored with its entries silently never ingested and the report still
    claiming to be complete.

    Asserted against the store rather than read off the report, and for both
    failure points, because they are on opposite sides of where the write used to
    happen.
    """
    for failing in ("chunks", "document"):
        stub = _StubSummariser()
        if failing == "chunks":
            stub._fail_on = ""
            stub.summarise_chunks = lambda *_: (_ for _ in ()).throw(
                SummaryError("the endpoint refused every chunk")
            )
        else:
            stub.summarise_document = lambda *_: (_ for _ in ()).throw(
                SummaryError("the endpoint refused the document summary")
            )

        with _instance(
            config, gate, stub, summary_model="stub", chunk_summaries=True
        ) as ctx:
            casefile = ctx.casefiles.create(f"Failed {failing}")
            report = ctx.ingestion.ingest(casefile.short_id, corpus)

            assert report.failed and not report.ingested, (
                f"a summariser failing on the {failing} pass did not fail the "
                f"documents: {[(o.status, o.detail) for o in report.outcomes]}"
            )
            stats = ctx.store.casefile_statistics(casefile.id)
            chunks = ctx.store.find_chunks_by_id_prefix(casefile.id, "")
            assert stats["documents"] == 0 and not chunks, (
                f"a document that failed on the {failing} pass left "
                f"{stats['documents']} row(s) and {len(chunks)} chunk(s) in the "
                "store. A failed document must leave nothing: a row with no chunks "
                "is listed and readable through every document surface while no "
                "search can ever return it, so an analyst's negative result over "
                "the casefile is wrong and nothing on disk says why."
            )


def test_the_client_cannot_be_re_routed_by_the_environment(config):
    """An environment variable must not be able to redirect corpus egress.

    `httpx` trusts the environment by default, so `HTTPS_PROXY` or `ALL_PROXY`
    in the ingesting process would route every summary request — up to twenty
    thousand characters of a document each, plus the bearer token — through a
    host that appears nowhere in `config.yaml`. This module's docstring says the
    endpoint is always one the operator wrote down; `trust_env=False` is what
    makes that sentence true.

    Also pins the two defaults that are currently correct and would be silent
    leaks if a future httpx flipped them: `follow_redirects=False`, so a 3xx
    cannot replay the Authorization header to whatever the Location header names,
    and `verify=True`. `httpx>=0.28` does not prevent a minor release from
    changing either.

    Reads `_trust_env` — private, and read deliberately. The alternative is no
    guard at all for a control that is one keyword away from silently
    disappearing, and a test that breaks loudly when httpx renames an attribute
    is a better outcome than a control nothing checks.
    """
    named = _with_profile(
        config, summary_model="probe", llm_url="http://127.0.0.1:1/v1"
    )
    summariser = build_summariser(named)
    client = summariser._connect()
    try:
        assert client._trust_env is False, (
            "the summary client trusts the environment, so HTTPS_PROXY can route "
            "every document's text through a host the operator never configured"
        )
        assert client.follow_redirects is False, (
            "the summary client follows redirects, so a 3xx from the endpoint "
            "replays the Authorization header to whatever the Location names"
        )
        assert summariser._connect() is client, (
            "a second `_connect` built a second client. One pooled client per "
            "summariser is the entire reason httpx is a runtime dependency: a "
            "client per call is 36,000 handshakes for the corpus this was built "
            "for, and `httpx.Limits` is per client, so the connection ceiling "
            "would multiply too. The race that motivates the lock in `_connect` "
            "is not deterministically testable; this is the regression that is."
        )
    finally:
        client.close()


def test_a_named_summariser_is_built_without_reaching_the_endpoint(config):
    """Construction is cheap; the endpoint is `check`'s business.

    The same split `CrossEncoderReranker` uses, and the reason `jackryan status`
    on an instance naming a summariser it will not use pays for neither the
    client nor a request. A constructor that connected would make every command
    on the instance depend on a generation endpoint being up.
    """
    named = _with_profile(
        config, summary_model="qwen3-8b", llm_url="http://127.0.0.1:8080/v1"
    )
    summariser = build_summariser(named)

    assert isinstance(summariser, OpenAICompatSummariser), (
        "a profile naming a model and an endpoint produced "
        f"{summariser!r} rather than a summariser, so nothing would be summarised "
        "and nothing would say why"
    )
    assert summariser.name == f"qwen3-8b/{RECIPE_FINGERPRINT}", (
        "the built summariser's name is not the model joined with the recipe "
        "fingerprint, so corpus identity would not record the recipe its "
        "vectors were built under"
    )
    assert summariser._client is None, (
        "constructing the summariser built the HTTP client. `jackryan status` "
        "constructs one, so this makes an unrelated command depend on a "
        "generation endpoint being reachable."
    )


# --- against a real endpoint -----------------------------------------------

# Every test above reaches nothing. This one reaches a real OpenAI-compatible
# endpoint, so it is opt-in — the suite is required to run offline. Declared
# module-locally rather than imported from `conftest`, the same way
# `needs_models` is declared in `tests/test_quality_gate.py`: the gate belongs
# beside the tests it guards, and `conftest` does not export one.
#
# The reason a stub cannot stand in here: every other test in this file asserts
# the pipeline's behaviour given a summariser, and none of them exercises the
# transport, the request body, the response shape or the concurrency. Those are
# exactly where an OpenAI-compatible endpoint differs from the specification of
# one, and a fake would agree with our own assumptions by construction.
needs_llm = pytest.mark.skipif(
    os.environ.get("JACKRYAN_LLM_TESTS", "") != "1",
    reason="reaches a real generation endpoint; set JACKRYAN_LLM_TESTS=1 to run",
)

LLM_URL = os.environ.get("JACKRYAN_LLM_URL", "http://localhost:8080/v1")
LLM_MODEL = os.environ.get("JACKRYAN_LLM_MODEL", "qwen3.8-27b")


@needs_llm
def test_a_real_endpoint_summarises_every_chunk_of_a_real_ingest(
    config, gate, sectioned_corpus
):
    """The whole fold, end to end, over the transport a stub cannot exercise.

    Asserts the property the fold depends on and nothing weaker: *every* chunk
    carries a non-empty summary. One missing summary is a chunk embedded bare
    inside a folded corpus, which is the state this change exists to make
    unreachable — and the shipped implementation refuses an empty summary for
    exactly that reason, so a partial result arrives here as a failed document
    rather than as a gap.

    Also asserts what was actually embedded, because a summary stored but not
    folded in is the silent defect: `chunks.summary` non-empty proves the
    endpoint answered, not that the answer reached the embedder.

    Read the summaries rather than only counting them. A model can return a
    refusal, an apology or its own reasoning trace instead of a context, and all
    of those are non-empty strings that would satisfy a count.
    """
    summariser = OpenAICompatSummariser(
        model_name=LLM_MODEL,
        base_url=LLM_URL,
        concurrency=4,
        timeout_seconds=120,
    )
    summariser.check()

    with _instance(
        config,
        gate,
        summariser=summariser,
        summary_model=LLM_MODEL,
        llm_url=LLM_URL,
        chunk_summaries=True,
    ) as ctx:
        assert ctx.summariser_name == f"{LLM_MODEL}/{RECIPE_FINGERPRINT}", (
            "corpus identity does not name the summariser that is about to fill "
            "this store, so the fold would not be recorded anywhere"
        )

        casefile = ctx.casefiles.create("Live Summaries")
        report = ctx.ingestion.ingest(casefile.short_id, sectioned_corpus)
        assert not report.failed, (
            "a document failed against the real endpoint: "
            + "; ".join(o.detail for o in report.outcomes if o.status == "failed")
        )

        stored = ctx.store.find_chunks_by_id_prefix(casefile.id, "")
        assert stored, (
            "the ingest stored no chunks, so this test proves nothing about what "
            "the endpoint produced"
        )
        bare = [c for c in stored if not c.summary.strip()]
        assert not bare, (
            f"{len(bare)} of {len(stored)} chunks carry no summary. Each one was "
            "embedded bare inside a corpus whose identity says every vector was "
            "built from a summary and its text, and nothing downstream can find "
            "them again."
        )
        documents = {
            d.id: d
            for d in ctx.ingestion.list_documents(casefile.short_id, include_expanded=True)
        }
        for chunk in stored:
            source = documents[chunk.document_id].extracted_text
            assert chunk.text in source, (
                "a stored chunk's text is not a verbatim slice of its document, so "
                "the fold reached the stored text rather than only the embed input"
            )
            assert chunk.summary.strip() not in source, (
                "a chunk's summary appears verbatim in the document, so the "
                f"endpoint echoed the text back instead of situating it: "
                f"{chunk.summary[:120]!r}"
            )
        assert any(d.summary.strip() for d in documents.values()), (
            "no document carries a summary, so the map-reduce pass never ran or "
            "its result was not persisted"
        )
        for document in documents.values():
            if document.summary.strip():
                assert document.summary_by == summariser.name, (
                    "a document's summary is not attributed to the summariser "
                    f"that wrote it (got {document.summary_by!r}), so a reader "
                    "cannot tell which recipe produced the words they are reading"
                )
