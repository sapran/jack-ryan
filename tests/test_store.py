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


def make_document(store, casefile, content_hash="hash-1", location="/dump/a.txt"):
    """A stored document and the place it was observed, which is one write.

    The location is not optional at this seam: whether a document's record may
    be read as whole is answered from it, so a fixture that stored a document
    without one would not be the state an ingest produces.
    """
    now = datetime.now(timezone.utc)
    return store.store_document(
        Document(
            id=uuid.uuid4().hex, casefile_id=casefile.id, content_hash=content_hash,
            filename="a.txt", media_type="text/plain", byte_size=10,
            extracted_text="some text", extractor="plaintext",
            created_at=now, updated_at=now,
        ),
        location,
        now,
    ).document


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
        store.replace_chunks(document.id, [chunk], [[0.1, 0.2, 0.3]], [])
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
        store.replace_chunks(document.id, [good, duplicate], [[0.0] * 4, [0.0] * 4], [])

    assert store.search_keyword(casefile.id, "first", 10) == []
    assert store.search_vector(casefile.id, [0.0] * 4, 10) == []
    store.close()


def test_replacing_chunks_removes_the_previous_ones(tmp_path):
    store = make_store(tmp_path, dimensions=4)
    casefile = make_casefile(store)
    document = make_document(store, casefile)

    store.replace_chunks(document.id, [make_chunk(document, casefile, 0, "aardvark")], [[1.0, 0, 0, 0]], [])
    assert store.search_keyword(casefile.id, "aardvark", 10)

    store.replace_chunks(document.id, [make_chunk(document, casefile, 0, "buffalo")], [[0, 1.0, 0, 0]], [])
    assert store.search_keyword(casefile.id, "aardvark", 10) == []
    assert store.search_keyword(casefile.id, "buffalo", 10)
    store.close()


def test_deleting_a_casefile_takes_its_documents_and_chunks(tmp_path):
    store = make_store(tmp_path, dimensions=4)
    casefile = make_casefile(store)
    document = make_document(store, casefile)
    store.replace_chunks(document.id, [make_chunk(document, casefile, 0, "aardvark")], [[1.0, 0, 0, 0]], [])

    store.delete_casefile(casefile.id)
    assert store.get_document(document.id) is None
    assert store.list_documents(casefile.id) == []
    store.close()


def test_deleting_a_casefile_deletes_its_ingest_records(tmp_path):
    """The cascade the step's comment claims, checked rather than trusted.

    The step adds no trigger, on the argument that `casefiles.id` is a real
    foreign-key parent and `PRAGMA foreign_keys=ON` is set in `initialize`.
    That argument is correct and it is also exactly the kind of claim that is
    silently wrong — the two sidecars next to it *do* need a trigger.
    """
    from jackryan.storage.port import Casefile, IngestRun

    store = make_store(tmp_path, dimensions=4)
    now = datetime.now(timezone.utc)

    def casefile_named(slug):
        return store.create_casefile(
            Casefile(
                id=uuid.uuid4().hex, slug=slug, title=slug.title(), description="",
                created_at=now, updated_at=now,
            )
        )

    doomed = casefile_named("doomed")
    kept = casefile_named("kept")

    for casefile in (doomed, kept):
        for _ in range(2):
            store.record_ingest_run(
                IngestRun(
                    id=uuid.uuid4().hex, casefile_id=casefile.id,
                    started_at=now, finished_at=now, documents_before=0,
                    documents_after=0,
                    items_ingested=1, items_failed=0, entries_refused=0,
                    files_without_extractor=0, exhausted_by="",
                )
            )
    assert store.ingestion_coverage(doomed.id).runs == 2
    assert store.ingestion_coverage(kept.id).runs == 2

    store.delete_casefile(doomed.id)

    assert store.ingestion_coverage(doomed.id).runs == 0
    assert store.ingestion_coverage(kept.id).runs == 2, (
        "deleting one casefile took another's records"
    )
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


# -- the seam itself: who may reach a store -------------------------------


#: Only these may name a store: the service layer, the storage package itself,
#: and the composition root that hands one to the other. Everything else in the
#: package — all three adapters, and every module below the service layer — is
#: checked. An exemption list rather than a list of adapters, so a fourth
#: adapter is covered on the day it is written rather than on the day someone
#: remembers to add it here.
_MAY_NAME_A_STORE = {"services", "storage", "app.py"}

