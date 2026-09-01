"""The embedder is a port; the deterministic implementation is a real embedder."""

from __future__ import annotations

from dataclasses import replace

import pytest

from jackryan.app import build_context
from jackryan.config import Config, Contract, Profile
from jackryan.embedding import build_embedder
from jackryan.embedding.deterministic import DeterministicEmbedder
from jackryan.embedding.model import ModelEmbedder
from jackryan.embedding.port import EmbeddingError
from jackryan.ingestion.chunker import chunk_text


def dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def test_identical_text_gives_identical_vectors():
    e = DeterministicEmbedder(128)
    assert e.embed_query("harbour lease") == e.embed_query("harbour lease")


def test_shared_vocabulary_is_more_similar_than_none():
    e = DeterministicEmbedder(512)
    base = e.embed_query("harbour lease northgate holdings")
    related = e.embed_query("harbour lease awarded northgate")
    unrelated = e.embed_query("baking bread grinding coffee")
    assert dot(base, related) > dot(base, unrelated)


def test_every_vector_has_the_declared_width():
    e = DeterministicEmbedder(97)
    assert len(e.embed_query("anything")) == 97
    assert all(len(v) == 97 for v in e.embed_documents(["a", "b", "c"]))


def test_text_with_no_tokens_still_yields_a_correctly_sized_vector():
    e = DeterministicEmbedder(32)
    assert len(e.embed_query("   !!!   ")) == 32


def test_dimensions_must_be_positive():
    with pytest.raises(ValueError):
        DeterministicEmbedder(0)


def build_config(embedder: str) -> Config:
    return Config(
        contract=Contract(embed_dimensions=64, embed_model="some/model"),
        profile=Profile(name="p", embedder=embedder),
        data_dir=__import__("pathlib").Path("/tmp/jr-embedder-test"),
    )


def test_the_profile_chooses_the_implementation():
    assert isinstance(build_embedder(build_config("deterministic")), DeterministicEmbedder)
    assert isinstance(build_embedder(build_config("model")), ModelEmbedder)


def test_the_deterministic_embedder_is_never_the_default():
    # Anything other than an explicit request yields the real implementation,
    # so an instance cannot silently store meaningless vectors.
    assert isinstance(build_embedder(build_config("model")), ModelEmbedder)


def test_an_unloadable_model_fails_loudly_with_no_fallback():
    embedder = ModelEmbedder(
        model_name="no/such-model-exists", dimensions=64, embed_library=Contract().embed_library
    )
    with pytest.raises(EmbeddingError) as exc:
        embedder.embed_query("anything")
    assert "no/such-model-exists" in str(exc.value)


def test_the_real_embedder_applies_asymmetric_prefixes(monkeypatch):
    seen: list[str] = []

    class FakeModel:
        def embed(self, texts):
            seen.extend(texts)
            return [[0.0] * 4 for _ in texts]

    embedder = ModelEmbedder(model_name="x", dimensions=4, embed_library=Contract().embed_library)
    monkeypatch.setattr(embedder, "_load", lambda: FakeModel())
    embedder.embed_documents(["a passage"])
    embedder.embed_query("a question")
    assert seen == ["passage: a passage", "query: a question"]


def test_a_mis_sized_embedding_is_refused(monkeypatch):
    class WrongWidth:
        def embed(self, texts):
            return [[0.0] * 9 for _ in texts]

    embedder = ModelEmbedder(model_name="x", dimensions=4, embed_library=Contract().embed_library)
    monkeypatch.setattr(embedder, "_load", lambda: WrongWidth())
    with pytest.raises(EmbeddingError, match="width 9"):
        embedder.embed_query("anything")


def test_an_embedder_refuses_a_library_version_that_is_not_installed():
    # The corpus records which library built its vectors. A different version of
    # the same library can return the declared width from the declared model and
    # still mean something else, so the embedder refuses before producing any.
    embedder = ModelEmbedder(
        model_name="x", dimensions=4, embed_library="fastembed==0.0.1-not-installed"
    )
    with pytest.raises(EmbeddingError) as exc:
        embedder.embed_query("anything")
    message = str(exc.value)
    assert "0.0.1-not-installed" in message, "the declared version must be named"
    assert "installed" in message


