## Context

Nothing here is a bug fix. `sqlite.py` was correct at 1,155 lines; it was also
the only file in the project where a reader looking for one rule had to scroll
past four others, and where a hazard file justified its own existence by naming
the file the code happened to live in.

The split is possible because the three extracted concerns share very little.
Measured rather than assumed:

- The migration path runs **before** the store is usable and is deliberately
  lock-free until `BEGIN IMMEDIATE`; it reads `self._path` only for error
  messages.
- The retrieval queries return `list[str]` of chunk ids and use **no** row
  mapper. They need the connection, and `search_vector` needs `self._dimensions`.
- Everything else — the row mappers, `_escape_like`, `_to_iso`/`_from_iso` — is
  used by the CRUD that stays.

## Goals / Non-Goals

**Goals.**

- One module per concern, each editable without reading the other two.
- The freeze made structural: three artefacts, one function.
- Behaviour preserved provably, not by assertion — the frozen block diffed
  byte-identical before the original was deleted.

**Non-Goals.**

- Splitting `replace_chunks`, or moving it.
- Renaming anything. `_SCHEMA`, `_STEPS`, `_BASELINE_VERSION`,
  `_OLDEST_MIGRATABLE`, `SCHEMA_VERSION` and `_SIDECAR_TRIGGER` keep their exact
  spellings; only their import path changes.
- Fixing the parked bm25 cross-casefile ranking leak.
- A `storage/sqlite/` package. Three sibling modules is the smaller change and
  leaves `from .sqlite import SqliteStore` working unchanged.

## Decisions

### The lock stays with the store; the extracted functions take a connection

`SqliteStore` owns its connection, so it owns when the connection is guarded.
Each delegate is `with self._lock: return retrieval.search_keyword(self._db, …)`.

The alternative — a mixin, or functions that acquire the lock themselves — was
rejected for a specific reason rather than a stylistic one. `CLAUDE.md` carries
one rule about locking in this codebase (*"Locks are `threading`, not
`asyncio`"*), and it is legible today because every acquisition is visible in one
class. A mixin would additionally let a method added later inherit the lock
without taking it, which is the failure mode this project keeps writing rules
about.

`verify_meta` is the one function whose body previously took the lock itself.
It no longer does; `initialize` wraps both calls.

### The frozen shape becomes one function

`create_baseline(conn, embed_dimensions)` runs `_SCHEMA`, creates
`chunk_vectors` at the contract's width, and installs `_SIDECAR_TRIGGER`. The
comment on `_SCHEMA` already said all three are part of one freeze and that
leaving any out is how the ladder and the create path drift apart. It was a
comment over three statements at a call site; it is now a function.

### Names keep their spelling, and nothing is re-exported

`tests/test_migrations.py` imports five private names and reaches two more
through the module object. All keep their exact spelling and move to
`migrations`; the test re-points its import path.

**`sqlite.py` does not re-export any of them.** That is the same call the window
change made for `MAX_RESPONSE_CHARS` and for the same reason: a re-export would
let `monkeypatch.setattr(sqlite, "_STEPS", …)` bind to a name `migrate` does not
read. Verified by mutation — pointing the ladder patch back at
`jackryan.storage.sqlite` raises
`AttributeError: module 'jackryan.storage.sqlite' has no attribute '_Step'`,
loudly, at the line that patches it.

Renaming `_SCHEMA` to `SCHEMA` now that it crosses a module boundary was
considered and rejected: it is churn across fifteen test sites, and it would put
the frozen-baseline rule under a name `storage/CLAUDE.md` does not use.

### A module-level patch is wider than the instance patch it replaces

`test_the_version_is_re_read_under_the_write_lock` used to replace
`store._backup_before_migrating` on **one instance**, so the competing store it
spawns mid-migration used the real function. Patching
`migrations.backup_before_migrating` affects every store in the process, and the
nested store re-entered the double — a `RecursionError`, not a subtle wrong
answer, but a real difference in what the patch reaches. The test now restores
the original before spawning the competitor and says why.

This is worth stating because it generalises: moving a method to a module
function widens the blast radius of every double that targets it.

### `sqlite.py` reads `migrations.SCHEMA_VERSION` by attribute, never by `from`-import

`initialize` writes `migrations.SCHEMA_VERSION`, not `SCHEMA_VERSION` imported
from that module. This looks like style and is not.

`tests/test_migrations.py` monkeypatches `SCHEMA_VERSION` on the `migrations`
module to stage a failing ladder step. An attribute read resolves through the
module object at call time, so the patch reaches the store. A `from … import
SCHEMA_VERSION` at the top of `sqlite.py` would bind the value once at import
and the patch would be **half-dead** — `migrate` would see the raised version
while `initialize`'s post-migration check saw the old one.

The same applies to `migrations._STEPS` and
`migrations.backup_before_migrating`, both read as module globals inside
`migrations.py` itself. A future tidy-up that converts any of these to
`from`-imports has to re-point the corresponding patch in the same change.

## Risks / Trade-offs

**A pure move is where a silent edit hides.** Mitigated mechanically: the 196
frozen lines and the 37 lines of `_mention_filter` were diffed against
`origin/develop` with `difflib` and are byte-identical, and every SQL literal
present before the split is present after it. The extracted modules were built
by a script that slices the original file, not retyped.

**Three files where a reader previously grepped one.** `storage/__init__.py`
still exports `SqliteStore`, and `from .sqlite import SqliteStore` is unchanged,
so no caller outside `storage/` moves. Inside, `sqlite.py` imports both new
modules by name, so `migrations.` and `retrieval.` prefixes say where a reader
should go.

**`search_vector` now takes `dimensions` as an argument** where it read
`self._dimensions`. The value still comes from the same place — the store sets it
in `initialize` from the contract — but a caller could now pass a different one.
No caller does; the port's signature is unchanged, and the delegate is the only
call site. Measured rather than assumed: a delegate passing
`self._dimensions + 1` fails dozens of tests across `test_search`,
`test_server`, `test_mentions` and `test_section_windows`, with the typed
`ConfigError` reaching the REST boundary.

**Three guard clauses moved inside the lock**, and the change is real even
though it is harmless. On develop, `search_vector`'s width check,
`search_keyword`'s empty-query return, and `mention_facets`' clause building all
ran *before* `with self._lock:`. Now the whole extracted function runs inside the
delegate's `with`. The lock is an `RLock`, nothing inside re-acquires it, and the
widened region holds a length comparison, a regex `findall` and string
formatting — no I/O. Strictly more atomic, marginally more contended, identical
answers. The proposal says "no *observable* behaviour changes" rather than "no
behaviour changes" because of this.