#: `store` is the composition root's field; `_store` is the service layer's own.
#: Both are one attribute away from an adapter that holds a `Context` or a
#: service, and reaching either is the same breach.
_STORE_ATTRIBUTES = {"store", "_store"}


def test_no_adapter_reaches_the_store():
    """`storage-seam`: no adapter SHALL reach a store directly.

    Until this was written the agent surface did, at the one call
    `casefile_statistics`, which was the only port method no service wrapped.
    It type-checked because the composition root declared its `store` field as
    the concrete `SqliteStore` rather than as the port, and nothing in this
    repository type-checks anyway.

    Parsed rather than grepped for two reasons, and a third that sounds good and
    is false. The true ones: it reports `<any expr>.store`, not only the
    `context.store` spelling a search would be written for, and it cannot be
    tripped by the words appearing in a comment or a docstring — including this
    one. The false one, recorded because the first draft of this test asserted
    it: a search would *not* be defeated by binding the store to a name first,
    because `store = context.store` contains the very string being searched for.

    `_store` is checked beside `store` because it is the realistic evasion, not
    an exotic one. Every adapter already holds a `CasefileService`, whose
    `_store` is one attribute away — and reaching for it is exactly what someone
    writes when the service method they need does not exist yet, which is the
    situation that produced the original breach.

    What this does not catch, stated so nobody trusts it further than it goes: a
    module that imports `SqliteStore` and constructs one, or that reaches a
    store through a name this does not know. It catches the accident and the
    shortcut, not a determined evasion.
    """
    import ast
    from pathlib import Path

    package = Path(__file__).resolve().parents[1] / "src" / "jackryan"
    assert package.is_dir(), "the package moved; this guard now checks nothing"

    inspected, offences = set(), []
    for module in sorted(package.rglob("*.py")):
        relative = module.relative_to(package)
        if relative.parts[0] in _MAY_NAME_A_STORE:
            continue
        inspected.add(relative.as_posix())
        tree = ast.parse(module.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            reached = (
                isinstance(node, ast.Attribute) and node.attr in _STORE_ATTRIBUTES
            ) or (
                # `getattr(context, "store")` is the same reach spelled around
                # an attribute node.
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "getattr"
                and len(node.args) >= 2
                and isinstance(node.args[1], ast.Constant)
                and node.args[1].value in _STORE_ATTRIBUTES
            )
            if reached:
                offences.append(f"{relative.as_posix()}:{node.lineno}")

    # Named rather than counted. A floor on the number passes the exact
    # regression this widening exists to prevent: reverting the scan to
    # `interfaces/` alone still inspects eight modules, so any plausible count
    # would be satisfied while REST and the CLI went unguarded again.
    assert {"cli.py", "server.py"} <= inspected, (
        "the REST and CLI adapters were not inspected; the scan narrowed"
    )
    assert any(name.startswith("interfaces/") for name in inspected), (
        "the agent surface was not inspected; the scan narrowed"
    )
    assert not offences, (
        "a module outside the service layer reaches a store directly, which "
        "`storage-seam` forbids: " + ", ".join(sorted(set(offences)))
        + ". The rule belongs in the service layer so every adapter inherits it."
    )


# -- the seam's vocabulary: what a port method may hand back --------------


#: Containers with no field names of their own. A `tuple` is refused in every
#: form; a `dict` is refused unless it is a keyed batch of domain objects, for
#: which see below.
_UNNAMED_CONTAINERS = {"dict", "tuple"}

#: A floor, not the exact count, so removing a method does not fail this for
#: the wrong reason. It exists only to catch a walk that found nothing: 34
#: methods are declared today, and a scan that inspects fewer than this has
#: stopped reading the protocol rather than found it clean.
_FEWEST_PLAUSIBLE_PORT_METHODS = 25


def test_the_port_hands_back_named_values_never_tuples_or_rows():
    """The port speaks in domain objects: no method SHALL return a bare pair.

    `store_document` was the last one that did. It returned
    `tuple[Document, bool]`, and the boolean acquired its name — and therefore
    its meaning — only at the call site that unpacked it. A tuple's positions
    carry no names, so a same-type reordering changes what every caller is
    asserting while nothing fails; and `dict` returns are the same defect
    spelled differently, with the field names moved into strings where a typo
    is a runtime `KeyError` at best and a silently absent key at worst. Both
    are what `port.py`'s own opening paragraph means by "the port speaks in
    domain objects, never in rows".

    **A mapping of domain objects is not a row.** `get_chunks` returns
    `dict[str, Chunk]` — chunks keyed by their identifier, which is how a batch
    lookup answers, and every value is still a domain object with named fields.
    So `dict[K, V]` passes exactly when `V` is one of this module's own
    declared classes; `dict[str, str]` or `dict[str, Any]` does not. The
    allowed set is derived from `port.py`'s top-level classes rather than
    written out here, so a domain type added tomorrow needs no edit to this
    test.

    **The oracle is the declaration, not a call.** This parses the annotation
    in the source; it never constructs a store and never asks one what it
    returns. An implementation change therefore cannot move both sides of the
    assertion together, which is the failure that makes a guard agree with
    whatever the code now does. It also fails on a *new* method carrying the
    old shape, rather than only on the one this change fixed.

    **The walk asserts it was non-empty.** A guard that inspected nothing
    passes, and passing is exactly how it goes blind instead of red — renaming
    `StorePort`, or moving it to another module, would otherwise leave this
    reporting success over an empty list forever. So the protocol must be
    found, `store_document` must be among what was read, and the count must
    reach a plausible floor.

    What this does not catch, stated so nobody trusts it further than it goes.
    A method returning a `TypedDict` passes: the annotation is a class name and
    this reads names, not their definitions. A method returning a domain object
    that itself wraps an unnamed tuple passes — `IngestionCoverage` already
    holds a `tuple[str, ...]` field, legitimately, and nothing here inspects a
    returned type's own fields. So does an alias (`Pair = tuple[Document,
    bool]`) and the `typing.Tuple`/`typing.Dict` spellings, which this
    repository does not use. It catches the shape written at the seam, which is
    the shape a reader copies when adding the next method.
    """
    import ast
    from pathlib import Path

    port = Path(__file__).resolve().parents[1] / "src" / "jackryan" / "storage" / "port.py"
    assert port.is_file(), "port.py moved; this guard now checks nothing"

    module = ast.parse(port.read_text(encoding="utf-8"))
    protocol = next(
        (
            node
            for node in module.body
            if isinstance(node, ast.ClassDef) and node.name == "StorePort"
        ),
        None,
    )
    assert protocol is not None, (
        "StorePort was renamed or moved out of port.py; this guard inspected "
        "nothing, which is how it goes blind rather than red"
    )

    domain_types = {
        node.name
        for node in module.body
        if isinstance(node, ast.ClassDef) and node.name != protocol.name
    }

    def what_is_wrong_with(annotation) -> str:
        """Why this return annotation is unnamed, or empty if it is fine."""
        if isinstance(annotation, ast.Name) and annotation.id in _UNNAMED_CONTAINERS:
            return f"a bare `{annotation.id}`, which carries no field names at all"
        if isinstance(annotation, ast.Subscript) and isinstance(annotation.value, ast.Name):
            if annotation.value.id == "tuple":
                return "a tuple, whose positions are named only where they are unpacked"
            if annotation.value.id == "dict":
                # `dict[K, V]` parses its subscript as a tuple of two nodes; the
                # value is the last, so a one-argument `dict[...]` is read as
                # its own value and still judged.
                inner = annotation.slice
                value = inner.elts[-1] if isinstance(inner, ast.Tuple) else inner
                if not (isinstance(value, ast.Name) and value.id in domain_types):
                    return (
                        "a mapping of something other than a domain object, which "
                        "puts the field names into strings"
                    )
        return ""

    inspected, offences = [], []
    for node in protocol.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        inspected.append(node.name)
        assert node.returns is not None, (
            f"StorePort.{node.name} declares no return type, so this guard cannot "
            "read what the seam hands back"
        )
        wrong = what_is_wrong_with(node.returns)
        if wrong:
            offences.append(
                f"StorePort.{node.name} -> {ast.unparse(node.returns)}: {wrong}"
            )

    assert "store_document" in inspected, (
        "the method this rule was written for was not inspected; the walk found "
        "the protocol but not its methods"
    )
    assert len(inspected) >= _FEWEST_PLAUSIBLE_PORT_METHODS, (
        f"only {len(inspected)} StorePort methods were inspected, fewer than the "
        f"{_FEWEST_PLAUSIBLE_PORT_METHODS} this protocol plausibly declares; the "
        "walk is reading almost nothing and would pass whatever the port did"
    )
    assert not offences, (
        "a port method hands back an unnamed value, which `port.py` forbids: "
        + "; ".join(offences)
        + ". Return a named domain object instead, so the fields cannot be "
        "reordered or misspelled without something failing."
    )