def test_the_library_check_names_a_distribution_that_is_absent():
    embedder = ModelEmbedder(
        model_name="x", dimensions=4, embed_library="no-such-distribution==1.0"
    )
    with pytest.raises(EmbeddingError, match="no-such-distribution"):
        embedder.embed_query("anything")


def test_a_malformed_library_declaration_is_refused():
    embedder = ModelEmbedder(model_name="x", dimensions=4, embed_library="fastembed")
    with pytest.raises(EmbeddingError, match="distribution.*version"):
        embedder.embed_query("anything")


# --- what reaches the embedder ---------------------------------------------


class _RecordingEmbedder(DeterministicEmbedder):
    """Records what ingestion hands the embedder, then embeds normally.

    Subclassing rather than wrapping keeps `name = "deterministic"`, so corpus
    identity is the one the fixture's config already describes and the store is
    not refused.
    """

    def __init__(self, dimensions: int) -> None:
        super().__init__(dimensions)
        self.seen: list[list[str]] = []

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self.seen.append(list(texts))
        return super().embed_documents(texts)


def test_what_reaches_the_embedder_is_the_chunks_own_text(config, gate, sectioned_corpus):
    """With the fold switched off, the embedder is given the chunk and nothing else.

    This is the folding-off branch, and it is what every instance that has not
    deliberately turned the fold on must do. `chunk_summaries` is false by
    default, so this assertion is byte-for-byte the one this test made before
    summaries existed. The folding-on branch is the sibling test below, which
    asserts the other half: what the embedder is given with the switch on is
    exactly the stored summary joined to the stored text.

    A setting that changes the bytes handed to the embedder is corpus-coupled.
    The heading path is computed and stored without being embedded, and a
    per-chunk summary can now be folded in. Either one folded in here produces
    vectors of the declared width that mean something else, appended to a corpus
    whose identity does not change. Nothing downstream can detect that, so this
    test is the detection: it fails on the day something is folded in without
    the switch and without entering corpus identity.

    Two oracles, because one of them alone has a blind spot. The multiset
    comparison recomputes the expectation with `chunk_text`, which catches
    anything folded in between the chunker and the embed call — but it is the
    same call the pipeline makes, so a fold applied *inside* the chunker moves
    both sides together and the comparison stays green. That is exactly where
    the heading path would be folded in, since the chunker is what computes it.
    So the second oracle does not route through `chunk_text` at all: a chunk's
    text is a verbatim slice of the document's extracted text, so every text the
    embedder was handed must appear in some document's extracted text. That is
    false for anything prepended or appended, wherever in the pipeline it was
    inserted.

    Neither oracle reads the stored chunk texts, which would compare the
    pipeline with itself and pass on any transformation applied before both the
    store write and the embed call. The folding-on branch does read them, and
    its docstring says why that is not the same mistake.
    """
    embedder = _RecordingEmbedder(config.contract.embed_dimensions)
    ctx = build_context(config, embedder=embedder, gate=gate)
    try:
        casefile = ctx.casefiles.create("Embed Input")
        report = ctx.ingestion.ingest(casefile.short_id, sectioned_corpus)
        assert not report.failed

        expected: list[str] = []
        headed = 0
        # `include_expanded=True`: expansions out of a container are chunked and
        # embedded like anything else, so the default would compare a subset of
        # the documents against all of the recorded texts and fail for a reason
        # that has nothing to do with the rule this test defends.
        documents = ctx.ingestion.list_documents(casefile.short_id, include_expanded=True)
        for document in documents:
            for piece in chunk_text(
                document.extracted_text,
                max_chars=config.contract.chunk_max_chars,
                overlap_chars=config.contract.chunk_overlap_chars,
            ):
                expected.append(piece.text)
                headed += bool(piece.heading_path)

        recorded = [text for call in embedder.seen for text in call]

        assert recorded, (
            "nothing was handed to the embedder, so this test proves nothing about "
            "what reaches it"
        )
        assert headed, (
            "no chunk in this corpus carries a heading path, so the corpus cannot "
            "show that the heading path is not folded into what is embedded — use a "
            "fixture whose documents have headings"
        )
        # The oracle that does not route through the chunker.
        sources = [document.extracted_text for document in documents]
        for text in recorded:
            assert text and any(text in source for source in sources), (
                "a text handed to the embedder is not a verbatim slice of any "
                "document's extracted text, so something was folded into it "
                f"before it was embedded: {text[:120]!r}"
            )
        # Sorted multisets, not positional: ingestion runs in a thread pool, so
        # the order of per-document embed calls is not guaranteed. Equality still
        # fails on any prefix, suffix or substitution, which is the assertion.
        assert sorted(recorded) == sorted(expected), (
            "what reaches the embedder must be the chunk's own text and nothing "
            "else — no heading path, no summary, no other context. Folding "
            "anything in changes what the vector means while leaving its width "
            "and corpus identity untouched, so it is corpus-coupled and whatever "
            "turns it on has to enter corpus identity — by composition, which is "
            "what `chunk_summaries` and the summariser's name now do in "
            "`build_context`. This test runs with the fold switched off, so a fold "
            "appearing here is a defect and not a feature: something is folding "
            "context in without entering identity, which is a corpus of mixed "
            "vectors under one fingerprint. Make the fold enter corpus identity, "
            "or remove it. Never update this test."
        )
    finally:
        ctx.close()


