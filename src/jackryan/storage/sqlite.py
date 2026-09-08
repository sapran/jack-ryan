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
from .port import (
    Casefile,
    CasefileStatistics,
    Chunk,
    Document,
    DocumentLocation,
    DocumentLocationSet,
    DocumentPage,
    IngestionCoverage,
    IngestRun,
    Mention,
    MentionCarrier,
    MentionDocumentPage,
    MentionFacet,
)


def _to_iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def _from_iso(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _document_selection(
    include_expanded: bool, parent_id: str | None
) -> tuple[str, str, str]:
    """The predicate, the ordering and the selection's name — decided once.

    Returned together rather than computed at each call site because the page
    and the count must run under the *same* predicate: a total counted under a
    wider predicate than the rows silently tells a caller there is more, and one
    counted under a narrower predicate hides evidence behind a `truncated` of
    false. This is the same argument the mention filter makes for living inside
    the retrievers' SQL rather than over their results.

    Two orderings, because the two selections are read for different reasons. A
    casefile's intake is chronological — newest first is what an analyst who has
    just ingested something wants. A container's contents share their parent's
    ingest instant almost exactly, so `created_at` orders them arbitrarily while
    the containment path orders them the way the container does.

    Every ordering ends in `d.id`, which is unique, so each is a total order and
    a page boundary cannot land in the middle of a tie. That is deliberately
    unlike the fused-ranking rule, which forbids breaking a tie by an identifier:
    that rule exists so two stores built from the same documents rank alike, and
    document ids differ between stores. Here the requirement is only that one
    unchanged store pages consistently, and `d.id` is reached only when two
    documents are equal on every corpus value before it.

    No test exercises the tie-break, and that is a property of the corpus rather
    than a gap in the tests: `created_at` is a per-document `datetime.now()` at
    microsecond resolution, and two siblings cannot share a containment path, so
    ingestion cannot produce two documents equal on every key before `d.id`.
    Removing the trailing keys was mutated and left the suite green. They stay
    because a total order is what `mcp-tool-surface` requires and because
    uniqueness that rests on clock resolution stops being true quietly — a
    coarser clock, a restored backup, or a bulk insert sharing one timestamp is
    all it takes. Do not "simplify" them on the strength of a green suite.
    """
    if parent_id is not None:
        return (
            " AND d.parent_id = ?",
            " ORDER BY d.containment_path, d.created_at, d.id",
            "children",
        )
    if include_expanded:
        return "", " ORDER BY d.created_at DESC, d.containment_path, d.id", "all"
    return (
        " AND d.parent_id IS NULL",
        " ORDER BY d.created_at DESC, d.containment_path, d.id",
        "ingested",
    )


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
        # A real column, so it is read directly: every query feeding this
        # function selects `*` or `d.*`, and a guard would only mask one that
        # forgot it. `location_count` is aliased by the listing query alone,
        # so it takes the same guard `child_count` above does.
        locations_recorded=bool(row["locations_recorded"]),
        location_count=row["location_count"] if "location_count" in row.keys() else 0,
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
                " created_at, updated_at, parent_id, containment_path, identity_path,"
                " locations_recorded)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
                " ON CONFLICT(casefile_id, content_hash, identity_path) DO UPDATE SET"
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
                # `filename` and `containment_path` are deliberately absent from
                # this list, like `created_at` above: they are the *first*
                # location this document's bytes were observed at, and a later
                # copy found elsewhere must not overwrite them. Every observed
                # location is kept in `document_locations`; this column is the
                # one a citation names, so it has to be stable or a citation
                # written yesterday points somewhere else today.
                #
                # `locations_recorded` is absent for a different reason: only an
                # insert can honestly claim that the location record is whole
                # from the start. A document migrated in from an older schema
                # must keep saying it predates the record however often it is
                # reingested.
                "   parent_id = excluded.parent_id",
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
                    int(document.locations_recorded),
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

    def record_document_location(
        self,
        document_id: str,
        source_root: str,
        containment_path: str,
        first_seen_at: datetime,
    ) -> bool:
        # INSERT OR IGNORE, never OR REPLACE: the first observation's timestamp
        # is the fact worth keeping, and the return value is how the caller
        # tells a newly discovered copy from an ordinary reingest of a known
        # one. OR REPLACE would report every reingest as a discovery.
        with self._lock:
            cursor = self._db.execute(
                "INSERT OR IGNORE INTO document_locations"
                " (document_id, source_root, containment_path, first_seen_at)"
                " VALUES (?, ?, ?, ?)",
                (document_id, source_root, containment_path, _to_iso(first_seen_at)),
            )
            self._db.commit()
            return cursor.rowcount > 0

    def document_locations(self, document_id: str, limit: int) -> DocumentLocationSet:
        """One document's recorded locations, bounded, and how many there are.

        Ordered by when each was first observed and then by the location itself,
        so the ordering is total: two locations recorded inside one ingest run
        can share a timestamp, and a bound falling inside a tie would return a
        different subset between two calls on an unchanged corpus.

        The earliest is returned first, which is what lets a caller identify the
        one the document itself reports without comparing strings against it.
        """
        with self._lock:
            total = self._db.execute(
                "SELECT COUNT(*) AS total FROM document_locations WHERE document_id = ?",
                (document_id,),
            ).fetchone()["total"]
            rows = self._db.execute(
                "SELECT source_root, containment_path, first_seen_at"
                " FROM document_locations WHERE document_id = ?"
                " ORDER BY first_seen_at, source_root, containment_path"
                " LIMIT ?",
                (document_id, int(limit)),
            ).fetchall()
        return DocumentLocationSet(
            locations=[
                DocumentLocation(
                    source_root=r["source_root"],
                    containment_path=r["containment_path"],
                    first_seen_at=_from_iso(r["first_seen_at"]),
                )
                for r in rows
            ],
            total=total,
        )

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

    def list_document_page(
        self,
        casefile_id: str,
        include_expanded: bool = False,
        parent_id: str | None = None,
        offset: int = 0,
        limit: int = -1,
    ) -> DocumentPage:
        """One page of a casefile's documents, and how many the selection holds.

        Each row carries how many children it has, so a caller can see there is
        more to reach without paying to fetch it — and so a container nested
        inside another is markable, which the children selection is the whole
        reason for.

        `offset` is floored here as well as in the service, because the reported
        `offset` must be the one SQLite actually applied: it is what
        `continue_from` is computed from, and SQLite silently treats a negative
        OFFSET as zero. A page that returned the first rows while reporting
        `offset=-2` would hand back a `continue_from` of 0 and repeat them. The
        service is the only caller that clamps, and the tests reach this method
        directly, so the hole was one positional argument away.

        `limit` is either negative, meaning unbounded, or at least 1. A `limit`
        of 0 returns no rows while the count still reports the selection's
        size, so `truncated` stays true and a caller following `continue_from`
        never advances. The service clamps it to at least 1; this method does
        not second-guess a deliberate negative.
        """
        clause, order, selection = _document_selection(include_expanded, parent_id)
        predicate = f" WHERE d.casefile_id = ?{clause}"
        start = max(0, int(offset))
        binds: tuple[object, ...] = (
            (casefile_id,) if parent_id is None else (casefile_id, parent_id)
        )
        with self._lock:
            total = self._db.execute(
                f"SELECT COUNT(*) AS total FROM documents d{predicate}", binds
            ).fetchone()["total"]
            # The page is chosen on a narrow query and widened afterwards.
            # Ordering `SELECT d.*` directly puts `extracted_text` through the
            # sorter, so a single page of a 40,000-document casefile would cost
            # the whole corpus's text in memory — the exact cost this page
            # exists to avoid.
            rows = self._db.execute(
                "SELECT d.*, ("
                "   SELECT COUNT(*) FROM documents c WHERE c.parent_id = d.id"
                " ) AS child_count, ("
                # Same shape and the same order of cost as the child count
                # already paid, and it is what makes "which documents were
                # found in several places" answerable by scanning a listing
                # rather than by opening every document in turn.
                "   SELECT COUNT(*) FROM document_locations l WHERE l.document_id = d.id"
                " ) AS location_count"
                " FROM documents d"
                " JOIN (SELECT d.id FROM documents d"
                f"{predicate}{order} LIMIT ? OFFSET ?) chosen ON chosen.id = d.id"
                # Repeated deliberately, and it is insurance rather than an
                # observed necessity — the distinction is worth stating,
                # because the obvious comment here is an overstatement.
                # SQL guarantees nothing about the row order a join produces,
                # so the subquery's ordering is not inherited. Measured on this
                # SQLite, `EXPLAIN QUERY PLAN` reports `SCAN chosen` driving
                # the join and probing `d` by primary key, which happens to
                # emit the subquery's order; a sweep at 6, 20, 60, 200 and 600
                # children paged correctly with this line removed. It stays
                # because that plan is a choice SQLite is free to change — an
                # added index or a future planner would silently reorder pages
                # — and because `mcp-tool-surface` requires paging to repeat
                # and omit nothing. Removing it cannot be caught by a test
                # through the public path, which is the reason to keep it, not
                # a reason to drop it.
                f"{order}",
                (*binds, int(limit), start),
            ).fetchall()
        return DocumentPage(
            documents=[_row_to_document(r) for r in rows],
            total_matching=total,
            offset=start,
            limit=int(limit),
            selection=selection,
        )

    def documents_with_mention(
        self,
        casefile_id: str,
        mention_kind: str,
        mention_value: str,
        offset: int,
        limit: int,
    ) -> MentionDocumentPage:
        """Every document carrying one identifier, one page, and the set's size.

        Three statements under one lock, all three composing the *same*
        predicate string and binds: the count, the page, and the passage to cite
        per returned document.

        The page is chosen on a query that touches only `mentions` and the two
        small `documents` columns it orders by, and widened afterwards. Ordering
        `SELECT d.*` directly puts `extracted_text` through the sorter, which is
        the whole cost this page exists to avoid — a page of a real casefile
        would carry megabytes of text to report a handful of integers.

        The ordering leads with the occurrence count, so the most heavily
        carrying document is reached first, and ends in `d.id`, which is unique,
        so it is a total order and a page boundary cannot land inside a tie.
        That is deliberately unlike the fused-ranking rule, which forbids
        breaking a tie by an identifier: that rule exists so two stores built
        from the same documents rank alike, and document ids differ between
        stores. Here the requirement is only that one unchanged store pages
        consistently, and `d.id` is reached only where two documents are equal
        on the count, the containment path and the creation time before it.
        `containment_path` is the corpus-derived key, as it is for the children
        selection above, and is set for every document — a folder walk records
        each file's relative path, a single file its name.

        **Every join to `documents` and `chunks` re-checks the casefile.** The
        shared predicate constrains `mentions` only, so without those the
        confinement would rest entirely on the denormalised
        `mentions.casefile_id`. A row whose `casefile_id` named one casefile
        while its `document_id` pointed into another would disclose that other
        casefile's document metadata and a citable passage id inside a read
        scoped to this one. `replace_chunks` cannot currently write such a row —
        it derives both columns from the chunk being stored — but a security
        review of `mentions-and-facets` planted exactly that row and found
        `mention_facets` advertising it, while both retrievers survived because
        they constrain the casefile twice. This query has the retrievers' shape
        rather than the facet's, and the indexes for it already exist.
        """
        body, binds = retrieval.mention_predicate(
            "m", casefile_id, mention_kind, mention_value
        )
        # Both bounds floored here as well as in the service, for the reason
        # `list_document_page` gives: the reported values must be the ones
        # SQLite applied, because `continue_from` is computed from them and the
        # tests reach this method directly. A `limit` of 0 is the quiet one — it
        # returns no rows while the count still reports the whole carrier set,
        # so `truncated` stays true and a caller following `continue_from` never
        # advances. Unlike `list_document_page`, this method offers no unbounded
        # form, so there is no deliberate negative to preserve.
        start = max(0, int(offset))
        page = max(1, int(limit))
        with self._lock:
            total = self._db.execute(
                "SELECT COUNT(DISTINCT m.document_id) AS total FROM mentions m"
                " JOIN documents td ON td.id = m.document_id"
                "    AND td.casefile_id = m.casefile_id"
                f" WHERE {body}",
                binds,
            ).fetchone()["total"]
            rows = self._db.execute(
                "SELECT d.*, ("
                "   SELECT COUNT(*) FROM documents k WHERE k.parent_id = d.id"
                " ) AS child_count, chosen.mentions AS mentions"
                " FROM documents d"
                " JOIN (SELECT m.document_id AS document_id,"
                "              COUNT(DISTINCT m.document_offset) AS mentions"
                "         FROM mentions m"
                "         JOIN documents dd ON dd.id = m.document_id"
                "            AND dd.casefile_id = m.casefile_id"
                f"        WHERE {body}"
                "         GROUP BY m.document_id, dd.containment_path, dd.created_at"
                "         ORDER BY mentions DESC, dd.containment_path, dd.created_at,"
                "                  m.document_id"
                "         LIMIT ? OFFSET ?) chosen ON chosen.document_id = d.id"
                # Repeated deliberately: SQL guarantees nothing about the row
                # order a join produces, so the subquery's ordering is not
                # inherited. The same insurance `list_document_page` keeps.
                " ORDER BY chosen.mentions DESC, d.containment_path, d.created_at, d.id",
                (*binds, page, start),
            ).fetchall()
            documents = [_row_to_document(row) for row in rows]
            counts = {row["id"]: row["mentions"] for row in rows}
            passages = self._first_passages(body, binds, [d.id for d in documents])
        return MentionDocumentPage(
            carriers=[
                MentionCarrier(
                    document=document,
                    mentions=counts[document.id],
                    chunk_id=passages.get(document.id, ""),
                )
                for document in documents
            ],
            total_matching=total,
            offset=start,
            limit=page,
            kind=mention_kind,
            value=mention_value,
        )

    def _first_passages(
        self, body: str, binds: tuple[str, ...], document_ids: list[str]
    ) -> dict[str, str]:
        """The passage carrying each named document's earliest occurrence.

        One statement for the whole page rather than a correlated subquery per
        row: correlated, it re-seeks every mention of the identifier in the
        casefile once for each of up to two hundred rows.

        The pick is the earliest position in the document, then the lowest chunk
        ordinal. Two chunks sharing an overlap hold the same occurrence, and the
        earlier chunk is the one a reader reaches first; the trailing
        `m.chunk_id` decides only between two candidates indistinguishable on
        both, where there is nothing left to decide.

        **The pick is made in SQL, so this returns one row per document rather
        than one per occurrence.** Reducing an unbounded result set in Python
        instead is the shape the page query above exists to avoid, and here it
        is worse than a merely wasteful read: the number of rows is the number
        of times the corpus writes the identifier in those documents, which
        nothing bounds, and the page's `mentions DESC` ordering guarantees the
        document holding the most occurrences is on the first page at every
        limit, including one. Measured on a synthetic corpus whose heaviest
        document held 2,000 occurrences, the unbounded form fetched 2,194 rows
        to use one — inside the store lock, so every other operation waited.

        The window function is the whole reason this is bounded: `MIN` over
        `document_offset` would leave the two chunks of an overlap
        indistinguishable, which is the tie the ordering below exists to break.

        Called inside the caller's lock, so it takes none of its own.
        """
        if not document_ids:
            return {}
        placeholders = ",".join("?" for _ in document_ids)
        rows = self._db.execute(
            "SELECT document_id, chunk_id FROM ("
            "  SELECT m.document_id AS document_id, m.chunk_id AS chunk_id,"
            "         ROW_NUMBER() OVER ("
            "           PARTITION BY m.document_id"
            "           ORDER BY m.document_offset, c.ordinal, m.chunk_id"
            "         ) AS rank"
            "    FROM mentions m"
            "    JOIN chunks c ON c.id = m.chunk_id"
            "       AND c.casefile_id = m.casefile_id"
            f"   WHERE {body} AND m.document_id IN ({placeholders})"
            ") WHERE rank = 1",
            (*binds, *document_ids),
        ).fetchall()
        return {row["document_id"]: row["chunk_id"] for row in rows}

    def list_documents(
        self, casefile_id: str, include_expanded: bool = False
    ) -> list[Document]:
        """A casefile's documents, unbounded.

        Every adapter reaches `list_document_page` instead: this loads each
        document's whole extracted text, which is the entire corpus for a real
        one. It remains for callers that legitimately want a small casefile in
        full, and it delegates rather than repeating the predicate, so the two
        cannot come to disagree about what "the casefile's documents" means.
        """
        return self.list_document_page(
            casefile_id, include_expanded=include_expanded
        ).documents

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

    def record_ingest_run(self, run: IngestRun) -> None:
        """Record a completed run.

        Eleven named columns rather than a serialised blob: the aggregate below
        sums four of them, orders on two and compares two across consecutive
        rows, none of which a blob could be asked to do without unpacking every
        row.
        """
        with self._lock:
            self._db.execute(
                "INSERT INTO ingest_runs (id, casefile_id, started_at, finished_at,"
                " documents_before, documents_after, items_ingested, items_failed,"
                " entries_refused, files_without_extractor, exhausted_by)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    run.id,
                    run.casefile_id,
                    _to_iso(run.started_at),
                    _to_iso(run.finished_at),
                    run.documents_before,
                    run.documents_after,
                    run.items_ingested,
                    run.items_failed,
                    run.entries_refused,
                    run.files_without_extractor,
                    run.exhausted_by,
                ),
            )
            self._db.commit()

    def ingestion_coverage(self, casefile_id: str) -> IngestionCoverage:
        """What the recorded runs add up to, counted in the database.

        Four statements in one lock hold, so the totals, the earliest run, the
        bounds and the continuity check all describe the same instant. The
        verdict they support is deliberately not computed here: it is a domain
        rule, and a store that held one could disagree with the service layer
        about what its own counts mean.
        """
        with self._lock:
            totals = self._db.execute(
                "SELECT COUNT(*) AS runs,"
                "       COALESCE(SUM(items_failed > 0 OR entries_refused > 0"
                "                    OR files_without_extractor > 0 OR exhausted_by <> ''), 0)"
                "           AS limited,"
                "       COALESCE(SUM(items_ingested), 0) AS ingested,"
                "       COALESCE(SUM(items_failed), 0) AS failed,"
                "       COALESCE(SUM(entries_refused), 0) AS refused,"
                "       COALESCE(SUM(files_without_extractor), 0) AS unroutable"
                " FROM ingest_runs WHERE casefile_id = ?",
                (casefile_id,),
            ).fetchone()
            # An ordered read rather than MIN(documents_before): deleting
            # documents makes the minimum stop being the earliest run's value,
            # and it is the earliest run that decides whether anything predates
            # the record. The tie-break on `id` keeps it deterministic, the same
            # discipline `retrieval.py` applies to fused ranks — a value that
            # varies between runs of an unchanged corpus cannot be reasoned
            # about.
            first = self._db.execute(
                "SELECT documents_before FROM ingest_runs WHERE casefile_id = ?"
                " ORDER BY started_at, id LIMIT 1",
                (casefile_id,),
            ).fetchone()
            bounds = self._db.execute(
                "SELECT DISTINCT exhausted_by FROM ingest_runs"
                " WHERE casefile_id = ? AND exhausted_by <> '' ORDER BY exhausted_by",
                (casefile_id,),
            ).fetchall()
            # Where the record stops accounting for the corpus. A run that
            # raised part way is never recorded, but the documents it wrote
            # before raising stay — so the next run finds more documents than
            # the last recorded run left behind, and this gap is the only trace
            # of it. `LAG` compares consecutive rows in the same order the
            # earliest-run read uses, so one ordering decides both.
            breaks = self._db.execute(
                "SELECT COUNT(*) AS breaks FROM ("
                "  SELECT documents_before,"
                "         LAG(documents_after) OVER (ORDER BY started_at, id) AS previous_after"
                "    FROM ingest_runs WHERE casefile_id = ?"
                ") WHERE previous_after IS NOT NULL AND documents_before <> previous_after",
                (casefile_id,),
            ).fetchone()
        return IngestionCoverage(
            runs=totals["runs"],
            runs_with_limitations=totals["limited"],
            items_ingested=totals["ingested"],
            items_failed=totals["failed"],
            entries_refused=totals["refused"],
            files_without_extractor=totals["unroutable"],
            bounds_reached=tuple(row["exhausted_by"] for row in bounds),
            continuity_breaks=breaks["breaks"],
            documents_before_first_run=first["documents_before"] if first else 0,
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

