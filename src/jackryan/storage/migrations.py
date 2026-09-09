"""The schema this store creates, and the ladder that carries an older one forward.

Split out of `sqlite.py` so the three artefacts the freeze below covers — the
baseline script, the vector table, and the delete trigger — are created by one
function in one module rather than assembled at two call sites. Their drifting
apart is the failure the freeze exists to prevent, and it was previously
prevented only by a comment asking the reader to remember.

Nothing here holds a connection or a lock. Every function takes an open
connection and the store's path (for its error messages); `SqliteStore` keeps
the lock and takes it around the calls that need it. A module that acquired its
own lock would be a second place threading is reasoned about.

Editing anything in this file loads `storage/CLAUDE.md`, which is where the
rules for `_SCHEMA` and `_STEPS` live and why each one matters.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from ..errors import ConfigError
from .port import join_location

_BASELINE_VERSION = 4
"""The shape `_SCHEMA` below creates. Frozen — see the warning on `_SCHEMA`."""

_OLDEST_MIGRATABLE = 4
"""Older than this is refused rather than migrated.

Nothing older exists outside development, and carrying a shape forward that no
one has is a guess maintained forever.
"""

# ---------------------------------------------------------------------------
# FROZEN. Do not add a column, a table or an index here — add a step to _STEPS.
#
# Every statement below is `IF NOT EXISTS`, which means editing this script adds
# the change for a store created afterwards and *silently does not* add it for a
# store that already exists. That asymmetry does not show up in a diff, and it
# is the reason this is frozen rather than merely left alone by convention.
#
# It is deliberately one version behind the schema this code produces: the
# ladder's first rung is applied to every store, including a brand new one, so
# the migration runner is exercised by the whole test suite rather than by a
# single fixture. A runner covered only by a fixture rots between the day it is
# written and the day it is first needed, which is the worst day to find out.
#
# `_SIDECAR_TRIGGER` and the `chunk_vectors` statement in `create_baseline`
# below are part of this freeze. They are separate artefacts, and leaving them
# out is how the ladder and the create path drift apart — which is why one
# function issues all three rather than a call site assembling them.
# ---------------------------------------------------------------------------
_SCHEMA = """
CREATE TABLE IF NOT EXISTS store_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS casefiles (
    id          TEXT PRIMARY KEY,
    slug        TEXT NOT NULL UNIQUE,
    title       TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_casefiles_slug ON casefiles(slug);

CREATE TABLE IF NOT EXISTS documents (
    id             TEXT PRIMARY KEY,
    casefile_id    TEXT NOT NULL REFERENCES casefiles(id) ON DELETE CASCADE,
    content_hash   TEXT NOT NULL,
    filename       TEXT NOT NULL,
    media_type     TEXT NOT NULL DEFAULT '',
    byte_size      INTEGER NOT NULL DEFAULT 0,
    extracted_text TEXT NOT NULL DEFAULT '',
    extractor      TEXT NOT NULL DEFAULT '',
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL,
    -- CASCADE, so a descendant cannot outlive the container that carried it
    -- whatever path does the deleting. Verified to recurse through nesting and
    -- to fire the chunk trigger below at every level, which is what keeps the
    -- full-text and vector sidecars from being orphaned.
    parent_id      TEXT REFERENCES documents(id) ON DELETE CASCADE,
    -- Where this document was found, for a human to follow. Always recorded,
    -- including the directory names a walk passed through.
    containment_path TEXT NOT NULL DEFAULT '',
    -- The part of that path which counts toward identity: empty for a file
    -- ingested directly, so two copies in one folder are one document; the
    -- containment path for one expanded out of a container, so the same
    -- attachment on two messages is two documents — which message carried it
    -- is itself evidence.
    identity_path  TEXT NOT NULL DEFAULT '',
    UNIQUE(casefile_id, content_hash, identity_path)
);

CREATE INDEX IF NOT EXISTS idx_documents_casefile ON documents(casefile_id);
CREATE INDEX IF NOT EXISTS idx_documents_parent ON documents(parent_id);

-- The implicit integer rowid is the key that ties a chunk to its full-text
-- entry and to its vector, so all three are addressed identically.
CREATE TABLE IF NOT EXISTS chunks (
    id           TEXT NOT NULL UNIQUE,
    document_id  TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    casefile_id  TEXT NOT NULL REFERENCES casefiles(id) ON DELETE CASCADE,
    ordinal      INTEGER NOT NULL,
    heading_path TEXT NOT NULL DEFAULT '',
    text         TEXT NOT NULL,
    char_start   INTEGER NOT NULL,
    char_end     INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_chunks_document ON chunks(document_id);
CREATE INDEX IF NOT EXISTS idx_chunks_casefile ON chunks(casefile_id);

-- External-content FTS: the text lives once, in `chunks`.
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts
    USING fts5(text, content='chunks', content_rowid='rowid');
"""


@dataclass(frozen=True)
class _Step:
    """One rung of the ladder: a version to reach, and how to reach it.

    `reason` is not decoration. It is quoted when a migration runs and when one
    is refused, and it is the only thing that tells an operator six months later
    why their corpus grew a column.
    """

    to_version: int
    reason: str
    statements: tuple[str, ...]


_STEPS: tuple[_Step, ...] = (
    _Step(
        to_version=5,
        reason="documents record which rung of the quality gate produced their text",
        statements=(
            "ALTER TABLE documents ADD COLUMN text_source TEXT NOT NULL DEFAULT ''",
        ),
    ),
    # None of these three columns enters `chunks_fts`, and that exclusion is a
    # decision rather than an omission. A model's words answering a keyword
    # search would report a document as containing a term that appears nowhere
    # in it, and a ranked list has no way to mark which hits matched evidence
    # and which matched a summary of it. The FTS column list is therefore
    # unchanged and `_SIDECAR_TRIGGER` is untouched.
    _Step(
        to_version=6,
        reason="chunks record the context folded into what was embedded, and documents record their summary and who wrote it",
        statements=(
            "ALTER TABLE chunks ADD COLUMN summary TEXT NOT NULL DEFAULT ''",
            "ALTER TABLE documents ADD COLUMN summary TEXT NOT NULL DEFAULT ''",
            "ALTER TABLE documents ADD COLUMN summary_by TEXT NOT NULL DEFAULT ''",
        ),
    ),
    # This table's cascade needs no trigger, and the difference from the two
    # sidecars is worth stating because the trigger above it looks like the
    # house rule. `chunks.id` is `TEXT NOT NULL UNIQUE`, which SQLite accepts as
    # a foreign-key parent, and `PRAGMA foreign_keys=ON` is set in `initialize`,
    # so deleting a chunk — or the document or the casefile above it — deletes
    # its mentions. `_SIDECAR_TRIGGER` exists only because `chunks_fts` and
    # `chunk_vectors` are virtual tables, which never observe a cascade at all;
    # a real table does. So this step adds no trigger, and touches neither that
    # one nor the FTS column list it names.
    _Step(
        to_version=7,
        reason="mentions are extracted at ingest so identifiers can be faceted and pivoted on",
        statements=(
            "CREATE TABLE IF NOT EXISTS mentions ("
            " chunk_id TEXT NOT NULL REFERENCES chunks(id) ON DELETE CASCADE,"
            " document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,"
            " casefile_id TEXT NOT NULL REFERENCES casefiles(id) ON DELETE CASCADE,"
            " kind TEXT NOT NULL, value TEXT NOT NULL, normalised TEXT NOT NULL,"
            " char_start INTEGER NOT NULL, char_end INTEGER NOT NULL,"
            # Where the identifier sits in the document, as opposed to in the
            # chunk. Chunks overlap by the contract's overlap, so one textual
            # occurrence near a boundary is extracted from two chunks; counting
            # rows would then report it twice and "how many times it was
            # mentioned" would be wrong by the overlap. The facet counts
            # distinct (document, offset) pairs instead.
            " document_offset INTEGER NOT NULL DEFAULT 0,"
            " extractor TEXT NOT NULL, confidence REAL NOT NULL DEFAULT 1.0)",
            "CREATE INDEX IF NOT EXISTS idx_mentions_facet ON mentions(casefile_id, kind, normalised)",
            "CREATE INDEX IF NOT EXISTS idx_mentions_pivot ON mentions(casefile_id, normalised)",
            "CREATE INDEX IF NOT EXISTS idx_mentions_chunk ON mentions(chunk_id)",
        ),
    ),
    # No trigger, for the same reason the mentions step above needs none:
    # `casefiles.id` is a real foreign-key parent and `PRAGMA foreign_keys=ON`
    # is set in `initialize`, so deleting a casefile deletes its run records.
    # `_SIDECAR_TRIGGER` exists only because `chunks_fts` and `chunk_vectors`
    # are virtual tables, which never observe a cascade at all. This step adds
    # no column to `chunks_fts`, so that trigger and the FTS column list are
    # untouched.
    _Step(
        to_version=8,
        reason="each completed ingest run is recorded, so a casefile can say how completely it was filled",
        statements=(
            "CREATE TABLE IF NOT EXISTS ingest_runs ("
            " id TEXT PRIMARY KEY,"
            " casefile_id TEXT NOT NULL REFERENCES casefiles(id) ON DELETE CASCADE,"
            " started_at TEXT NOT NULL, finished_at TEXT NOT NULL,"
            # How many documents the casefile held before and after this run.
            #
            # `documents_before` alone answers only "did evidence predate the
            # *first* record". The pair answers the question that matters: does
            # the record account for everything now in the corpus. A run that
            # raises part way is deliberately never recorded, but the documents
            # it already wrote stay — so the next run's `documents_before`
            # exceeds the previous run's `documents_after`, and that gap is the
            # only evidence left that a run happened and was not recorded. It
            # also catches a killed process and a `record_ingest_run` write that
            # itself failed, neither of which any marker on a run row could.
            " documents_before INTEGER NOT NULL DEFAULT 0,"
            " documents_after INTEGER NOT NULL DEFAULT 0,"
            " items_ingested INTEGER NOT NULL DEFAULT 0,"
            " items_failed INTEGER NOT NULL DEFAULT 0,"
            " entries_refused INTEGER NOT NULL DEFAULT 0,"
            " files_without_extractor INTEGER NOT NULL DEFAULT 0,"
            # '' rather than NULL for "no bound was reached", matching
            # `text_source` and `summary_by`.
            " exhausted_by TEXT NOT NULL DEFAULT '')",
            "CREATE INDEX IF NOT EXISTS idx_ingest_runs_casefile"
            " ON ingest_runs(casefile_id, started_at, id)",
        ),
    ),
    _Step(
        to_version=9,
        reason=(
            "documents record every source location their bytes were observed at, so a"
            " second copy no longer overwrites the first"
        ),
        statements=(
            # No separate index: a composite PRIMARY KEY on a rowid table gets
            # an implicit unique index, whose leftmost prefix is document_id —
            # which is the only way this table is ever queried. A second index
            # would be a copy of that one.
            #
            # `source_root` is part of the key because a containment path is
            # relative to whatever was ingested: two dumps each holding
            # `note.txt` at their top level produce the same path, and without
            # the root they would collide into one location — losing exactly
            # the second custodian this table exists to record. It is the
            # *top-level* ingest root, inherited by an expansion rather than
            # taken from the scratch directory its entries are materialised
            # into: that directory is new on every run, which would insert a
            # fresh row and report a false discovery each time a container was
            # reingested.
            "CREATE TABLE IF NOT EXISTS document_locations ("
            " document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,"
            " source_root TEXT NOT NULL,"
            " containment_path TEXT NOT NULL,"
            " first_seen_at TEXT NOT NULL,"
            " PRIMARY KEY (document_id, source_root, containment_path))",
            # Zero for every row that already exists, which is exactly what it
            # has to mean: those documents predate the record and their
            # overwritten locations cannot be recovered. Only an insert by the
            # new code may claim otherwise, which is why `upsert_document`
            # never names this column in its DO UPDATE SET.
            "ALTER TABLE documents ADD COLUMN locations_recorded INTEGER NOT NULL DEFAULT 0",
        ),
    ),
    _Step(
        to_version=10,
        reason=(
            "a location is one path, so a file reached through two ingest roots is one"
            " place rather than two, and the records already kept are carried across"
        ),
        statements=(
            # `document_locations` keyed a location on the ingest root paired
            # with the path within it, which discriminates *observations* rather
            # than *places*: a folder walk and then that folder's nested file
            # named directly yield ("/dump", "sub/note.txt") and
            # ("/dump/sub", "note.txt") for one file. The path alone is the
            # place, and it still separates two dumps that each hold one file at
            # their top level, because those paths differ.
            "CREATE TABLE IF NOT EXISTS document_observations ("
            " document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,"
            " location_path TEXT NOT NULL,"
            " first_seen_at TEXT NOT NULL,"
            " PRIMARY KEY (document_id, location_path))",
            # Carried across rather than reingested, and the GROUP BY is what
            # repairs a store that already holds one place twice: the earliest
            # observation of each path wins, which is the timestamp worth
            # keeping.
            #
            # This concatenation does *not* always agree with the join the
            # runtime uses, which is why rung 11 below exists and why nothing
            # reads this table any more. It is left exactly as it shipped: a
            # rung already applied to a store cannot be corrected by editing
            # it, so editing it would only change what a not-yet-migrated
            # store gets — two populations diverging by which day they were
            # opened, which is the failure the recorded version exists to
            # prevent.
            "INSERT OR IGNORE INTO document_observations"
            " (document_id, location_path, first_seen_at)"
            " SELECT document_id, source_root || '/' || containment_path,"
            " MIN(first_seen_at) FROM document_locations"
            " GROUP BY document_id, source_root || '/' || containment_path",
            # `document_locations` is deliberately left in place and is no
            # longer written. It is the prior record of which root each place was
            # reached through, and dropping it to tidy up would destroy
            # provenance in order to improve a representation. Do not clean it
            # up.
            #
            # `documents.locations_recorded` is likewise no longer written or
            # read. It stored a claim about these rows — whether the record was
            # whole — in a different transaction from the rows themselves, so the
            # two could disagree, and they did: a document written before its
            # first observation kept the claim and lost the row. Whether a
            # record is whole is now derived from it, by asking whether the
            # earliest observation is no later than the document's creation. The
            # ladder is additive, so the column stays; nothing may start reading
            # it again.
        ),
    ),
    _Step(
        to_version=11,
        reason=(
            "a location carried forward is spelled by the same join live ingestion uses,"
            " so reingesting unchanged evidence does not record a second place"
        ),
        statements=(
            # Rung 10 built `document_observations` by concatenating the old
            # root and path with a separator, while every live observation is
            # spelled by `join_location`, which normalises. The two disagree on
            # paths a real dump routinely holds — a tar entry named
            # `./note.txt`, a doubled separator, a source root of `/` — so a
            # migrated store held `bundle.tar/./note.txt` and then gained
            # `bundle.tar/note.txt` on a reingest of the unchanged archive:
            # one place recorded twice, announced as a discovery.
            #
            # A new table rather than a repair of that one. The ladder may only
            # add, and `document_observations` holds evidence — an UPDATE and a
            # DELETE over it is exactly the rewrite the additive rule and its
            # guard test forbid. Rung 10 set the precedent when it left
            # `document_locations` in place: the older representation stays
            # readable, and the corrected one is derived beside it.
            "CREATE TABLE IF NOT EXISTS document_places ("
            " document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,"
            " location_path TEXT NOT NULL,"
            " first_seen_at TEXT NOT NULL,"
            " PRIMARY KEY (document_id, location_path))",
            # Observations this instance's own code wrote, which are already
            # spelled by `join_location` and must be carried across as they
            # are. The NOT EXISTS excludes the rows rung 10 *misspelled*: those
            # are re-derived below from the raw pairs, which is the only place
            # the correct spelling can be recovered from. A root of `/` is why —
            # `//lease.md` is its own normal form, so no amount of
            # re-normalising the concatenated string recovers `/lease.md`, and
            # only the pair `('/', 'lease.md')` says what was meant.
            #
            # The predicate is deliberately narrower than "this row matches a
            # pair": it also requires that the pair's concatenation *differs*
            # from its join, so a row is dropped only when the statement below
            # will reinsert that same place under a different spelling. Without
            # the second condition, a row whose concatenation is already normal
            # is excluded here and re-dated below from the pairs alone —
            # measured, and it replaced an earlier live sighting with a later
            # one, which is the mis-dating `min` exists to prevent.
            "INSERT INTO document_places (document_id, location_path, first_seen_at)"
            " SELECT o.document_id, o.location_path, MIN(o.first_seen_at)"
            " FROM document_observations o"
            " WHERE NOT EXISTS ("
            "   SELECT 1 FROM document_locations l"
            "   WHERE l.document_id = o.document_id"
            "     AND l.source_root || '/' || l.containment_path = o.location_path"
            "     AND l.source_root || '/' || l.containment_path"
            "         <> jr_join_location(l.source_root, l.containment_path))"
            " GROUP BY o.document_id, o.location_path"
            " ON CONFLICT(document_id, location_path) DO UPDATE SET"
            "   first_seen_at = min(first_seen_at, excluded.first_seen_at)",
            # The raw pairs, joined exactly as the runtime joins them, through
            # the one definition in `port.py` registered on the connection as
            # `jr_join_location`. Two spellings of one place therefore collapse
            # here, and `min` keeps the earlier sighting — which is the
            # timestamp the wholeness of the record is judged against, so
            # keeping the later one would turn an old record into a young one.
            #
            # The unqualified `first_seen_at` on the left of the SET, and inside
            # the `min`, is the *existing* row's, even though the SELECT's source
            # table has a column of that name. Measured rather than assumed,
            # because it reads ambiguously: with a stored row at T1 and a source
            # row at T2 > T1, the surviving value is T1, and it is T1 whether the
            # reference is written bare or as `document_places.first_seen_at`.
            # The rungs are shipped, so the bare form stays;
            # `test_the_carry_forward_never_re_dates_a_place_to_a_later_sighting`
            # is what would catch it if that ever stopped being true.
            "INSERT INTO document_places (document_id, location_path, first_seen_at)"
            " SELECT document_id, jr_join_location(source_root, containment_path),"
            " MIN(first_seen_at) FROM document_locations"
            " GROUP BY document_id, jr_join_location(source_root, containment_path)"
            " ON CONFLICT(document_id, location_path) DO UPDATE SET"
            "   first_seen_at = min(first_seen_at, excluded.first_seen_at)",
            # A legacy `containment_path` is always relative — archive entries
            # are refused for an absolute name before they can become one, and
            # a folder walk stores a `relative_to` result. The join relies on
            # it: `PurePosixPath` discards its left operand when the right is
            # absolute, so an absolute path here would strip the custodian root
            # and merge two custodians into one place. The guard is in
            # `ingestion/containers.py`; this is the one place a violation of
            # it would become permanent.
            #
            # Both older tables stay, unwritten and unread, for the reason rung
            # 10 gave: they are the record as it was kept, and this rung's own
            # correctness is checkable against them. Do not clean them up.
        ),
    ),
)
"""The ladder, in order. Every step may only ADD.

A step may add a column with a constant default, create a table, an index or a
trigger, or drop and recreate a sidecar wholly derivable from `chunks`. It may
never drop or rewrite `documents`, `casefiles` or `chunks`, and never change a
uniqueness constraint — those hold evidence, and a migration is not the place to
discover that a rewrite was lossy. `tests/test_migrations.py` reads these
statements and enforces that.

A step is never made idempotent by catching "duplicate column". That turns a
recorded version which lies into a silent success, which is the one thing the
recorded version exists to prevent.

A step that changes the FTS column list MUST drop and recreate
`_SIDECAR_TRIGGER` in the same transaction. The trigger names the columns it
feeds to FTS5's `'delete'` command; if the table gains a column the trigger does
not, deleted rows leave their tokens behind, `MATCH` keeps returning them, and a
strict integrity check reports the database malformed. It would fire on every
ordinary reingest, because rebuilding a document's chunks begins by deleting
them.
"""

SCHEMA_VERSION = max((step.to_version for step in _STEPS), default=_BASELINE_VERSION)
"""Derived, never written by hand.

Declared independently, the version and the ladder can disagree — and what that
disagreement produces is a store stamped as migrated that is not.
"""

# Virtual tables never see ON DELETE CASCADE, so a casefile or document
# deletion would leave full-text postings and vectors behind. SQLite then
# reuses the freed rowids and the next insert collides. A trigger on the
# one table every path deletes from is what makes that unreachable.
_SIDECAR_TRIGGER = """
CREATE TRIGGER IF NOT EXISTS chunks_after_delete AFTER DELETE ON chunks BEGIN
    INSERT INTO chunks_fts(chunks_fts, rowid, text) VALUES('delete', old.rowid, old.text);
    DELETE FROM chunk_vectors WHERE rowid = old.rowid;
END;
"""


def create_baseline(conn: sqlite3.Connection, embed_dimensions: int) -> None:
    """Create the frozen baseline shape: the script, the vector table, the trigger.

    One function rather than three statements at the call site, because the
    comment on `_SCHEMA` says all three are part of the same freeze and leaving
    any of them out is how the ladder and the create path drift apart. Keeping
    them together makes that structural instead of remembered.

    Every statement is `IF NOT EXISTS`, so this is safe on a store that already
    exists — and that is exactly why `_SCHEMA` may never be edited to add
    something: it would be added for new stores and silently skipped for old
    ones.
    """
    conn.executescript(_SCHEMA)
    # The vector index is sized from the contract, so its width is part of
    # corpus identity and cannot drift from the embeddings it holds.
    conn.execute(
        "CREATE VIRTUAL TABLE IF NOT EXISTS chunk_vectors "
        f"USING vec0(embedding float[{int(embed_dimensions)}])"
    )
    conn.executescript(_SIDECAR_TRIGGER)


def recorded_version(conn: sqlite3.Connection, path: Path) -> int | None:
    """The version stamped on this store, or None if it has never been stamped.

    None means "created moments ago by the baseline script", not "version
    zero". The distinction decides whether there is anything to back up: a
    store with no rows in it has nothing to lose, and writing a `.bak` beside
    every brand-new casefile would be litter.
    """
    row = conn.execute(
        "SELECT value FROM store_meta WHERE key = 'schema_version'"
    ).fetchone()
    if row is None:
        return None
    try:
        return int(row["value"])
    except (TypeError, ValueError):
        raise ConfigError(
            f"store at {path} records schema_version={row['value']!r}, which is "
            "not a version number. The file may not be a Jack Ryan store, or its "
            "metadata may be damaged; restore it from a backup."
        ) from None

def migrate(conn: sqlite3.Connection, path: Path) -> None:
    """Carry an older store up the ladder, one transaction, backed up first.

    Ordering here is load-bearing and not obvious:

    The version is read once *outside* a transaction, the backup is taken,
    and the version is read *again* inside the write transaction that
    applies the steps. The first read is unlocked because SQLite's backup
    API cannot run inside a write transaction — so the re-read is not an
    optimisation to be tidied away, it is what makes the unlocked read safe.
    """
    stamped = recorded_version(conn, path)
    # An unstamped store was created by the baseline script a moment ago, so
    # it is at the baseline and holds nothing worth copying.
    is_new = stamped is None
    recorded = _BASELINE_VERSION if stamped is None else stamped

    if recorded == SCHEMA_VERSION:
        return

    if recorded > SCHEMA_VERSION:
        raise ConfigError(
            f"store at {path} was created by a newer version of Jack Ryan: it "
            f"records schema_version={recorded} and this build understands "
            f"{SCHEMA_VERSION}. A newer schema cannot be read by older code without "
            "guessing at what changed. Upgrade Jack Ryan, or open this store with "
            "the version that wrote it."
        )

    if recorded < _OLDEST_MIGRATABLE:
        raise ConfigError(
            f"store at {path} records schema_version={recorded}, which is older "
            f"than the oldest this build can carry forward ({_OLDEST_MIGRATABLE}). "
            "Move the store, its -wal and its -shm aside and reingest the casefiles."
        )

    pending = tuple(step for step in _STEPS if step.to_version > recorded)
    if not pending:
        return

    if not is_new:
        backup_before_migrating(conn, path, recorded)

    # Registered for the ladder, not for the store: rung 11 spells a carried
    # location with the same function live ingestion spells one with, and
    # importing it here is what makes that one definition rather than a second
    # copy in SQL. Deterministic so SQLite may use it inside the GROUP BY it
    # appears in twice.
    #
    # Withdrawn again below, and that is enforcement rather than tidiness: the
    # caller keeps this connection for the life of the process, so a function
    # left registered exists on the one boot that migrated and on no boot
    # afterwards. Anything that came to depend on it would work the day it was
    # written and raise `no such function` after the next restart.
    conn.create_function("jr_join_location", 2, join_location, deterministic=True)

    try:
        conn.execute("PRAGMA busy_timeout = 30000")
        conn.execute("BEGIN IMMEDIATE")
        # Re-read under the write lock. Between the unlocked read above and
        # this line another process could have migrated the same file, and
        # applying a step twice is what "ADD COLUMN" cannot survive.
        stamped_now = recorded_version(conn, path)
        confirmed = _BASELINE_VERSION if stamped_now is None else stamped_now
        for step in (s for s in _STEPS if s.to_version > confirmed):
            for statement in step.statements:
                conn.execute(statement)
        conn.execute(
            "INSERT INTO store_meta (key, value) VALUES ('schema_version', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (str(SCHEMA_VERSION),),
        )
        conn.commit()
    except Exception as exc:
        conn.rollback()
        # Only promise the copy when one was actually taken. A new store is
        # not backed up — it holds nothing to lose — and telling an operator
        # to look for a file that was deliberately never written is worse
        # than saying nothing.
        reassurance = (
            " Nothing was changed, and a copy of the store as it was is beside it."
            if not is_new
            else " Nothing was changed. The store was new, so no backup was taken."
        )
        raise ConfigError(
            f"store at {path} could not be carried from schema_version="
            f"{recorded} to {SCHEMA_VERSION}: {type(exc).__name__}: {exc}."
            + reassurance
        ) from exc
    finally:
        # Passing None removes it, so the store's connection leaves this
        # function exactly as it found it, migration or no migration.
        conn.create_function("jr_join_location", 2, None)

def backup_before_migrating(
    conn: sqlite3.Connection, path: Path, recorded: int
) -> None:
    """Copy the store beside itself before anything rewrites it.

    Taken through SQLite's own backup API rather than by copying the file,
    so the copy is a consistent store rather than a snapshot of a file with
    writes in flight — this store runs in WAL mode, where the file on disk
    is not the whole picture.

    Never deleted. A migration is the only operation here that rewrites a
    corpus in place, and the evidence in it is not reconstructible once the
    originals have left the analyst's hands.
    """
    destination = path.with_suffix(path.suffix + f".v{recorded}.bak")
    if destination.is_file():
        # Someone got here first. Two processes can open the same store on
        # the first run after an upgrade — `docker compose up` and
        # `docker compose run cli` share a data directory — and both read
        # the old version before either commits. Overwriting would replace
        # the genuine pre-migration copy with an already-migrated one, under
        # a name still claiming the old version. The existing file is the
        # older and therefore the more valuable of the two.
        #
        # `is_file`, not `exists`: something at this path that is not a file
        # is an obstruction, not a backup, and must still be reported.
        return
    try:
        with sqlite3.connect(destination) as copy:
            conn.backup(copy)
    except Exception as exc:
        raise ConfigError(
            f"store at {path} records schema_version={recorded} and needs to be "
            f"carried forward, but a backup could not be written to {destination}: "
            f"{type(exc).__name__}: {exc}. The migration has not run. Free space or "
            "fix permissions there, or move the store aside and reingest."
        ) from exc

def verify_meta(
    conn: sqlite3.Connection, path: Path, key: str, expected: str
) -> None:
    """Record a value on first boot; refuse to run if it later disagrees.

    For the contract fingerprint this is the guard that stops an existing
    corpus being appended to under different chunking or embedding rules.

    The caller holds the lock. This used to take `self._lock` itself; leaving
    that here would mean two modules deciding when the store's connection is
    guarded, and the answer has to come from one of them.
    """
    row = conn.execute(
        "SELECT value FROM store_meta WHERE key = ?", (key,)
    ).fetchone()
    if row is None:
        conn.execute(
            "INSERT INTO store_meta (key, value) VALUES (?, ?)", (key, expected)
        )
        conn.commit()
        return
    if row["value"] != expected:
        if key == "schema_version":
            # A schema that reaches here was not migratable, so the
            # identity remedy below does not apply: there is no
            # configuration to restore that would make this code
            # understand a shape it does not contain.
            raise ConfigError(
                f"store at {path} records schema_version={row['value']!r} "
                f"but this build produces {expected!r}, and it could not be "
                "carried forward. Move the store, its -wal and its -shm aside "
                "and reingest the casefiles."
            )
        raise ConfigError(
            f"store at {path} was created with {key}={row['value']!r} "
            f"but this instance is configured for {expected!r}. "
            "The corpus is only appendable under the rules that created it. "
            "Either restore the configuration the values above name, or "
            "reingest every casefile under the current one."
        )
