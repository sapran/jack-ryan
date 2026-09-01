"""The embedder is a port; the deterministic implementation is a real embedder."""

from __future__ import annotations

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
    """A setting that changes the bytes handed to the embedder is corpus-coupled.

    Contextual retrieval — folding a per-chunk summary into the text before
    embedding it — is deferred to M3, and the heading path is already computed
    and stored without being embedded. Either one folded in produces vectors of
    the declared width that mean something else, appended to a corpus whose
    identity does not change. Nothing downstream can detect that, so this test
    is the detection: it fails on the day the folding-in happens, and the fix is
    to declare the setting in the contract, not to update the test.

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
    store write and the embed call.
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
            "and corpus identity untouched, so it is corpus-coupled and the "
            "setting that turns it on belongs in the contract. This test failing "
            "is the signal to declare that value, not to update the test."
        )
    finally:
        ctx.close()
