"""SQLite implementation of the storage port.

One file holds everything: casefile rows now, and — from M1 — document rows,
chunk text in an FTS5 index, and their vectors via sqlite-vec. Keeping text
and vectors in one transactional store is what makes it impossible for them
to drift apart, so there is no reconciliation problem to solve between them.
"""

from __future__ import annotations

import json
import re
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import sqlite_vec

from ..errors import ConfigError, ConflictError
from .port import Casefile, Chunk, Document, Mention, MentionFacet

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
# `_SIDECAR_TRIGGER` and the `chunk_vectors` statement in `initialize` are part
# of this freeze. They are separate artefacts, and leaving them out is how the
# ladder and the create path drift apart.
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


def _to_iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def _from_iso(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _row_to_casefile(row: sqlite3.Row) -> Casefile:
    return Casefile(
        id=row["id"],
        slug=row["slug"],
        title=row["title"],
        description=row["description"],
        created_at=_from_iso(row["created_at"]),
        updated_at=_from_iso(row["updated_at"]),
    )


_FTS_TOKEN = re.compile(r"[\w\u0400-\u04FF]+", re.UNICODE)


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _mention_filter(
    column: str, casefile_id: str, mention_kind: str, mention_value: str
) -> tuple[str, tuple[str, ...]]:
    """The clause that confines a search to passages carrying one identifier.

    Returned as a fragment and its parameters rather than as finished SQL. Only
    the *shape* of the clause varies — whether it is there at all, and whether
    it names a kind — and only the shape is composed. The identifier itself
    reaches SQLite as a bound parameter, so a value carrying a quote or a
    semicolon is matched rather than parsed.

    `column` names the chunk id in the query being assembled: `c.id` where
    `chunks` is joined under an alias, `id` where the clause sits inside a
    subquery already selecting from it. It is a literal from this module and
    never comes from a caller.

    An empty `mention_value` is no filter, including when a kind was named.
    Validating that combination belongs to the service layer, where the kinds
    are known; the store applies what it is given rather than forming an opinion
    of its own about it.

    The casefile is repeated inside the subquery although the query around it is
    already confined to one. It is the leading column of both mention indexes,
    and without it neither is usable — which turns the one read this table exists
    for into a scan of every mention in the store.
    """
    if not mention_value:
        return "", ()
    clause = (
        f" AND {column} IN (SELECT chunk_id FROM mentions"
        " WHERE casefile_id = ? AND normalised = ?"
    )
    parameters = (casefile_id, mention_value)
    if mention_kind:
        clause += " AND kind = ?"
        parameters += (mention_kind,)
    return clause + ")", parameters


def _row_to_document(row: sqlite3.Row) -> Document:
    return Document(
        id=row["id"],
        casefile_id=row["casefile_id"],
        content_hash=row["content_hash"],
        filename=row["filename"],
        media_type=row["media_type"],
        byte_size=row["byte_size"],
        extracted_text=row["extracted_text"],
        extractor=row["extractor"],
        text_source=row["text_source"],
        summary=row["summary"],
        summary_by=row["summary_by"],
        created_at=_from_iso(row["created_at"]),
        updated_at=_from_iso(row["updated_at"]),
        parent_id=row["parent_id"],
        containment_path=row["containment_path"],
        identity_path=row["identity_path"],
        child_count=row["child_count"] if "child_count" in row.keys() else 0,
    )


def _row_to_chunk(row: sqlite3.Row) -> Chunk:
    return Chunk(
        id=row["id"],
        document_id=row["document_id"],
        casefile_id=row["casefile_id"],
        ordinal=row["ordinal"],
        heading_path=row["heading_path"],
        text=row["text"],
        char_start=row["char_start"],
        char_end=row["char_end"],
        summary=row["summary"],
    )


class SqliteStore:
    """A single-file store guarded by one lock.

    Ingestion runs in a thread pool while the server is async, so the guard is
    a ``threading`` primitive rather than an asyncio one — it has to hold for
    worker threads, not just for coroutines.
    """

    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = threading.RLock()
        self._conn: sqlite3.Connection | None = None
        self._dimensions = 0

    # -- lifecycle ---------------------------------------------------------

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

    def initialize(self, contract_fingerprint: str, embed_dimensions: int) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self._path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.executescript(_SCHEMA)
        # The vector index is sized from the contract, so its width is part of
        # corpus identity and cannot drift from the embeddings it holds.
        conn.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS chunk_vectors "
            f"USING vec0(embedding float[{int(embed_dimensions)}])"
        )
        conn.executescript(self._SIDECAR_TRIGGER)
        conn.commit()
        self._conn = conn
        self._dimensions = int(embed_dimensions)

        # Carry the schema forward before corpus identity is compared. A store
        # that is migrated and then refused on identity is left improved and
        # undamaged, because every step is additive; the reverse order would
        # refuse a store this code could have read. It also keeps a future rung
        # free to rename the `store_meta` keys an identity check would read.
        self._migrate(conn)

        self._verify_meta("schema_version", str(SCHEMA_VERSION))
        self._verify_meta("contract_fingerprint", contract_fingerprint)

    # -- migration ---------------------------------------------------------

    def _recorded_version(self, conn: sqlite3.Connection) -> int | None:
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
                f"store at {self._path} records schema_version={row['value']!r}, which is "
                "not a version number. The file may not be a Jack Ryan store, or its "
                "metadata may be damaged; restore it from a backup."
            ) from None

    def _migrate(self, conn: sqlite3.Connection) -> None:
        """Carry an older store up the ladder, one transaction, backed up first.

        Ordering here is load-bearing and not obvious:

        The version is read once *outside* a transaction, the backup is taken,
        and the version is read *again* inside the write transaction that
        applies the steps. The first read is unlocked because SQLite's backup
        API cannot run inside a write transaction — so the re-read is not an
        optimisation to be tidied away, it is what makes the unlocked read safe.
        """
        stamped = self._recorded_version(conn)
        # An unstamped store was created by the baseline script a moment ago, so
        # it is at the baseline and holds nothing worth copying.
        is_new = stamped is None
        recorded = _BASELINE_VERSION if stamped is None else stamped

        if recorded == SCHEMA_VERSION:
            return

        if recorded > SCHEMA_VERSION:
            raise ConfigError(
                f"store at {self._path} was created by a newer version of Jack Ryan: it "
                f"records schema_version={recorded} and this build understands "
                f"{SCHEMA_VERSION}. A newer schema cannot be read by older code without "
                "guessing at what changed. Upgrade Jack Ryan, or open this store with "
                "the version that wrote it."
            )

        if recorded < _OLDEST_MIGRATABLE:
            raise ConfigError(
                f"store at {self._path} records schema_version={recorded}, which is older "
                f"than the oldest this build can carry forward ({_OLDEST_MIGRATABLE}). "
                "Move the store, its -wal and its -shm aside and reingest the casefiles."
            )

        pending = tuple(step for step in _STEPS if step.to_version > recorded)
        if not pending:
            return

        if not is_new:
            self._backup_before_migrating(conn, recorded)

        try:
            conn.execute("PRAGMA busy_timeout = 30000")
            conn.execute("BEGIN IMMEDIATE")
            # Re-read under the write lock. Between the unlocked read above and
            # this line another process could have migrated the same file, and
            # applying a step twice is what "ADD COLUMN" cannot survive.
            stamped_now = self._recorded_version(conn)
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
                f"store at {self._path} could not be carried from schema_version="
                f"{recorded} to {SCHEMA_VERSION}: {type(exc).__name__}: {exc}."
                + reassurance
            ) from exc

    def _backup_before_migrating(self, conn: sqlite3.Connection, recorded: int) -> None:
        """Copy the store beside itself before anything rewrites it.

        Taken through SQLite's own backup API rather than by copying the file,
        so the copy is a consistent store rather than a snapshot of a file with
        writes in flight — this store runs in WAL mode, where the file on disk
        is not the whole picture.

        Never deleted. A migration is the only operation here that rewrites a
        corpus in place, and the evidence in it is not reconstructible once the
        originals have left the analyst's hands.
        """
        destination = self._path.with_suffix(self._path.suffix + f".v{recorded}.bak")
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
                f"store at {self._path} records schema_version={recorded} and needs to be "
                f"carried forward, but a backup could not be written to {destination}: "
                f"{type(exc).__name__}: {exc}. The migration has not run. Free space or "
                "fix permissions there, or move the store aside and reingest."
            ) from exc

    def _verify_meta(self, key: str, expected: str) -> None:
        """Record a value on first boot; refuse to run if it later disagrees.

        For the contract fingerprint this is the guard that stops an existing
        corpus being appended to under different chunking or embedding rules.
        """
        assert self._conn is not None
        with self._lock:
            row = self._conn.execute(
                "SELECT value FROM store_meta WHERE key = ?", (key,)
            ).fetchone()
            if row is None:
                self._conn.execute(
                    "INSERT INTO store_meta (key, value) VALUES (?, ?)", (key, expected)
                )
                self._conn.commit()
                return
            if row["value"] != expected:
                if key == "schema_version":
                    # A schema that reaches here was not migratable, so the
                    # identity remedy below does not apply: there is no
                    # configuration to restore that would make this code
                    # understand a shape it does not contain.
                    raise ConfigError(
                        f"store at {self._path} records schema_version={row['value']!r} "
                        f"but this build produces {expected!r}, and it could not be "
                        "carried forward. Move the store, its -wal and its -shm aside "
                        "and reingest the casefiles."
                    )
                raise ConfigError(
                    f"store at {self._path} was created with {key}={row['value']!r} "
                    f"but this instance is configured for {expected!r}. "
                    "The corpus is only appendable under the rules that created it. "
                    "Either restore the configuration the values above name, or "
                    "reingest every casefile under the current one."
                )

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None

    @property
    def _db(self) -> sqlite3.Connection:
        if self._conn is None:
            raise RuntimeError("store used before initialize()")
        return self._conn

    # -- casefiles ---------------------------------------------------------

    def create_casefile(self, casefile: Casefile) -> Casefile:
        with self._lock:
            try:
                self._db.execute(
                    "INSERT INTO casefiles (id, slug, title, description, created_at, updated_at)"
                    " VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        casefile.id,
                        casefile.slug,
                        casefile.title,
                        casefile.description,
                        _to_iso(casefile.created_at),
                        _to_iso(casefile.updated_at),
                    ),
                )
                self._db.commit()
            except sqlite3.IntegrityError as exc:
                # Without this the failed statement keeps the WAL write lock,
                # and every other process is locked out of the database.
                self._db.rollback()
                raise ConflictError(f"a casefile with slug {casefile.slug!r} already exists") from exc
        return casefile

    def get_casefile(self, casefile_id: str) -> Casefile | None:
        with self._lock:
            row = self._db.execute(
                "SELECT * FROM casefiles WHERE id = ?", (casefile_id,)
            ).fetchone()
        return _row_to_casefile(row) if row else None

    def get_casefile_by_slug(self, slug: str) -> Casefile | None:
        with self._lock:
            row = self._db.execute(
                "SELECT * FROM casefiles WHERE slug = ?", (slug,)
            ).fetchone()
        return _row_to_casefile(row) if row else None

    def find_casefiles_by_id_prefix(self, prefix: str) -> list[Casefile]:
        # LIKE with an escaped prefix: ids are hex, but the escape keeps a
        # caller-supplied wildcard from turning a lookup into a scan match.
        pattern = _escape_like(prefix) + "%"
        with self._lock:
            rows = self._db.execute(
                "SELECT * FROM casefiles WHERE id LIKE ? ESCAPE '\\' ORDER BY created_at",
                (pattern,),
            ).fetchall()
        return [_row_to_casefile(row) for row in rows]

    def list_casefiles(self) -> list[Casefile]:
        with self._lock:
            rows = self._db.execute(
                "SELECT * FROM casefiles ORDER BY created_at DESC"
            ).fetchall()
        return [_row_to_casefile(row) for row in rows]

    def update_casefile(self, casefile: Casefile) -> Casefile:
        with self._lock:
            try:
                self._db.execute(
                    "UPDATE casefiles SET slug = ?, title = ?, description = ?, updated_at = ?"
                    " WHERE id = ?",
                    (
                        casefile.slug,
                        casefile.title,
                        casefile.description,
                        _to_iso(casefile.updated_at),
                        casefile.id,
                    ),
                )
                self._db.commit()
            except sqlite3.IntegrityError as exc:
                # Without this the failed statement keeps the WAL write lock,
                # and every other process is locked out of the database.
                self._db.rollback()
                raise ConflictError(f"a casefile with slug {casefile.slug!r} already exists") from exc
        return casefile

    def delete_casefile(self, casefile_id: str) -> bool:
        with self._lock:
            cursor = self._db.execute("DELETE FROM casefiles WHERE id = ?", (casefile_id,))
            self._db.commit()
            return cursor.rowcount > 0

    # -- documents ---------------------------------------------------------

    def upsert_document(self, document: Document) -> Document:
        with self._lock:
            self._db.execute(
                "INSERT INTO documents (id, casefile_id, content_hash, filename, media_type,"
                " byte_size, extracted_text, extractor, text_source, summary, summary_by,"
                " created_at, updated_at, parent_id, containment_path, identity_path)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
                " ON CONFLICT(casefile_id, content_hash, identity_path) DO UPDATE SET"
                "   filename = excluded.filename,"
                "   media_type = excluded.media_type,"
                "   byte_size = excluded.byte_size,"
                "   extracted_text = excluded.extracted_text,"
                "   extractor = excluded.extractor,"
                # Overwritten on reingest, not preserved: the value has to
                # describe the text now stored beside it. A document reingested
                # after the recognition engine changed was read by the new one.
                "   text_source = excluded.text_source,"
                # Overwritten on reingest for the same reason, one step further
                # out: the summary has to describe the text now stored beside
                # it. A document reingested after the summariser changed was
                # summarised by the new one, and `summary_by` has to say so or
                # it credits the wrong author for text it did not write.
                "   summary = excluded.summary,"
                "   summary_by = excluded.summary_by,"
                "   updated_at = excluded.updated_at,"
                "   parent_id = excluded.parent_id,"
                "   containment_path = excluded.containment_path",
                (
                    document.id,
                    document.casefile_id,
                    document.content_hash,
                    document.filename,
                    document.media_type,
                    document.byte_size,
                    document.extracted_text,
                    document.extractor,
                    document.text_source,
                    document.summary,
                    document.summary_by,
                    _to_iso(document.created_at),
                    _to_iso(document.updated_at),
                    document.parent_id,
                    document.containment_path,
                    document.identity_path,
                ),
            )
            self._db.commit()
        stored = self.find_document_by_hash(
            document.casefile_id, document.content_hash, document.identity_path
        )
        assert stored is not None
        return stored

    def get_document(self, document_id: str) -> Document | None:
        with self._lock:
            row = self._db.execute(
                "SELECT * FROM documents WHERE id = ?", (document_id,)
            ).fetchone()
        return _row_to_document(row) if row else None

    def find_document_by_hash(
        self, casefile_id: str, content_hash: str, identity_path: str = ""
    ) -> Document | None:
        """Find by identity: content, and for an expansion, where it was found.

        `identity_path` is empty for a file ingested directly, so two copies in
        one folder are one document. For an expansion it is the containment
        path, so the same bytes reached through two containers resolve to two
        documents and each keeps the link to what carried it.
        """
        with self._lock:
            row = self._db.execute(
                "SELECT * FROM documents"
                " WHERE casefile_id = ? AND content_hash = ? AND identity_path = ?",
                (casefile_id, content_hash, identity_path),
            ).fetchone()
        return _row_to_document(row) if row else None

    def list_children(self, document_id: str) -> list[Document]:
        with self._lock:
            rows = self._db.execute(
                "SELECT * FROM documents WHERE parent_id = ? ORDER BY containment_path",
                (document_id,),
            ).fetchall()
        return [_row_to_document(r) for r in rows]

    def ancestors(self, document_id: str) -> list[Document]:
        """The chain from the directly ingested file down to this document's parent.

        Bounded by the same depth the expansion budget allows, so a parent cycle
        introduced by a bug cannot spin here.
        """
        with self._lock:
            rows = self._db.execute(
                "WITH RECURSIVE chain(id, depth) AS ("
                "   SELECT parent_id, 1 FROM documents WHERE id = ?"
                "   UNION ALL"
                "   SELECT d.parent_id, chain.depth + 1 FROM documents d"
                "     JOIN chain ON d.id = chain.id"
                "     WHERE d.parent_id IS NOT NULL AND chain.depth < 64"
                " )"
                " SELECT documents.* FROM chain JOIN documents ON documents.id = chain.id"
                " ORDER BY chain.depth DESC",
                (document_id,),
            ).fetchall()
        return [_row_to_document(r) for r in rows]

    def delete_document(self, document_id: str) -> bool:
        """Delete a document and everything expanded out of it.

        Descendants and all three chunk sidecars go with it by cascade, declared
        in the schema rather than performed here, so a delete path written later
        cannot forget and leave the corpus with orphaned vector rows.
        """
        with self._lock:
            cursor = self._db.execute(
                "DELETE FROM documents WHERE id = ?", (document_id,)
            )
            self._db.commit()
            return cursor.rowcount > 0

    def descendant_ids(self, document_id: str) -> list[str]:
        """Every document expanded out of this one, at any depth."""
        with self._lock:
            rows = self._db.execute(
                "WITH RECURSIVE tree(id, depth) AS ("
                "   SELECT id, 0 FROM documents WHERE parent_id = ?"
                "   UNION ALL"
                "   SELECT d.id, tree.depth + 1 FROM documents d"
                "     JOIN tree ON d.parent_id = tree.id"
                "     WHERE tree.depth < 64"
                " )"
                " SELECT id FROM tree",
                (document_id,),
            ).fetchall()
        return [r["id"] for r in rows]

    def find_documents_by_id_prefix(self, casefile_id: str, prefix: str) -> list[Document]:
        pattern = _escape_like(prefix) + "%"
        with self._lock:
            rows = self._db.execute(
                "SELECT * FROM documents WHERE casefile_id = ? AND id LIKE ? ESCAPE '\\'"
                " ORDER BY created_at",
                (casefile_id, pattern),
            ).fetchall()
        return [_row_to_document(r) for r in rows]

    def list_documents(
        self, casefile_id: str, include_expanded: bool = False
    ) -> list[Document]:
        """A casefile's documents, newest first.

        Expanded children are excluded unless asked for: three archives that
        expand to forty thousand documents are three things an analyst put in,
        and an inventory that returns forty thousand rows is not an inventory.
        Each row carries how many children it has, so a caller can see there is
        more to reach without paying to fetch it.
        """
        clause = "" if include_expanded else " AND d.parent_id IS NULL"
        with self._lock:
            rows = self._db.execute(
                "SELECT d.*, ("
                "   SELECT COUNT(*) FROM documents c WHERE c.parent_id = d.id"
                " ) AS child_count"
                " FROM documents d"
                f" WHERE d.casefile_id = ?{clause}"
                " ORDER BY d.created_at DESC",
                (casefile_id,),
            ).fetchall()
        return [_row_to_document(r) for r in rows]

    # -- chunks ------------------------------------------------------------

    def replace_chunks(
        self,
        document_id: str,
        chunks: list[Chunk],
        embeddings: list[list[float]],
        mentions: list[Mention],
    ) -> None:
        """Replace a document's chunks, full-text entries, vectors and mentions.

        One transaction covers all four, so a chunk whose text is stored without
        its vector is not a state the store can be left in — and neither is a
        mention pointing at a chunk from the ingest before this one. A mention
        naming a chunk that is not among those being written violates its foreign
        key, which fails the whole call rather than storing a reference nothing
        can resolve.
        """
        if len(chunks) != len(embeddings):
            raise ValueError("each chunk must have exactly one embedding")
        for embedding in embeddings:
            if len(embedding) != self._dimensions:
                raise ConfigError(
                    f"embedding has width {len(embedding)} but the contract declares "
                    f"{self._dimensions}; refusing to store it"
                )

        with self._lock:
            db = self._db
            try:
                db.execute("BEGIN")
                # The AFTER DELETE trigger clears the full-text and vector rows,
                # so this one statement retires all three.
                db.execute("DELETE FROM chunks WHERE document_id = ?", (document_id,))

                for chunk, embedding in zip(chunks, embeddings):
                    cursor = db.execute(
                        "INSERT INTO chunks (id, document_id, casefile_id, ordinal,"
                        " heading_path, text, char_start, char_end, summary)"
                        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            chunk.id,
                            chunk.document_id,
                            chunk.casefile_id,
                            chunk.ordinal,
                            chunk.heading_path,
                            chunk.text,
                            chunk.char_start,
                            chunk.char_end,
                            chunk.summary,
                        ),
                    )
                    rowid = cursor.lastrowid
                    # `chunk.text`, never the folded text: the full-text index
                    # answers for what the document contains, and a model's
                    # summary of it is not that.
                    db.execute(
                        "INSERT INTO chunks_fts(rowid, text) VALUES (?, ?)", (rowid, chunk.text)
                    )
                    db.execute(
                        "INSERT INTO chunk_vectors(rowid, embedding) VALUES (?, ?)",
                        (rowid, json.dumps(list(embedding))),
                    )
                # After the chunks and not before: `mentions.chunk_id` is a
                # foreign key onto `chunks.id`, the constraint is immediate, and
                # a mention inserted first would have no parent to reference.
                # `executemany`, because nothing has to be read back per row —
                # unlike the chunk inserts above, each of which needs its own
                # rowid in order to address the two sidecars.
                #
                # `document_id`, `casefile_id` and the document offset are taken
                # from the chunk this mention names, not from the mention itself.
                # The foreign keys prove only that those ids exist somewhere;
                # nothing makes them agree with the chunk. A row whose
                # denormalised casefile disagreed would appear in another
                # casefile's inventory — a compartment breach, and a casefile is
                # the compartment. Reviewed and demonstrated: a mention naming a
                # chunk in one casefile and a `casefile_id` in another was
                # accepted, and the second casefile's facet then advertised an
                # identifier that existed only in the first's text. Deriving them
                # here makes that unreachable rather than merely unused, which
                # matters because this registry is advertised as the seam a
                # second, model-backed producer arrives through.
                by_id = {chunk.id: chunk for chunk in chunks}
                rows = []
                for mention in mentions:
                    parent = by_id.get(mention.chunk_id)
                    if parent is None:
                        # Named a chunk that is not being written. The foreign
                        # key would refuse it; refused here instead so the
                        # message names the mention rather than the constraint.
                        raise ConfigError(
                            f"a {mention.kind} mention names chunk "
                            f"{mention.chunk_id!r}, which is not among the "
                            f"{len(chunks)} chunks being written for this document"
                        )
                    rows.append(
                        (
                            mention.chunk_id,
                            parent.document_id,
                            parent.casefile_id,
                            mention.kind,
                            mention.value,
                            mention.normalised,
                            mention.char_start,
                            mention.char_end,
                            # Where this identifier sits in the *document*, so a
                            # facet can count textual occurrences rather than
                            # rows. Chunks overlap by the contract's overlap, so
                            # an identifier near a boundary is extracted from two
                            # chunks of one document and would otherwise be
                            # counted twice — making "how many times it was
                            # mentioned" wrong by exactly the overlap.
                            parent.char_start + mention.char_start,
                            mention.extractor,
                            mention.confidence,
                        )
                    )
                db.executemany(
                    "INSERT INTO mentions (chunk_id, document_id, casefile_id, kind,"
                    " value, normalised, char_start, char_end, document_offset,"
                    " extractor, confidence)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    rows,
                )
                db.commit()
            except Exception:
                db.rollback()
                raise

    def get_chunks(self, chunk_ids: list[str]) -> dict[str, Chunk]:
        if not chunk_ids:
            return {}
        placeholders = ",".join("?" for _ in chunk_ids)
        with self._lock:
            rows = self._db.execute(
                f"SELECT * FROM chunks WHERE id IN ({placeholders})", tuple(chunk_ids)
            ).fetchall()
        return {row["id"]: _row_to_chunk(row) for row in rows}

    def find_chunks_by_id_prefix(self, casefile_id: str, prefix: str) -> list[Chunk]:
        pattern = _escape_like(prefix) + "%"
        with self._lock:
            rows = self._db.execute(
                "SELECT * FROM chunks WHERE casefile_id = ? AND id LIKE ? ESCAPE '\\'"
                " ORDER BY document_id, ordinal",
                (casefile_id, pattern),
            ).fetchall()
        return [_row_to_chunk(row) for row in rows]

    def casefile_statistics(self, casefile_id: str) -> dict[str, object]:
        """Counts and sizes computed in the database.

        Loading every document's text to measure it costs the whole corpus in
        memory for a handful of integers.
        """
        with self._lock:
            totals = self._db.execute(
                "SELECT COUNT(*) AS documents,"
                "       COALESCE(SUM(parent_id IS NULL), 0) AS ingested,"
                "       COALESCE(SUM(parent_id IS NOT NULL), 0) AS expanded,"
                "       COALESCE(SUM(LENGTH(extracted_text)), 0) AS characters"
                " FROM documents WHERE casefile_id = ?",
                (casefile_id,),
            ).fetchone()
            by_type = self._db.execute(
                "SELECT media_type, COUNT(*) AS count FROM documents WHERE casefile_id = ?"
                " GROUP BY media_type ORDER BY media_type",
                (casefile_id,),
            ).fetchall()
        # Split rather than one figure: a casefile of three archives holding
        # forty thousand documents is both "3" and "40,003", and a count that
        # does not say which it means misrepresents the size of the corpus.
        return {
            "documents": totals["documents"],
            "documents_ingested": totals["ingested"],
            "documents_expanded": totals["expanded"],
            "characters": totals["characters"],
            "by_type": {(r["media_type"] or "unknown"): r["count"] for r in by_type},
        }

    def get_document_chunks_around(
        self, document_id: str, ordinal: int, radius: int
    ) -> list[Chunk]:
        """A chunk's neighbours within a document, so a passage can be read in context."""
        with self._lock:
            rows = self._db.execute(
                "SELECT * FROM chunks WHERE document_id = ? AND ordinal BETWEEN ? AND ?"
                " ORDER BY ordinal",
                (document_id, ordinal - int(radius), ordinal + int(radius)),
            ).fetchall()
        return [_row_to_chunk(row) for row in rows]

    # -- retrieval ---------------------------------------------------------

    def search_keyword(
        self,
        casefile_id: str,
        query: str,
        limit: int,
        mention_kind: str = "",
        mention_value: str = "",
    ) -> list[str]:
        """Rank chunks by full-text relevance, returning chunk ids in order.

        Every term is quoted so that user text is matched as words rather than
        interpreted as FTS5 operators.

        A mention filter is applied inside this query, never to the ids it
        returns. The caller asks for a bounded number of candidates, so removing
        the non-matching ones afterwards would discard every matching chunk that
        ranked below that depth unfiltered — on a corpus of any size, nearly all
        of them. The caller would then be told that nothing carries the
        identifier while the store held exactly what it asked for, which is the
        one wrong answer an evidence tool must not give.
        """
        terms = [t for t in _FTS_TOKEN.findall(query) if t]
        if not terms:
            return []
        match = " OR ".join(f'"{t}"' for t in terms)
        predicate, carrying = _mention_filter(
            "c.id", casefile_id, mention_kind, mention_value
        )
        with self._lock:
            rows = self._db.execute(
                "SELECT c.id AS id FROM chunks_fts f"
                " JOIN chunks c ON c.rowid = f.rowid"
                " WHERE chunks_fts MATCH ? AND c.casefile_id = ?"
                f"{predicate}"
                " ORDER BY bm25(chunks_fts) LIMIT ?",
                (match, casefile_id, *carrying, int(limit)),
            ).fetchall()
        return [row["id"] for row in rows]

    def search_vector(
        self,
        casefile_id: str,
        embedding: list[float],
        limit: int,
        mention_kind: str = "",
        mention_value: str = "",
    ) -> list[str]:
        """Rank chunks by vector distance, returning chunk ids nearest first."""
        if len(embedding) != self._dimensions:
            raise ConfigError(
                f"query embedding has width {len(embedding)} but the contract declares "
                f"{self._dimensions}"
            )
        predicate, carrying = _mention_filter(
            "id", casefile_id, mention_kind, mention_value
        )
        with self._lock:
            # The casefile constraint goes inside the MATCH, so the nearest
            # neighbours are the nearest *in this casefile*. Filtering after a
            # global KNN would silently lose hits whenever another casefile
            # owned the top of the list.
            #
            # The mention filter sits in the same subquery, beside it, because it
            # is the same argument: the KNN returns a bounded number of
            # neighbours, so a filter applied to what it returned loses every
            # match that was not already among the nearest overall. Both decide
            # which vectors are candidates, and neither touches how the
            # candidates rank.
            rows = self._db.execute(
                "SELECT c.id AS id FROM ("
                "  SELECT rowid, distance FROM chunk_vectors"
                "  WHERE embedding MATCH ?"
                "    AND rowid IN (SELECT rowid FROM chunks WHERE casefile_id = ?"
                f"{predicate})"
                "  ORDER BY distance LIMIT ?"
                ") v JOIN chunks c ON c.rowid = v.rowid ORDER BY v.distance",
                (json.dumps(list(embedding)), casefile_id, *carrying, int(limit)),
            ).fetchall()
        return [row["id"] for row in rows]

    # -- mentions ----------------------------------------------------------

    def mention_facets(
        self, casefile_id: str, kind: str, limit: int
    ) -> list[MentionFacet]:
        """Count a casefile's identifiers, most mentioned first.

        One GROUP BY, counted in the database: fetching a casefile's mentions in
        order to count them in Python costs the whole table in memory for a
        handful of integers, and the service layer holds no SQL.

        The order is made total deliberately. The mention count decides it, and
        where two identifiers were mentioned equally often the normalised value
        and then the kind decide the rest. Left at the count alone, two equal
        entries would come back in whatever order the query plan happened to
        produce, and anything comparing this list with a previous one — a test,
        or a surface showing a table an analyst expects to be the same between
        two looks — would disagree with itself for no reason it could see.

        `mentions` counts distinct textual occurrences, not rows. Chunks overlap
        by the contract's overlap, so an identifier near a boundary is extracted
        from two chunks of one document and `COUNT(*)` reported it twice — which
        made "how many times it was mentioned" wrong by exactly the overlap, and
        wrong invisibly, since nothing in the number said which occurrences were
        the same one seen twice. Counting distinct `(document_id,
        document_offset)` pairs is exact: one occurrence has one offset in its
        document however many chunks it lands in.
        """
        clause = " AND kind = ?" if kind else ""
        selection = (casefile_id, kind) if kind else (casefile_id,)
        with self._lock:
            rows = self._db.execute(
                "SELECT kind, normalised AS value,"
                "       COUNT(DISTINCT document_id || ':' || document_offset) AS mentions,"
                "       COUNT(DISTINCT document_id) AS documents"
                " FROM mentions"
                f" WHERE casefile_id = ?{clause}"
                " GROUP BY kind, normalised"
                " ORDER BY mentions DESC, value, kind"
                " LIMIT ?",
                (*selection, int(limit)),
            ).fetchall()
        return [
            MentionFacet(
                kind=row["kind"],
                value=row["value"],
                mentions=row["mentions"],
                documents=row["documents"],
            )
            for row in rows
        ]