# --- what reaches the embedder once the fold is on --------------------------


class _StubSummariser:
    """A summariser that writes a predictable context, with no endpoint.

    Local to this file rather than shared, for the reason `_RecordingEmbedder`
    above is: a test double belongs beside the test whose oracle depends on
    exactly what it returns.

    Predictable rather than constant. The context it returns is derived from the
    chunk it was given, so a fold that pairs one chunk's context with another
    chunk's text shows up in the failure instead of being hidden by every
    summary being the same string.
    """

    def __init__(self, name: str = "stub/000000000000") -> None:
        self.name = name
        self.checked = 0
        self.documents: list[str] = []

    def check(self) -> None:
        self.checked += 1

    def summarise_chunks(self, document_text: str, chunk_texts):
        return [f"context for {t[:20]}" for t in chunk_texts]

    def summarise_document(self, chunk_summaries) -> str:
        self.documents.append("|".join(chunk_summaries))
        return f"document summary from {len(chunk_summaries)} notes"


def _with_folding(config: Config) -> Config:
    """The same configuration with the fold on, built rather than mutated.

    `Config` and `Profile` are frozen, so this leaves the fixture's own object
    untouched for every other test in the run.
    """
    return replace(
        config,
        profile=replace(config.profile, summary_model="stub", chunk_summaries=True),
    )


