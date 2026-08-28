"""Carrying a store forward across a schema change.

Two kinds of test live here. The first kind exercises the runner against a store
built at the frozen baseline. The second kind is mechanical: it reads the ladder
itself and fails if a future step breaks the additive rule, because this project
has learned that a rule stated only in a comment is a rule a later change breaks
without noticing.
"""

from __future__ import annotations

import sqlite3

import pytest

from jackryan.errors import ConfigError
from jackryan.storage.sqlite import (
    _BASELINE_VERSION,
    _OLDEST_MIGRATABLE,
    _SCHEMA,
    _STEPS,
    SCHEMA_VERSION,
    SqliteStore,
)

DIMENSIONS = 64
IDENTITY = "chunk_max_chars=400|embed_model=test|embedder=deterministic"


def build_baseline_store(path, *, version=_BASELINE_VERSION, rows=True):
    """A store at the frozen baseline shape, as an older build would have left it.

    Written with raw sqlite3 rather than through SqliteStore, because the point
    is to produce the shape this code no longer creates.
    """
    import sqlite_vec

    conn = sqlite3.connect(path)
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(_SCHEMA)
    conn.execute(
        "CREATE VIRTUAL TABLE IF NOT EXISTS chunk_vectors "
        f"USING vec0(embedding float[{DIMENSIONS}])"
    )
    conn.executescript(SqliteStore._SIDECAR_TRIGGER)
    conn.execute(
        "INSERT INTO store_meta (key, value) VALUES ('schema_version', ?)", (str(version),)
    )
    conn.execute(
        "INSERT INTO store_meta (key, value) VALUES ('contract_fingerprint', ?)", (IDENTITY,)
    )
    if rows:
        conn.execute(
            "INSERT INTO casefiles (id, slug, title, description, created_at, updated_at)"
            " VALUES ('c1', 'harbour', 'Harbour', '', '2026-01-01T00:00:00+00:00',"
            " '2026-01-01T00:00:00+00:00')"
        )
        conn.execute(
            "INSERT INTO documents (id, casefile_id, content_hash, filename, media_type,"
            " byte_size, extracted_text, extractor, created_at, updated_at, parent_id,"
            " containment_path, identity_path)"
            " VALUES ('d1', 'c1', 'hash1', 'lease.md', 'text/markdown', 10, 'the lease text',"
            " 'plaintext', '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00', NULL,"
            " 'lease.md', '')"
        )
    conn.commit()
    conn.close()
    return path


def columns_of(store, table="documents"):
    return [row[1] for row in store._db.execute(f"PRAGMA table_info({table})")]


# --- The runner ---------------------------------------------------------------


def test_a_baseline_store_is_carried_forward_rather_than_refused(tmp_path):
    """The whole point: an older store opens instead of being thrown away.

    Before the ladder this raised "the corpus is only appendable under the rules
    that created it" and the operator's only option was to recreate the corpus.
    """
    path = build_baseline_store(tmp_path / "old.db")
    store = SqliteStore(path)
    try:
        store.initialize(IDENTITY, DIMENSIONS)
        assert "text_source" in columns_of(store)
        recorded = store._db.execute(
            "SELECT value FROM store_meta WHERE key='schema_version'"
        ).fetchone()["value"]
        assert recorded == str(SCHEMA_VERSION)
    finally:
        store.close()


def test_the_migration_survives_closing_the_store(tmp_path):
    """Read it back off disk, through a connection that never saw the migration.

    Every other assertion here reads through the connection that applied the
    steps, inside its still-open transaction, so an uncommitted migration looks
    exactly like a committed one. A fresh store cannot catch it either:
    `_verify_meta` commits the fingerprint insert straight afterwards and
    incidentally flushes the pending migration. Only a store that already
    carries a fingerprint depends on the migration's own commit — which is this
    one.
    """
    path = build_baseline_store(tmp_path / "old.db")
    store = SqliteStore(path)
    store.initialize(IDENTITY, DIMENSIONS)
    store.close()

    conn = sqlite3.connect(path)
    try:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(documents)")]
        assert "text_source" in cols, "the migration was not committed to disk"
        stamped = conn.execute(
            "SELECT value FROM store_meta WHERE key='schema_version'"
        ).fetchone()[0]
        assert stamped == str(SCHEMA_VERSION)
    finally:
        conn.close()


