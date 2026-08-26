"""The store guards corpus identity: a contract change must not silently
append to a corpus built under different rules."""

from __future__ import annotations

import pytest

from jackryan.errors import ConfigError
from jackryan.storage.sqlite import SqliteStore


def test_reopening_with_the_same_contract_succeeds(tmp_path):
    path = tmp_path / "store.db"
    first = SqliteStore(path)
    first.initialize("contract-a", 8)
    first.close()

    second = SqliteStore(path)
    second.initialize("contract-a", 8)
    second.close()


def test_reopening_under_a_different_contract_is_fatal(tmp_path):
    path = tmp_path / "store.db"
    first = SqliteStore(path)
    first.initialize("contract-a", 8)
    first.close()

    second = SqliteStore(path)
    with pytest.raises(ConfigError, match="only appendable"):
        second.initialize("contract-b", 8)


def test_initialize_creates_missing_parent_directories(tmp_path):
    store = SqliteStore(tmp_path / "nested" / "deeper" / "store.db")
    store.initialize("contract-a", 8)
    assert (tmp_path / "nested" / "deeper" / "store.db").exists()
    store.close()


def test_using_the_store_before_initialize_is_an_error(tmp_path):
    store = SqliteStore(tmp_path / "store.db")
    with pytest.raises(RuntimeError, match="before initialize"):
        store.list_casefiles()


# -- M1: documents, chunks, and the single-transaction guarantee ----------

import uuid
from datetime import datetime, timezone

from jackryan.storage.port import Chunk, Document


def make_store(tmp_path, dimensions=8):
    store = SqliteStore(tmp_path / "store.db")
    store.initialize("contract-a", dimensions)
    return store


def make_casefile(store):
    from jackryan.storage.port import Casefile

    now = datetime.now(timezone.utc)
    casefile = Casefile(
        id=uuid.uuid4().hex, slug="case", title="Case", description="",
        created_at=now, updated_at=now,
    )
    return store.create_casefile(casefile)


def make_document(store, casefile, content_hash="hash-1"):
    now = datetime.now(timezone.utc)
    return store.upsert_document(
        Document(
            id=uuid.uuid4().hex, casefile_id=casefile.id, content_hash=content_hash,
            filename="a.txt", media_type="text/plain", byte_size=10,
            extracted_text="some text", extractor="plaintext",
            created_at=now, updated_at=now,
        )
    )


def make_chunk(document, casefile, ordinal=0, text="chunk text"):
    return Chunk(
        id=uuid.uuid4().hex, document_id=document.id, casefile_id=casefile.id,
        ordinal=ordinal, heading_path="", text=text, char_start=0, char_end=len(text),
    )


def test_an_embedding_of_the_wrong_width_is_refused(tmp_path):
    store = make_store(tmp_path, dimensions=8)
    casefile = make_casefile(store)
    document = make_document(store, casefile)
    chunk = make_chunk(document, casefile)
    with pytest.raises(ConfigError, match="width 3"):
        store.replace_chunks(document.id, [chunk], [[0.1, 0.2, 0.3]])
    store.close()


def test_a_failed_chunk_write_leaves_nothing_behind(tmp_path):
    store = make_store(tmp_path, dimensions=4)
    casefile = make_casefile(store)
    document = make_document(store, casefile)

    good = make_chunk(document, casefile, 0, "first")
    # A duplicate id makes the second insert fail partway through the batch.
    duplicate = Chunk(
        id=good.id, document_id=document.id, casefile_id=casefile.id, ordinal=1,
        heading_path="", text="second", char_start=0, char_end=6,
    )
    with pytest.raises(Exception):
        store.replace_chunks(document.id, [good, duplicate], [[0.0] * 4, [0.0] * 4])

    assert store.search_keyword(casefile.id, "first", 10) == []
    assert store.search_vector(casefile.id, [0.0] * 4, 10) == []
    store.close()


def test_replacing_chunks_removes_the_previous_ones(tmp_path):
    store = make_store(tmp_path, dimensions=4)
    casefile = make_casefile(store)
    document = make_document(store, casefile)

    store.replace_chunks(document.id, [make_chunk(document, casefile, 0, "aardvark")], [[1.0, 0, 0, 0]])
    assert store.search_keyword(casefile.id, "aardvark", 10)

    store.replace_chunks(document.id, [make_chunk(document, casefile, 0, "buffalo")], [[0, 1.0, 0, 0]])
    assert store.search_keyword(casefile.id, "aardvark", 10) == []
    assert store.search_keyword(casefile.id, "buffalo", 10)
    store.close()


