"""The embedder is a port; the deterministic implementation is a real embedder."""

from __future__ import annotations

import pytest

from jackryan.config import Config, Contract, Profile
from jackryan.embedding import build_embedder
from jackryan.embedding.deterministic import DeterministicEmbedder
from jackryan.embedding.model import ModelEmbedder
from jackryan.embedding.port import EmbeddingError


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
