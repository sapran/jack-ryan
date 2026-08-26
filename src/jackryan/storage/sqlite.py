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
from datetime import datetime, timezone
from pathlib import Path

import sqlite_vec

from ..errors import ConfigError, ConflictError
from .port import Casefile, Chunk, Document

SCHEMA_VERSION = 4

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

        self._verify_meta("schema_version", str(SCHEMA_VERSION))
        self._verify_meta("contract_fingerprint", contract_fingerprint)

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
                " byte_size, extracted_text, extractor, created_at, updated_at,"
                " parent_id, containment_path, identity_path)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
                " ON CONFLICT(casefile_id, content_hash, identity_path) DO UPDATE SET"
                "   filename = excluded.filename,"
                "   media_type = excluded.media_type,"
                "   byte_size = excluded.byte_size,"
                "   extracted_text = excluded.extracted_text,"
                "   extractor = excluded.extractor,"
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
        self, document_id: str, chunks: list[Chunk], embeddings: list[list[float]]
    ) -> None:
        """Replace a document's chunks, full-text entries, and vectors atomically.

        One transaction covers all three, so a chunk whose text is stored
        without its vector is not a state the store can be left in.
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
                        " heading_path, text, char_start, char_end)"
                        " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            chunk.id,
                            chunk.document_id,
                            chunk.casefile_id,
                            chunk.ordinal,
                            chunk.heading_path,
                            chunk.text,
                            chunk.char_start,
                            chunk.char_end,
                        ),
                    )
                    rowid = cursor.lastrowid
                    db.execute(
                        "INSERT INTO chunks_fts(rowid, text) VALUES (?, ?)", (rowid, chunk.text)
                    )
                    db.execute(
                        "INSERT INTO chunk_vectors(rowid, embedding) VALUES (?, ?)",
                        (rowid, json.dumps(list(embedding))),
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

    def search_keyword(self, casefile_id: str, query: str, limit: int) -> list[str]:
        """Rank chunks by full-text relevance, returning chunk ids in order.

        Every term is quoted so that user text is matched as words rather than
        interpreted as FTS5 operators.
        """
        terms = [t for t in _FTS_TOKEN.findall(query) if t]
        if not terms:
            return []
        match = " OR ".join(f'"{t}"' for t in terms)
        with self._lock:
            rows = self._db.execute(
                "SELECT c.id AS id FROM chunks_fts f"
                " JOIN chunks c ON c.rowid = f.rowid"
                " WHERE chunks_fts MATCH ? AND c.casefile_id = ?"
                " ORDER BY bm25(chunks_fts) LIMIT ?",
                (match, casefile_id, int(limit)),
            ).fetchall()
        return [row["id"] for row in rows]

    def search_vector(self, casefile_id: str, embedding: list[float], limit: int) -> list[str]:
        """Rank chunks by vector distance, returning chunk ids nearest first."""
        if len(embedding) != self._dimensions:
            raise ConfigError(
                f"query embedding has width {len(embedding)} but the contract declares "
                f"{self._dimensions}"
            )
        with self._lock:
            # The casefile constraint goes inside the MATCH, so the nearest
            # neighbours are the nearest *in this casefile*. Filtering after a
            # global KNN would silently lose hits whenever another casefile
            # owned the top of the list.
            rows = self._db.execute(
                "SELECT c.id AS id FROM ("
                "  SELECT rowid, distance FROM chunk_vectors"
                "  WHERE embedding MATCH ?"
                "    AND rowid IN (SELECT rowid FROM chunks WHERE casefile_id = ?)"
                "  ORDER BY distance LIMIT ?"
                ") v JOIN chunks c ON c.rowid = v.rowid ORDER BY v.distance",
                (json.dumps(list(embedding)), casefile_id, int(limit)),
            ).fetchall()
        return [row["id"] for row in rows]