def test_deleting_a_casefile_takes_its_documents_and_chunks(tmp_path):
    store = make_store(tmp_path, dimensions=4)
    casefile = make_casefile(store)
    document = make_document(store, casefile)
    store.replace_chunks(document.id, [make_chunk(document, casefile, 0, "aardvark")], [[1.0, 0, 0, 0]])

    store.delete_casefile(casefile.id)
    assert store.get_document(document.id) is None
    assert store.list_documents(casefile.id) == []
    store.close()


def test_the_same_hash_in_one_casefile_reuses_the_row(tmp_path):
    store = make_store(tmp_path, dimensions=4)
    casefile = make_casefile(store)
    first = make_document(store, casefile, content_hash="same")
    second = make_document(store, casefile, content_hash="same")
    assert first.id == second.id
    assert len(store.list_documents(casefile.id)) == 1
    store.close()


def test_a_corpus_built_under_one_embedding_library_is_refused_under_another(tmp_path):
    """The end-to-end shape of the defect, through real fingerprints.

    Two contracts that differ only in the embedding library version. Before that
    value entered the fingerprint these produced the same string, so the store
    opened a mean-pooled corpus under a CLS-pooled configuration and appended to
    it — vectors of the right width that mean something else, which no later
    check can detect.
    """
    from jackryan.config import Contract

    built_under = Contract(embed_library="fastembed==0.5.1")
    opened_under = Contract(embed_library="fastembed==0.8.0")
    assert built_under.fingerprint() != opened_under.fingerprint()

    path = tmp_path / "corpus.db"
    first = SqliteStore(path)
    first.initialize(built_under.fingerprint(), built_under.embed_dimensions)
    first.close()

    second = SqliteStore(path)
    with pytest.raises(ConfigError):
        second.initialize(opened_under.fingerprint(), opened_under.embed_dimensions)
    second.close()


def test_a_deterministic_corpus_is_refused_by_a_real_model_configuration(tmp_path):
    """The defect this change closes, end to end through build_context.

    One data directory. Fill it under the deterministic embedder, then open it
    under the model embedder. Before this change both produced the same
    fingerprint, the store opened, and real e5 query vectors were cosine-compared
    against blake2b hash vectors of the same width — nothing downstream can tell
    those apart, so this refusal is the last point the difference is visible.
    """
    import pytest

    from jackryan.app import build_context
    from jackryan.config import Config, Contract, Profile
    from jackryan.errors import ConfigError

    def config_for(embedder: str) -> Config:
        return Config(
            contract=Contract(),
            profile=Profile(name="p", embedder=embedder),
            data_dir=tmp_path,
        )

    filled = build_context(config_for("deterministic"))
    filled.casefiles.create("Some Casefile")
    filled.close()

    with pytest.raises(ConfigError) as exc:
        build_context(config_for("model"))
    message = str(exc.value)
    assert "deterministic" in message, "the refusal must name what filled the store"
    assert "model" in message, "the refusal must name what tried to open it"


def test_the_same_embedder_still_reopens(tmp_path):
    # The guard must refuse a different embedder, not everything.
    from jackryan.app import build_context
    from jackryan.config import Config, Contract, Profile

    def config_for(embedder: str) -> Config:
        return Config(
            contract=Contract(),
            profile=Profile(name="p", embedder=embedder),
            data_dir=tmp_path,
        )

    first = build_context(config_for("deterministic"))
    first.casefiles.create("Some Casefile")
    first.close()

    second = build_context(config_for("deterministic"))
    assert len(second.casefiles.list()) == 1
    second.close()


def test_the_reported_identity_is_the_one_the_store_enforces(tmp_path):
    # Reporting a value that guards nothing leaves an operator comparing the
    # wrong string against a refusal they are trying to explain.
    from jackryan.app import build_context
    from jackryan.config import Config, Contract, Profile, corpus_fingerprint

    config = Config(
        contract=Contract(),
        profile=Profile(name="p", embedder="deterministic"),
        data_dir=tmp_path,
    )
    context = build_context(config)
    try:
        assert context.corpus_fingerprint == corpus_fingerprint(
            config.contract, context.embedder.name
        )
    finally:
        context.close()
