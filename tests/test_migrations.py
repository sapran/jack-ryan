"""Carrying a store forward across a schema change.

Two kinds of test live here. The first kind exercises the runner against a store
built at the frozen baseline. The second kind is mechanical: it reads the ladder
itself and fails if a future step breaks the additive rule, because this project
has learned that a rule stated only in a comment is a rule a later change breaks
without noticing.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

import pytest

from jackryan.errors import ConfigError
from jackryan.storage.migrations import (
    _BASELINE_VERSION,
    _OLDEST_MIGRATABLE,
    _SCHEMA,
    _SIDECAR_TRIGGER,
    _STEPS,
    SCHEMA_VERSION,
)
from jackryan.storage.sqlite import SqliteStore

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
    conn.executescript(_SIDECAR_TRIGGER)
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


def test_an_older_store_gains_the_ingest_run_record(tmp_path):
    """A store built before the run record opens and gains the table.

    The mechanical guards below cover the additive rule and the version
    derivation. What they cannot say is that this particular step reaches an
    old store and leaves its evidence alone, which is the only thing an
    operator with a filled corpus cares about.

    Two stores, not one. `migrate` computes `confirmed` **once** and then runs
    every step whose `to_version` exceeds it, so from the baseline this step
    applies even if its `to_version` duplicated the one before it. A store
    already stamped at the previous version is the case that depends on the
    version being higher.

    **This test does not pin `to_version`, and cannot.** `previous` is derived
    from `_STEPS`, so a duplicated version moves it too and this stays green —
    measured, not supposed. What pins it is
    `test_the_ladder_versions_strictly_increase`, which asserts the property
    instead of consuming the value. This half is here for the behaviour: that a
    store one rung down really does arrive with the table.

    The anchor is the step that creates the table, not the top of the ladder.
    The two were the same value only while this was the newest rung: taking
    `max(to_version < SCHEMA_VERSION)` means every rung added above it builds a
    store already stamped at *this* step's version, which then correctly skips
    the step the test exists to exercise and fails for a reason that has nothing
    to do with the run record.
    """
    expected_columns = {
        "id",
        "casefile_id",
        "started_at",
        "finished_at",
        "documents_before",
        "documents_after",
        "items_ingested",
        "items_failed",
        "entries_refused",
        "files_without_extractor",
        "exhausted_by",
    }

    creates_the_record = min(
        step.to_version
        for step in _STEPS
        if any("ingest_runs" in statement for statement in step.statements)
    )
    previous = max(
        (step.to_version for step in _STEPS if step.to_version < creates_the_record),
        default=_BASELINE_VERSION,
    )
    at_previous = build_baseline_store(tmp_path / "at-previous.db", version=previous)
    store = SqliteStore(at_previous)
    try:
        store.initialize(IDENTITY, DIMENSIONS)
        assert set(columns_of(store, "ingest_runs")) == expected_columns, (
            f"a store stamped at {previous} did not reach the run-record step"
        )
    finally:
        store.close()

    path = build_baseline_store(tmp_path / "old.db")
    store = SqliteStore(path)
    try:
        store.initialize(IDENTITY, DIMENSIONS)

        assert set(columns_of(store, "ingest_runs")) == expected_columns
        # The document written at the baseline still reads. A migration that
        # reached the evidence would be the one unrecoverable failure here.
        document = store._db.execute(
            "SELECT extracted_text FROM documents WHERE id='d1'"
        ).fetchone()
        assert document["extracted_text"] == "the lease text"
        # And no run is invented for it: a casefile filled before the record
        # existed must read as unaccounted-for, not as clean.
        assert store.ingestion_coverage("c1").runs == 0
    finally:
        store.close()


def test_a_document_carried_forward_reports_its_locations_as_unknown(tmp_path):
    """A document that predates the location record must never claim otherwise.

    Its source locations were overwritten by whichever copy was ingested last,
    and nothing can recover them. Nothing is written for such a document, so it
    has no observation, so no earliest observation can be no later than its
    creation — and one recorded afterwards is later than it, which is why a
    further sighting cannot turn missing history into a whole record.
    """
    path = build_baseline_store(tmp_path / "old.db")
    store = SqliteStore(path)
    try:
        store.initialize(IDENTITY, DIMENSIONS)

        document = store.get_document("d1")
        assert document is not None
        # No location is invented for it: the only timestamp available is
        # `created_at`, which is when the document was first ingested and not
        # when any particular copy was observed.
        assert store.document_locations("d1", 20).total == 0

        # A later sighting is recorded, and is later than the document. The
        # store writes it through the one call that also stores the document,
        # which on a reingest keeps the row it already has.
        later = datetime.now(timezone.utc)
        assert later > document.created_at
        written = store.store_document(document, "/dumps/alpha/lease.md", later)
        assert written.location_is_new is True

        recorded = store.document_locations("d1", 20)
        assert recorded.total == 1
        assert recorded.locations[0].first_seen_at > written.document.created_at, (
            "an observation recorded after the document was created must stay later "
            "than it, or the record would read as whole"
        )
    finally:
        store.close()


def test_existing_location_records_are_carried_into_observations(tmp_path):
    """Rung 10 keeps what was recorded, and collapses one place recorded twice.

    The prior key was the ingest root paired with the path within it, so a
    folder walk and then that folder's nested file named directly wrote two
    rows for one file. Carrying them across joins each pair into its path,
    which makes the duplicate a duplicate — and the earliest sighting is the
    one kept, because that is what the wholeness of the record is judged
    against.
    """
    path = build_baseline_store(tmp_path / "old.db", version=9)
    conn = sqlite3.connect(path)
    try:
        # The shape rung 9 left: a pair-keyed table, holding one place twice
        # and one place once.
        conn.execute(
            "CREATE TABLE document_locations ("
            " document_id TEXT NOT NULL, source_root TEXT NOT NULL,"
            " containment_path TEXT NOT NULL, first_seen_at TEXT NOT NULL,"
            " PRIMARY KEY (document_id, source_root, containment_path))"
        )
        conn.execute("ALTER TABLE documents ADD COLUMN locations_recorded INTEGER NOT NULL DEFAULT 0")
        # The two rows for one place are ordered so that the pair ordering and
        # the timestamp ordering *disagree*: by (source_root, containment_path)
        # `/dump` sorts first, and it carries the later sighting. Without that,
        # grouping by the pair instead of by the path still happens to keep the
        # earliest, and this test passes while proving nothing — measured, not
        # supposed.
        conn.executemany(
            "INSERT INTO document_locations VALUES (?, ?, ?, ?)",
            [
                ("d1", "/dump", "sub/lease.md", "2026-01-03T00:00:00+00:00"),
                ("d1", "/dump/sub", "lease.md", "2026-01-02T00:00:00+00:00"),
                ("d1", "/elsewhere", "lease.md", "2026-01-04T00:00:00+00:00"),
            ],
        )
        conn.commit()
    finally:
        conn.close()

    store = SqliteStore(path)
    try:
        store.initialize(IDENTITY, DIMENSIONS)
        recorded = store.document_locations("d1", 20)
        assert [location.path for location in recorded.locations] == [
            "/dump/sub/lease.md",
            "/elsewhere/lease.md",
        ], "the two rows for one place did not collapse into it"
        assert recorded.total == 2
        # The earliest of the two sightings of that place is the one kept, not
        # whichever the prior key happened to order first.
        assert recorded.locations[0].first_seen_at.isoformat() == "2026-01-02T00:00:00+00:00", (
            "the later sighting of a place recorded twice was kept"
        )
        # And the prior record is still there, unrewritten.
        surviving = store._db.execute(
            "SELECT COUNT(*) AS n FROM document_locations"
        ).fetchone()["n"]
        assert surviving == 3, "the prior record was rewritten rather than kept"
    finally:
        store.close()


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

# `document_places` is the live record: rung 11 made it the one table every
# location observation is written to and read from, and a location is evidence
# of custody in its own right — where a file was found is a finding, not a
# derived convenience that could be rebuilt. `chunks` can be recomputed from a
# document; an observation cannot be recomputed from anything.
#
# `document_observations` and `document_locations` are here too, and they are
# the ones that need the guard most. Rungs 10 and 11 stopped writing them and
# say in comments that they are kept deliberately, because they hold which root
# each place was reached through and the spelling each was recorded under, and
# dropping either would destroy provenance to tidy a representation. This
# module's own docstring argues that a rule only a comment states is a rule a
# later change breaks without noticing, and an unwritten table is exactly what
# a later change tidies up.
EVIDENCE_TABLES = (
    "documents",
    "casefiles",
    "chunks",
    "document_places",
    "document_observations",
    "document_locations",
)


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


def test_the_ladder_versions_strictly_increase():
    """Two steps may never declare the same version, and none may go backwards.

    Not pedantry about tidiness — it is the only thing that makes a step
    reachable. `migrate` computes the store's version once and then runs every
    step whose `to_version` exceeds it, so from the baseline a step declaring a
    version already used still applies and looks perfectly healthy. The store
    it silently skips is one already stamped at that version: `migrate` returns
    early on `recorded == SCHEMA_VERSION`, and the duplicate step never runs
    against the stores that most need it — the ones already in service.

    Asserted as a property of the ladder rather than through a migrated store,
    because any test that derives "the previous version" from `_STEPS` moves
    with the very value a mistake would change, and passes. That was measured:
    the two-store test above stayed green against a duplicated version for
    exactly that reason.
    """
    versions = [step.to_version for step in _STEPS]
    assert versions == sorted(set(versions)), (
        f"the ladder's versions must strictly increase, got {versions}"
    )
    assert versions[0] > _BASELINE_VERSION, (
        f"the first step must climb above the baseline {_BASELINE_VERSION}"
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


def test_a_failing_step_leaves_the_store_at_its_recorded_version(tmp_path, monkeypatch):
    """A step that raises must roll back, not half-apply.

    Every step runs inside one transaction with one commit, so an interrupted
    migration leaves the store exactly as it was — which is what makes it safe
    to retry, and what makes the backup a second line of defence rather than the
    only one.
    """
    from jackryan.storage import migrations as mod

    broken = mod._Step(
        to_version=SCHEMA_VERSION + 1,
        reason="a step that cannot succeed",
        statements=(
            "ALTER TABLE documents ADD COLUMN added_first TEXT NOT NULL DEFAULT ''",
            "ALTER TABLE documents ADD COLUMN added_first TEXT NOT NULL DEFAULT ''",
        ),
    )
    monkeypatch.setattr(mod, "_STEPS", mod._STEPS + (broken,))
    monkeypatch.setattr(mod, "SCHEMA_VERSION", SCHEMA_VERSION + 1)

    path = build_baseline_store(tmp_path / "old.db")
    store = SqliteStore(path)
    try:
        with pytest.raises(ConfigError) as exc:
            store.initialize(IDENTITY, DIMENSIONS)
        assert "could not be carried" in str(exc.value)
    finally:
        store.close()

    # Nothing half-applied, and the version is untouched: a retry starts from a
    # known place rather than from wherever the failure happened to land.
    conn = sqlite3.connect(path)
    try:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(documents)")]
        assert "added_first" not in cols
        assert "text_source" not in cols
        stamped = conn.execute(
            "SELECT value FROM store_meta WHERE key='schema_version'"
        ).fetchone()[0]
        assert stamped == str(_BASELINE_VERSION)
    finally:
        conn.close()


def test_the_version_is_re_read_under_the_write_lock(tmp_path, monkeypatch):
    """The unlocked first read is only safe because of the re-read.

    The version is read once without a lock so the backup can be taken — SQLite's
    backup API cannot run inside a write transaction — and then again inside the
    transaction that applies the steps. If another process migrated the file in
    between, applying the steps a second time is what ADD COLUMN cannot survive.

    Simulated by migrating the store out from under an in-flight open, which is
    what the re-read exists to notice.
    """
    from jackryan.storage import migrations as mod

    path = build_baseline_store(tmp_path / "old.db")

    store = SqliteStore(path)
    original = mod.backup_before_migrating
    raced = []

    def migrate_underneath(conn, store_path, recorded):
        original(conn, store_path, recorded)
        # Put the real function back before the nested migration runs. The patch
        # is on the module now, so it applies to every store in the process; the
        # instance-level patch it replaced applied only to this one, and leaving
        # it in place here makes the competing store re-enter this function
        # forever.
        monkeypatch.setattr(mod, "backup_before_migrating", original)
        # Another process finishes the whole migration while we hold no lock.
        other = SqliteStore(path)
        other.initialize(IDENTITY, DIMENSIONS)
        other.close()
        raced.append(True)

    # Patched on the module `migrate` reads the name from. It is a module-level
    # function now rather than a method on the store, so patching the store
    # would bind a name nothing calls and the race would never be triggered —
    # which the assertion below would catch.
    monkeypatch.setattr(mod, "backup_before_migrating", migrate_underneath)
    try:
        store.initialize(IDENTITY, DIMENSIONS)
        assert raced, "the race was never triggered"
        assert "text_source" in columns_of(store)
    finally:
        store.close()