def test_what_reaches_the_embedder_with_the_fold_on_is_the_summary_and_the_text(
    config, gate, sectioned_corpus
):
    """With the fold on, the embedder is given the stored summary joined to the stored text.

    The folding-on branch of the test above, and the two have to be read
    together. That one says the fold is absent while the switch is off; this one
    says exactly what the fold is once the switch is on. A change that folded
    something in and recorded nothing fails that test. A change that folded
    something other than the summary it recorded fails this one.

    The oracle reads the chunks back from the store, which the folding-off
    branch deliberately refuses to do. The difference is the point rather than
    an inconsistency. There, the store would be comparing the pipeline with
    itself: the stored text and the embedded text come from one expression, so a
    transformation applied before both moves both sides together and the
    comparison stays green. Here they are two different expressions on adjacent
    lines of `_rebuild_chunks` — the summary travels to `replace_chunks` on the
    `Chunk`, the embed input is built by a separate comprehension — so the two
    can disagree, which makes `chunks.summary` an independent record of what was
    folded in rather than a second copy of it. It is also the only record: the
    stored `text` is by design the chunk's own text, so nothing else on disk
    says what the vector was built from.

    The asymmetry asserted below is the whole corpus-coupling argument in one
    place. Every stored chunk text is still a verbatim slice of its document,
    and no text the embedder was given is. The store holds the document's words;
    the vector was built from more. That is why a folded corpus and a bare one
    cannot be told apart by their stored text and have to be told apart by
    corpus identity instead.
    """
    summariser = _StubSummariser()
    embedder = _RecordingEmbedder(config.contract.embed_dimensions)
    ctx = build_context(
        _with_folding(config), embedder=embedder, gate=gate, summariser=summariser
    )
    try:
        casefile = ctx.casefiles.create("Folded Embed Input")
        report = ctx.ingestion.ingest(casefile.short_id, sectioned_corpus)
        assert not report.failed

        recorded = [text for call in embedder.seen for text in call]
        # Every chunk in the casefile: an empty prefix is `LIKE '%'`. Read through
        # the port rather than the connection, so this asserts what a reader of
        # the store would see.
        stored = ctx.store.find_chunks_by_id_prefix(casefile.id, "")

        assert recorded, (
            "nothing was handed to the embedder, so this test proves nothing about "
            "what reaches it"
        )
        assert any(chunk.summary for chunk in stored), (
            "no stored chunk carries a summary, so nothing was folded and every "
            "assertion below holds vacuously — a folding-on test that folded "
            "nothing proves nothing. Check that the stub is wired through "
            "`build_context` and that `chunk_summaries` reached `IngestionService`"
        )

        # `include_expanded=True` for the reason the folding-off branch gives:
        # an expansion is chunked and embedded like anything else.
        documents = ctx.ingestion.list_documents(casefile.short_id, include_expanded=True)
        sources = [document.extracted_text for document in documents]
        by_document = {document.id: document.extracted_text for document in documents}

        # Half one of the asymmetry: the store still holds the document's words.
        for chunk in stored:
            assert chunk.text and chunk.text in by_document.get(chunk.document_id, ""), (
                "a stored chunk's text is not a verbatim slice of its own document's "
                "extracted text, so the fold reached the stored text as well as the "
                "embed input. `chunks.text` must stay the chunk's own words — a "
                "folded corpus and a bare one differ in their vectors and in nothing "
                "else, which is the difference corpus identity exists to record. Fix "
                "`_rebuild_chunks` so that only the embed input carries the summary. "
                f"Offending chunk: {chunk.short_id}"
            )
        # Half two: what was embedded is not those words. This is the assertion
        # that catches storing the summary and embedding the bare chunk.
        for text in recorded:
            assert not any(text in source for source in sources), (
                "a text handed to the embedder is a verbatim slice of a document's "
                "extracted text, so nothing was folded into it. With "
                "`chunk_summaries` on, the embed input must be the chunk's summary "
                "joined to its text. Recording the summary and embedding the bare "
                "chunk is the silent defect this test exists to catch: the store "
                "describes a fold the vectors were not built from, under an identity "
                "that says they were, and no later check can find the disagreement. "
                f"Offending text: {text[:120]!r}"
            )

        # Sorted multisets for the reason the folding-off branch gives: ingestion
        # runs in a thread pool, so the order of per-document embed calls is not
        # guaranteed. Equality still fails on any prefix, suffix or substitution.
        expected = [f"{chunk.summary}\n\n{chunk.text}" for chunk in stored]
        assert sorted(recorded) == sorted(expected), (
            "with the fold on, what reaches the embedder must be exactly the "
            "chunk's stored summary, a blank line, and the chunk's stored text — "
            "for every chunk, and not for some of them. One chunk folded while its "
            "neighbour is embedded bare puts two kinds of vector inside a single "
            "document, where no corpus identity check can reach the difference. "
            "Compare `_rebuild_chunks`'s embed input against the chunks it hands "
            "`replace_chunks`: the two must differ by the summary and by nothing "
            "else."
        )

        # The pairing, which none of the assertions above can see. Each of them
        # compares the embed input against `chunks.summary` — and a mispaired
        # summary is what gets *stored*, so both sides of every comparison move
        # together and the multiset stays equal. `summarising/port.py` names this
        # exactly: "a reordering pairs one chunk's context with another chunk's
        # text and nothing stored afterwards would say so".
        #
        # The stub's output is derived from the chunk it was given, which is what
        # makes the pairing checkable at all: recomputing it here is an oracle
        # outside the pipeline rather than a reading of the pipeline's own record.
        for chunk in stored:
            assert chunk.summary == f"context for {chunk.text[:20]}", (
                "a chunk carries a summary derived from a different chunk, so the "
                "fold paired one chunk's context with another chunk's text. Under a "
                "real summariser that produces vectors of the declared width, from "
                "the declared model, under a correct corpus identity, and meaning "
                "something other than what they claim — the failure class this "
                "whole change is built to prevent, and the one thing no later check "
                "can detect. `_rebuild_chunks` must zip the summaries onto the "
                "chunks in the order the summariser was given them. "
                f"Chunk {chunk.short_id} text={chunk.text[:40]!r} "
                f"summary={chunk.summary[:60]!r}"
            )
    finally:
        ctx.close()


