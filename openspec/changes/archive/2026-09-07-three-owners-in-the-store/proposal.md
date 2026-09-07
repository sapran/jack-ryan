## Why

`storage/sqlite.py` was 1,155 lines holding five concerns, three of which share
nothing but the connection:

| Concern | Lines |
|---|---|
| schema and the migration ladder | 24–219, 339–348, 381–553 |
| casefile CRUD | 567–650 |
| document and hierarchy CRUD | 652–823 |
| the chunk+vector+mention atomic write, and chunk reads | 825–1016 |
| retrieval SQL | 241, 248–284, 1023–1155 |

Two of those have a published spec of their own — `schema-migration` and the
retrieval half of `hybrid-search` — and a hazard file, `storage/CLAUDE.md`, whose
own opening sentence explained itself by where the code sat: *"`_SCHEMA` and
`_STEPS` are defined in one file, `sqlite.py`, and adding a column or a step
means editing it — which is what loads this file."*

That file also names three artefacts as one frozen shape — the baseline script,
the `chunk_vectors` table, and `_SIDECAR_TRIGGER` — and says *"leaving them out
is how the ladder and the create path drift apart"*. They were created by three
separate statements in `initialize`, kept together by a comment asking the reader
to remember.

## What Changes

**Current behaviour.** One module, five concerns, and one comment standing in for
a structural guarantee.

**Desired behaviour.**

- **`storage/migrations.py`** owns the frozen baseline, the ladder, the version,
  the backup, and the identity check. It sits inside `storage/`, so editing it
  still loads `storage/CLAUDE.md` — that mechanism is why it went here and not
  anywhere else.
- **`create_baseline(conn, embed_dimensions)`** creates all three frozen
  artefacts in one function. The freeze becomes structural instead of remembered.
- **`storage/retrieval.py`** owns the two retrieval legs, the shared mention
  filter, and the identifier inventory — the queries whose *shape* is
  load-bearing, because every predicate deciding which passages are eligible
  must sit inside the SQL rather than over its results.
- **`replace_chunks` stays whole, in `sqlite.py`.** Its single transaction across
  text, FTS and vectors is the guarantee the whole seam exists to make; splitting
  it would put one guarantee in two files.
- **The lock stays with the store.** The extracted functions take an open
  connection and hold no lock. `SqliteStore` takes `self._lock` around each call.
  A module acquiring its own lock would be a second place threading is reasoned
  about, and `CLAUDE.md` has one rule on that subject for a reason.

`sqlite.py` goes 1,155 → 657. The SQL moves verbatim, the frozen block moves
byte-identically, and the port's method signatures are untouched.

**No *observable* behaviour changes** — the phrasing matters, because review
found the stronger claim to be false. Three guard clauses that ran before the
lock now run inside it: `search_vector`'s width check, `search_keyword`'s
empty-query return, and `mention_facets`' clause building, because the whole
extracted function is now inside the delegate's `with`. The region is an
`RLock` holding a length comparison, a regex `findall` and some string
formatting — no I/O, nothing that blocks — so the widening is harmless and the
answers are identical. It is recorded rather than hidden.

**Deliberately not in scope.** The parked bm25 finding — `search_keyword` orders
by a score FTS5 computes over the whole index, not over the casefile — moves file
and stays parked. Fixing it changes what `hybrid-search` guarantees.

## Impact

- **Specs: none.** Established by falsification. `storage-seam` and
  `schema-migration` were read in full: every occurrence of "one file" is
  unambiguously the SQLite **database** file ("Persistence SHALL be a single
  SQLite file…"), and no requirement in either names a Python module, a file
  layout, or a method. What they require — the ladder's order and additivity,
  the pre-migration backup, the two distinct refusal messages, a `threading`
  lock, one transaction across text and vectors — is preserved and still
  asserted by the same tests.
- **Code:** `src/jackryan/storage/migrations.py` and
  `src/jackryan/storage/retrieval.py` (new); `sqlite.py` loses 505 lines.
- **Tests:** `tests/test_migrations.py` re-points its imports and its two
  monkeypatches. No assertion changes; one helper gains an argument.
- **Docs:** `storage/CLAUDE.md`'s rationale, two root `CLAUDE.md` pitfalls, and
  the bm25 entry in `docs/implementation-notes.md`.
