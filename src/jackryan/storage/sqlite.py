"""SQLite implementation of the storage port.

One file holds everything: casefile rows now, and — from M1 — document rows,
chunk text in an FTS5 index, and their vectors via sqlite-vec. Keeping text
and vectors in one transactional store is what makes it impossible for them
to drift apart, so there is no reconciliation problem to solve between them.
That "one file" is the database, not this module: the schema and its migration
ladder live in `migrations.py`, and the read queries in `retrieval.py`.

What stays here is the connection, the lock, the row mappers, the CRUD, and
`replace_chunks` — which is whole and stays whole, because its single
transaction across a chunk's text, its FTS entry and its vector is the
guarantee this seam exists to make.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

import sqlite_vec

from ..errors import ConfigError, ConflictError
from . import migrations, retrieval
from .port import Casefile, CasefileStatistics, Chunk, Document, Mention, MentionFacet


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

    def initialize(self, contract_fingerprint: str, embed_dimensions: int) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self._path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        # The baseline script, the vector table and the delete trigger are one
        # frozen shape, created together — see `migrations._SCHEMA`.
        migrations.create_baseline(conn, embed_dimensions)
        conn.commit()
        self._conn = conn
        self._dimensions = int(embed_dimensions)

        # Carry the schema forward before corpus identity is compared. A store
        # that is migrated and then refused on identity is left improved and
        # undamaged, because every step is additive; the reverse order would
        # refuse a store this code could have read. It also keeps a future rung
        # free to rename the `store_meta` keys an identity check would read.
        migrations.migrate(conn, self._path)

        # The lock is taken here rather than inside `migrations`: the store owns
        # its connection, so it owns when the connection is guarded. Two modules
        # answering that question is one answer too many.
        with self._lock:
            migrations.verify_meta(
                conn, self._path, "schema_version", str(migrations.SCHEMA_VERSION)
            )
            migrations.verify_meta(
                conn, self._path, "contract_fingerprint", contract_fingerprint
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

    def casefile_statistics(self, casefile_id: str) -> CasefileStatistics:
        """Counts and sizes computed in the database.

        Loading every document's text to measure it costs the whole corpus in
        memory for a handful of integers.

        The SQL aliases and the returned field names differ on purpose, and the
        mapping is written out below rather than splatted: `ingested` and
        `expanded` are readable beside `COUNT(*) AS documents` in a query, and
        unreadable on their own in a payload.
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
        return CasefileStatistics(
            documents=totals["documents"],
            documents_ingested=totals["ingested"],
            documents_expanded=totals["expanded"],
            characters=totals["characters"],
            by_type={(r["media_type"] or "unknown"): r["count"] for r in by_type},
        )

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

    def list_document_ids(self, casefile_id: str) -> list[str]:
        """Identifiers only, so a maintenance pass need not hold the corpus.

        `list_documents` carries every row's extracted text, which is the whole
        of a casefile. Ordered so a run over it is reproducible.
        """
        with self._lock:
            rows = self._db.execute(
                "SELECT id FROM documents WHERE casefile_id = ?"
                " ORDER BY created_at, id",
                (casefile_id,),
            ).fetchall()
        return [row["id"] for row in rows]

    def list_document_chunks(self, document_id: str) -> list[Chunk]:
        with self._lock:
            rows = self._db.execute(
                "SELECT * FROM chunks WHERE document_id = ? ORDER BY ordinal",
                (document_id,),
            ).fetchall()
        return [_row_to_chunk(row) for row in rows]

    def recompute_mention_offsets(self, text_starts: dict[str, int]) -> int:
        """Only `document_offset`, and only where it differs.

        The derivation is the one `replace_chunks` makes at write time — the
        chunk's start plus the mention's own chunk-relative offset — from a
        start the caller established against the document's text rather than
        from the one recorded on the chunk.

        The `<>` predicate is what makes a repeated run report nothing rather
        than rewriting every row and claiming a correction.
        """
        if not text_starts:
            return 0
        with self._lock:
            db = self._db
            try:
                cursor = db.executemany(
                    "UPDATE mentions SET document_offset = ? + char_start"
                    " WHERE chunk_id = ? AND document_offset <> ? + char_start",
                    [(start, chunk_id, start) for chunk_id, start in text_starts.items()],
                )
                changed = cursor.rowcount
                db.commit()
            except Exception:
                db.rollback()
                raise
        return changed

    # -- retrieval ---------------------------------------------------------
    #
    # The queries live in `retrieval.py`; these take the lock and hand over the
    # connection. Read them there rather than here — each carries the argument
    # for why its predicates are inside the SQL, and a predicate added to the
    # wrong side of that line is the most damaging wrong answer this tool can
    # give.

    def search_keyword(
        self,
        casefile_id: str,
        query: str,
        limit: int,
        mention_kind: str = "",
        mention_value: str = "",
    ) -> list[str]:
        with self._lock:
            return retrieval.search_keyword(
                self._db, casefile_id, query, limit, mention_kind, mention_value
            )

    def search_vector(
        self,
        casefile_id: str,
        embedding: list[float],
        limit: int,
        mention_kind: str = "",
        mention_value: str = "",
    ) -> list[str]:
        with self._lock:
            return retrieval.search_vector(
                self._db,
                self._dimensions,
                casefile_id,
                embedding,
                limit,
                mention_kind,
                mention_value,
            )

    # -- mentions ----------------------------------------------------------

    def mention_facets(
        self, casefile_id: str, kind: str, limit: int
    ) -> list[MentionFacet]:
        with self._lock:
            return retrieval.mention_facets(self._db, casefile_id, kind, limit)