def test_documents_written_before_the_column_still_read(tmp_path):
    # A document ingested before text_source existed has no honest value, so it
    # gets the empty default and discloses itself as unrecorded downstream.
    path = build_baseline_store(tmp_path / "old.db")
    store = SqliteStore(path)
    try:
        store.initialize(IDENTITY, DIMENSIONS)
        document = store.get_document("d1")
        assert document is not None
        assert document.filename == "lease.md"
        assert document.extracted_text == "the lease text"
        assert document.text_source == ""
    finally:
        store.close()


def test_an_unrecorded_rung_is_disclosed_as_unrecorded(tmp_path):
    from jackryan.ingestion.quality_gate import read_as

    path = build_baseline_store(tmp_path / "old.db")
    store = SqliteStore(path)
    try:
        store.initialize(IDENTITY, DIMENSIONS)
        assert read_as(store.get_document("d1").text_source) == "unrecorded"
    finally:
        store.close()


def test_a_current_store_is_left_untouched(tmp_path):
    path = tmp_path / "current.db"
    first = SqliteStore(path)
    first.initialize(IDENTITY, DIMENSIONS)
    first.close()

    second = SqliteStore(path)
    try:
        second.initialize(IDENTITY, DIMENSIONS)
    finally:
        second.close()
    # Reopening a store already at the running version must not write a backup:
    # there is nothing to carry forward, so there is nothing to preserve.
    assert not list(tmp_path.glob("*.bak"))


def test_a_store_from_a_newer_build_is_refused(tmp_path):
    path = build_baseline_store(tmp_path / "future.db", version=SCHEMA_VERSION + 5)
    store = SqliteStore(path)
    try:
        with pytest.raises(ConfigError) as exc:
            store.initialize(IDENTITY, DIMENSIONS)
        message = str(exc.value)
        assert str(SCHEMA_VERSION + 5) in message and str(SCHEMA_VERSION) in message
        assert "newer version" in message
    finally:
        store.close()


def test_a_store_older_than_the_floor_is_refused(tmp_path):
    path = build_baseline_store(tmp_path / "ancient.db", version=_OLDEST_MIGRATABLE - 1)
    store = SqliteStore(path)
    try:
        with pytest.raises(ConfigError) as exc:
            store.initialize(IDENTITY, DIMENSIONS)
        assert "reingest" in str(exc.value)
    finally:
        store.close()


def test_the_schema_refusal_does_not_borrow_the_identity_remedy(tmp_path):
    # They fail for different reasons. "Restore the configuration the values
    # above name" cannot be acted on for a schema this build does not contain.
    path = build_baseline_store(tmp_path / "future.db", version=SCHEMA_VERSION + 5)
    store = SqliteStore(path)
    try:
        with pytest.raises(ConfigError) as exc:
            store.initialize(IDENTITY, DIMENSIONS)
        assert "restore the configuration" not in str(exc.value).lower()
    finally:
        store.close()


# --- The backup ---------------------------------------------------------------


def test_a_store_is_backed_up_before_it_is_migrated(tmp_path):
    path = build_baseline_store(tmp_path / "old.db")
    store = SqliteStore(path)
    try:
        store.initialize(IDENTITY, DIMENSIONS)
    finally:
        store.close()

    backup = tmp_path / f"old.db.v{_BASELINE_VERSION}.bak"
    assert backup.exists(), "the store as it was must survive the migration"

    # And it must be a usable store, not a partial file: the copy is the way
    # back, so it has to open and hold what the original held.
    import sqlite_vec

    conn = sqlite3.connect(backup)
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    try:
        assert conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 1
        # The pre-migration shape, which is what makes it a way back.
        cols = [r[1] for r in conn.execute("PRAGMA table_info(documents)")]
        assert "text_source" not in cols
    finally:
        conn.close()


