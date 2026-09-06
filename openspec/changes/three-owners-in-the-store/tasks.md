## 1. The rule in the published specs

- [x] 1.1 Read `storage-seam` and `schema-migration` in full and check every
      occurrence of "one file"; verify each means the SQLite database rather than
      a Python module, since that is the phrase a split would falsify if it meant
      the other thing. *All of them mean the database: "Persistence SHALL be a
      single SQLite file under the configured data directory", "exactly one
      database file is created". Neither spec names a module, a file layout or a
      method.*
- [x] 1.2 Confirm what the two specs actually require and that each survives;
      verify against the tests that assert them, not against the prose alone.
      *Ladder order and additivity, the version derived from the ladder, the
      pre-migration backup through a real backup API, two distinct refusal
      messages, a `threading` lock, one transaction across text and vectors — all
      preserved, all still asserted by the same 20 tests in
      `tests/test_migrations.py`.*
- [x] 1.3 Ship `.openspec.yaml` with `skip_specs: true` and the falsification as
      a comment; verify `openspec validate --all --strict` accepts it, which it
      refuses without valid metadata.

## 2. The migration module

- [x] 2.1 Create `storage/migrations.py` **inside `storage/`**; verify the
      placement against `storage/CLAUDE.md`'s own mechanism rather than by taste.
      *That file explains itself by "adding a column or a step means editing it —
      which is what loads this file". Any home inside `storage/` preserves that;
      a home outside would silently stop loading the hazard rules for the exact
      edit they exist to govern.*
- [x] 2.2 Move `_BASELINE_VERSION`, `_OLDEST_MIGRATABLE`, the freeze comment,
      `_SCHEMA`, `_Step`, `_STEPS` and `SCHEMA_VERSION`; verify byte-identity
      against `origin/develop` before the originals are deleted. *Extracted by a
      script that slices the original file rather than by retyping, then diffed
      with `difflib`: **196 lines, identical**, zero hunks.*
- [x] 2.3 Move `_SIDECAR_TRIGGER` off the class and into the module; verify the
      one test that read it from the class is re-pointed rather than left to an
      `AttributeError` at some later date. *`tests/test_migrations.py:49` now
      imports `_SIDECAR_TRIGGER` by name.*
- [x] 2.4 Add `create_baseline`; verify it creates all three frozen artefacts,
      because the freeze comment names three and the call site created them as
      three separate statements. *Script, vector table, trigger — one function.
      The comment that asked a reader to remember is now the function's
      docstring.*
- [x] 2.5 Convert `_recorded_version`, `_migrate`, `_backup_before_migrating` and
      `_verify_meta` to functions taking `(conn, path, …)`; verify no `self.`
      reference survives. *Grep returns one hit, in a docstring explaining why
      `verify_meta` no longer takes the lock.*
- [x] 2.6 Take the lock out of `verify_meta` and put it at the call site; verify
      both calls are inside it. *`initialize` wraps both `verify_meta` calls in
      `with self._lock:`, with a comment saying the store owns when its
      connection is guarded.*

## 3. The retrieval module

- [x] 3.1 Move `_FTS_TOKEN`, `_mention_filter`, `search_keyword`, `search_vector`
      and `mention_facets`; verify `_mention_filter` is byte-identical, since it
      is the shared predicate both legs depend on. *Diffed: **37 lines,
      identical**.*
- [x] 3.2 Leave `_escape_like` in `sqlite.py`; verify it is used by something
      that stays. *Three prefix lookups — casefiles, documents, chunks — none of
      which is retrieval.*
- [x] 3.3 Strip the three `with self._lock:` blocks and pass the connection;
      verify the lock is taken by the delegate instead, not dropped. *Each
      delegate on `SqliteStore` is `with self._lock: return retrieval.<fn>(self._db, …)`.*
- [x] 3.4 Pass `dimensions` to `search_vector` explicitly; verify the width check
      still refuses a mismatched query embedding. *Same `ConfigError`, same
      message; `tests/test_search.py` and `tests/test_store.py` unchanged and
      green.*