def test_the_switch_alone_folds_nothing_when_no_summariser_is_configured(
    config, gate, sectioned_corpus
):
    """The switch on its own folds nothing, and leaves corpus identity alone.

    `build_context` computes `folding = chunk_summaries and summariser is not
    None`, and this pins that conjunction. Each half matters on its own: a
    `folding` taken from the switch alone would call `summarise_chunks` on
    `None`, and one taken from the summariser alone would fold for every
    instance that names a model only to get per-document summaries.

    The loader refuses this combination — `chunk_summaries: true` with an empty
    `summary_model` is fatal — so the only way to reach it is the injection seam,
    which is the seam worth pinning: the composition root has to hold the
    conjunction whether or not the loader ran.

    Deliberately not a second copy of the folding-off branch. That test owns
    detecting a fold against the chunker's own output. This one asserts that
    nothing was folded, that nothing was recorded as folded, and that corpus
    identity is untouched — because an instance in this state must still open a
    corpus written before summaries existed.
    """
    switched_on = replace(config, profile=replace(config.profile, chunk_summaries=True))
    embedder = _RecordingEmbedder(config.contract.embed_dimensions)
    ctx = build_context(switched_on, embedder=embedder, gate=gate, summariser=None)
    try:
        casefile = ctx.casefiles.create("Switch Without Summariser")
        report = ctx.ingestion.ingest(casefile.short_id, sectioned_corpus)
        assert not report.failed

        recorded = [text for call in embedder.seen for text in call]
        stored = ctx.store.find_chunks_by_id_prefix(casefile.id, "")
        assert recorded, (
            "nothing was handed to the embedder, so this test proves nothing about "
            "what reaches it"
        )
        assert stored, (
            "no chunk was stored, so an empty `summary` on every stored chunk below "
            "proves nothing"
        )

        sources = [
            document.extracted_text
            for document in ctx.ingestion.list_documents(
                casefile.short_id, include_expanded=True
            )
        ]
        for text in recorded:
            assert text and any(text in source for source in sources), (
                "the switch is on and no summariser was given, so there is nothing "
                "to fold — yet a text handed to the embedder is not a verbatim slice "
                "of any document. `folding` must be the conjunction of the switch "
                "and a summariser being present, not the switch alone. Offending "
                f"text: {text[:120]!r}"
            )
        assert not any(chunk.summary for chunk in stored), (
            "a stored chunk records a folded summary although no summariser was "
            "configured, so something wrote `chunks.summary` from the switch alone"
        )
        assert ctx.summariser_name == "", (
            "corpus identity gained a summariser component with no summariser "
            "configured, which would refuse every corpus written before summaries "
            "existed — for a fold that did not happen"
        )
    finally:
        ctx.close()