def test_the_backup_captures_commits_still_living_in_the_wal(tmp_path):
    """A file copy would lose them, and the spec forbids a file copy.

    This store runs in WAL mode, so a committed row can be in the -wal and not
    yet in the main file. `shutil.copyfile` here passes every other assertion in
    this module while silently dropping such rows — and the backup is the
    operator's only way back from a bad migration.

    Holding a second connection open with a committed row is what makes the WAL
    hot; the fixture closes its build connection, which checkpoints, so nothing
    else in this file can expose the difference.
    """
    import sqlite_vec

    path = build_baseline_store(tmp_path / "old.db")

    writer = sqlite3.connect(path)
    writer.enable_load_extension(True)
    sqlite_vec.load(writer)
    writer.enable_load_extension(False)
    writer.execute(
        "INSERT INTO documents (id, casefile_id, content_hash, filename, media_type,"
        " byte_size, extracted_text, extractor, created_at, updated_at, parent_id,"
        " containment_path, identity_path)"
        " VALUES ('d2', 'c1', 'hash2', 'minutes.md', 'text/markdown', 10, 'minutes',"
        " 'plaintext', '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00', NULL,"
        " 'minutes.md', '')"
    )
    writer.commit()

    try:
        store = SqliteStore(path)
        try:
            store.initialize(IDENTITY, DIMENSIONS)
        finally:
            store.close()

        backup = tmp_path / f"old.db.v{_BASELINE_VERSION}.bak"
        conn = sqlite3.connect(backup)
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
        try:
            ids = sorted(r[0] for r in conn.execute("SELECT id FROM documents"))
            assert ids == ["d1", "d2"], (
                f"the backup holds {ids}; a commit living in the -wal was lost, which "
                "is what a file copy does and what the backup API exists to avoid"
            )
        finally:
            conn.close()
    finally:
        writer.close()


def test_a_store_that_cannot_be_backed_up_is_not_migrated(tmp_path):
    path = build_baseline_store(tmp_path / "old.db")

    # Something is already in the way at the backup's destination, and it is not
    # a file. Realistic — a stale directory, a mount point, a permissions
    # problem — and it means the copy cannot be written.
    (tmp_path / f"old.db.v{_BASELINE_VERSION}.bak").mkdir()

    store = SqliteStore(path)
    try:
        with pytest.raises(ConfigError) as exc:
            store.initialize(IDENTITY, DIMENSIONS)
        assert ".bak" in str(exc.value)
    finally:
        store.close()

    # Nothing ran: the store is still at the shape it had.
    conn = sqlite3.connect(path)
    try:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(documents)")]
        assert "text_source" not in cols
    finally:
        conn.close()


# --- Mechanical rules ---------------------------------------------------------

EVIDENCE_TABLES = ("documents", "casefiles", "chunks")


def test_no_step_is_destructive():
    """The additive rule, enforced by reading the ladder rather than trusting it.

    A migration that drops or rewrites a table holding evidence is not a
    migration, it is data loss with a version bump.
    """
    for step in _STEPS:
        for statement in step.statements:
            upper = " ".join(statement.upper().split())
            assert "DROP TABLE" not in upper, f"step {step.to_version} drops a table"
            assert "DROP INDEX" not in upper, f"step {step.to_version} drops an index"
            for table in EVIDENCE_TABLES:
                assert f"CREATE TABLE {table.upper()}" not in upper, (
                    f"step {step.to_version} recreates {table}, which holds evidence"
                )
                assert f"DELETE FROM {table.upper()}" not in upper, (
                    f"step {step.to_version} deletes from {table}"
                )


def test_every_step_says_why():
    # Quoted when a migration runs and when one is refused. It is the only thing
    # that tells an operator later why their corpus grew a column.
    for step in _STEPS:
        assert step.reason.strip(), f"step {step.to_version} has no reason"


def test_the_version_is_derived_from_the_ladder():
    assert SCHEMA_VERSION == max(
        (s.to_version for s in _STEPS), default=_BASELINE_VERSION
    )


def test_the_ladder_and_the_baseline_produce_the_same_schema(tmp_path):
    """A store walked up the ladder is indistinguishable from a fresh one.

    This is what stops the frozen baseline and the steps drifting apart — the
    failure that would otherwise show up as two stores with the same recorded
    version and different shapes.
    """
    migrated_path = build_baseline_store(tmp_path / "migrated.db")
    migrated = SqliteStore(migrated_path)
    migrated.initialize(IDENTITY, DIMENSIONS)

    fresh = SqliteStore(tmp_path / "fresh.db")
    fresh.initialize(IDENTITY, DIMENSIONS)

    def schema_of(store):
        return sorted(
            (row["type"], row["name"], " ".join((row["sql"] or "").split()))
            for row in store._db.execute(
                "SELECT type, name, sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"
            )
        )

    try:
        assert schema_of(migrated) == schema_of(fresh)
    finally:
        migrated.close()
        fresh.close()


