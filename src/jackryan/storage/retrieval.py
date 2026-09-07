"""The read queries: the two retrieval legs, and the identifier inventory.

Split out of `sqlite.py` because these are the only queries whose *shape* is
load-bearing rather than incidental. Both legs are asked for a bounded number of
candidates, so every predicate that decides which passages are eligible has to
sit inside the SQL — a filter applied to what a leg returned discards every
match that ranked below that depth unfiltered, and hands the caller nothing
while the store holds exactly what they asked for. The casefile constraint and
the mention filter are both inside for that reason, and any new predicate
belongs beside them, in this file.

Nothing here holds a connection or a lock. Each function takes an open
connection; `SqliteStore` keeps the lock and takes it around the call.
"""

from __future__ import annotations

import json
import re
import sqlite3

from ..errors import ConfigError
from .port import MentionFacet

_FTS_TOKEN = re.compile(r"[\w\u0400-\u04FF]+", re.UNICODE)


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


def search_keyword(
    db: sqlite3.Connection,
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
    rows = db.execute(
        "SELECT c.id AS id FROM chunks_fts f"
        " JOIN chunks c ON c.rowid = f.rowid"
        " WHERE chunks_fts MATCH ? AND c.casefile_id = ?"
        f"{predicate}"
        " ORDER BY bm25(chunks_fts) LIMIT ?",
        (match, casefile_id, *carrying, int(limit)),
    ).fetchall()
    return [row["id"] for row in rows]


def search_vector(
    db: sqlite3.Connection,
    dimensions: int,
    casefile_id: str,
    embedding: list[float],
    limit: int,
    mention_kind: str = "",
    mention_value: str = "",
) -> list[str]:
    """Rank chunks by vector distance, returning chunk ids nearest first."""
    if len(embedding) != dimensions:
        raise ConfigError(
            f"query embedding has width {len(embedding)} but the contract declares "
            f"{dimensions}"
        )
    predicate, carrying = _mention_filter(
        "id", casefile_id, mention_kind, mention_value
    )
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
    rows = db.execute(
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


def mention_facets(
    db: sqlite3.Connection, casefile_id: str, kind: str, limit: int
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
    rows = db.execute(
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