- [x] 3.5 Keep the long docstrings with the SQL; verify the load-bearing argument
      travels with the query rather than staying behind. *Both legs' comments —
      the filter goes inside the query, never over its results — moved with them,
      and the module docstring states it once for the file. The delegates carry a
      pointer rather than a copy.*

## 4. What stays

- [x] 4.1 Leave `replace_chunks` whole and in place; verify the transaction it
      guarantees is still one transaction in one file. *Untouched, 127 lines,
      still the only writer of chunks, vectors and mentions.*
- [x] 4.2 Leave the row mappers, the ISO helpers and the CRUD; verify nothing
      that stays now reaches into a moved module for a helper. *`sqlite.py`
      references `migrations.` and `retrieval.` only at the five delegation
      points and in `initialize`.*
- [x] 4.3 Remove imports the split made dead; verify by use rather than by
      assumption. *`re` had one user (`_FTS_TOKEN`) and `dataclass` one
      (`_Step`); both removed. `json`, `threading`, `sqlite_vec`, `ConfigError`,
      `ConflictError`, `Mention`, `MentionFacet` and `CasefileStatistics` all
      still have users and stay.*

## 5. The tests that move

- [x] 5.1 Re-point `tests/test_migrations.py`'s five-name import at
      `jackryan.storage.migrations`; verify no assertion changes. *None did.*
- [x] 5.2 Re-point the two `from jackryan.storage import sqlite as mod` aliases;
      verify a stale one fails loudly rather than silently. *Watched: pointing
      the ladder patch back at `sqlite` raises `AttributeError: module
      'jackryan.storage.sqlite' has no attribute '_Step'` at the patch line,
      because nothing is re-exported.*
- [x] 5.3 Re-point the `_backup_before_migrating` double at
      `migrations.backup_before_migrating`; verify the race it stages still
      happens. *It does — but only after fixing what the move exposed: see 5.4.*
- [x] 5.4 Handle the widened blast radius of the module-level patch; verify by
      the failure it caused rather than by reasoning about it. *The instance
      patch it replaced applied to one store; the module patch applies to every
      store in the process, so the competing store spawned inside the double
      re-entered it — `RecursionError`. The double now restores the original
      before spawning the competitor, and says why. This generalises: moving a
      method to a module function widens the reach of every double targeting it.*

## 6. Documentation

- [x] 6.1 Rewrite `storage/CLAUDE.md`'s opening rationale; verify it still
      explains the mechanism rather than just naming the new file. *It names
      `migrations.py`, states that the split kept the ladder inside `storage/`
      **so that** editing it still loads these rules, and records that
      `create_baseline` now makes the freeze structural.*
- [x] 6.2 Re-point root `CLAUDE.md`'s `_STEPS` pitfall and its search-filter
      pitfall; verify the search-filter one still tells a reader where to put a
      new predicate. *It now names `storage/retrieval.py` and says that is why
      the file exists.*
- [x] 6.3 Re-point the bm25 entry in `docs/implementation-notes.md`; verify it
      stays parked. *Path only; the finding and its reasoning are unchanged.*

## 7. Verification

- [x] 7.1 Run `pytest -q`; verify the count is unchanged, since a pure move that
      changes the count changed something else too. *710 passed, 3 skipped —
      identical to the branch point.*
- [x] 7.2 Diff the moved blocks against `origin/develop`; verify byte-identity
      rather than plausibility. *Frozen block 196 lines identical,
      `_mention_filter` 37 lines identical, and every SQL literal present before
      the split is present after it.*
- [x] 7.3 Watch the stale-monkeypatch failure; verify it is loud. *See 5.2.*
- [x] 7.4 Run `openspec validate --all --strict`; verify 18 items pass.
- [x] 7.5 Leak-grep the diff for `sk-`, `hf_`, `AKIA`, `ghp_`, `-----BEGIN`,
      `.ts.net`, `/Users/`, `/home/`; verify nothing matches.