BASELINE_DOCUMENT_COLUMNS = (
    "id",
    "casefile_id",
    "content_hash",
    "filename",
    "media_type",
    "byte_size",
    "extracted_text",
    "extractor",
    "created_at",
    "updated_at",
    "parent_id",
    "containment_path",
    "identity_path",
)


def test_the_frozen_baseline_is_frozen(tmp_path):
    """Pin the baseline literally, because nothing else can.

    The parity test compares a migrated store against a fresh one, but both are
    built from the live `_SCHEMA` object — so adding a column there instead of
    to `_STEPS` leaves it green. That edit is silently wrong in the worst way:
    every statement in the script is IF NOT EXISTS, so a store already on disk
    never gains the column while every store created afterwards has it, both
    stamped with the same version.

    Written out rather than derived, so that changing the baseline requires
    changing this list too — which is the point at which someone has to ask
    whether it should have been a step.
    """
    path = build_baseline_store(tmp_path / "baseline.db", rows=False)
    conn = sqlite3.connect(path)
    try:
        cols = tuple(r[1] for r in conn.execute("PRAGMA table_info(documents)"))
    finally:
        conn.close()
    assert cols == BASELINE_DOCUMENT_COLUMNS, (
        "the frozen baseline changed. If this is a new column, it belongs in "
        "_STEPS, not in _SCHEMA — a store already on disk would never receive it."
    )


def test_the_fts_trigger_covers_every_fts_column(tmp_path):
    """The trigger must name every column the FTS table has.

    FTS5's external-content 'delete' command needs the values of all indexed
    columns to remove a row's tokens. Supply fewer, and the missing column's
    tokens stay in the index: MATCH keeps returning the deleted row and a strict
    integrity check reports the database malformed. It would fire on every
    ordinary reingest, because rebuilding a document's chunks starts by deleting
    them — and a summaries column is on the roadmap.
    """
    store = SqliteStore(tmp_path / "fts.db")
    store.initialize(IDENTITY, DIMENSIONS)
    try:
        fts_columns = [r[1] for r in store._db.execute("PRAGMA table_info(chunks_fts)")]
        trigger = store._db.execute(
            "SELECT sql FROM sqlite_master WHERE type='trigger' AND name='chunks_after_delete'"
        ).fetchone()["sql"]
        for column in fts_columns:
            assert f"old.{column}" in trigger, (
                f"chunks_fts has column {column!r} but the delete trigger does not "
                "supply it; deleted rows would leave their tokens in the index"
            )
    finally:
        store.close()


def test_a_second_process_does_not_overwrite_the_pre_migration_copy(tmp_path):
    """The backup is the way back, and the older copy is the valuable one.

    Two processes can open the same store on the first run after an upgrade —
    `docker compose up` and `docker compose run cli` share a data directory —
    and both read the old version before either commits. If the loser writes its
    backup after the winner has migrated, the only pre-migration copy is
    replaced by a post-migration one, under a name still claiming the old
    version.
    """
    path = build_baseline_store(tmp_path / "old.db")
    backup = tmp_path / f"old.db.v{_BASELINE_VERSION}.bak"

    first = SqliteStore(path)
    first.initialize(IDENTITY, DIMENSIONS)
    first.close()
    assert backup.exists()

    conn = sqlite3.connect(backup)
    try:
        before = [r[1] for r in conn.execute("PRAGMA table_info(documents)")]
    finally:
        conn.close()

    # A second process now runs the same migration path against a store that is
    # already carried forward. Nothing it does may touch the existing copy.
    second = SqliteStore(path)
    second.initialize(IDENTITY, DIMENSIONS)
    second.close()

    conn = sqlite3.connect(backup)
    try:
        after = [r[1] for r in conn.execute("PRAGMA table_info(documents)")]
    finally:
        conn.close()
    assert before == after, "the pre-migration copy was overwritten"
    assert "text_source" not in after, "the backup now holds post-migration content"
