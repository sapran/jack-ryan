# Storage — schema and migrations

These rules live here rather than in the root memory file because `_SCHEMA` and
`_STEPS` are defined in one file in this directory, `migrations.py`, and adding
a column or a step means editing it — which is what loads this file. A session
that cannot cause the failure does not need to carry the warning.

That mechanism is why the migration ladder was split out of `sqlite.py` into its
own module *inside this directory* rather than anywhere else: editing it still
loads these rules. `migrations.py` also owns `_SIDECAR_TRIGGER` and creates the
`chunk_vectors` table, so the three artefacts the freeze covers are now made by
one function, `create_baseline`, instead of assembled at a call site that had to
remember all three.

`tests/test_migrations.py` names both from outside this directory, so it does
not load these rules. The additive-only rule and the FTS-trigger rule are
enforced there by `test_no_step_is_destructive` and
`test_the_fts_trigger_covers_every_fts_column`. The frozen-`_SCHEMA` rule is the
one no test can catch, which is why its one-line form stays in the root
`CLAUDE.md`.

- **`_SCHEMA` in the store is frozen at schema version 4.** Never add a column,
  table or index to it — add a step to `_STEPS`. Every statement there is
  `CREATE ... IF NOT EXISTS`, so editing it adds the change for new stores and
  *silently does not* for stores already on disk, leaving two shapes reporting
  one version. The baseline sits one version behind on purpose, so every fresh
  store climbs the ladder's first rung and the migration runner is exercised by
  the whole suite rather than by one fixture.
- **A migration step may only add.** A column with a constant default, a table,
  an index, a trigger, or a sidecar rebuilt from `chunks`. Never touch
  `documents`, `casefiles` or `chunks` destructively, never change a uniqueness
  constraint, and never make a step idempotent by catching "duplicate column" —
  that turns a version row that lies into a silent success.
- **A rung already applied is frozen, so a wrong rung is corrected by the next
  one.** Rung 10 spelled a location by concatenating in SQL what the runtime
  spells with `join_location`, and rung 11 exists because editing 10 could not
  reach a store already stamped at 10 — it would only move the stores that had
  not migrated yet, leaving two populations that differ by the day they were
  first opened. The corollary: a rung that derives a value the runtime also
  derives must call the runtime's function, registered on the connection by
  `migrate` (`jr_join_location`) and withdrawn afterwards, rather than
  reimplementing it in SQL.
  **The corollary has a price, and it is the same split.** Rung 11's output
  depends on whichever `join_location` the migrating build carried, and the rung
  cannot be re-run, so changing `join_location` (`storage/port.py`) is itself a
  schema event: stores migrated before the change and after it would hold
  different spellings under one stamped version. Such a change needs a further
  rung re-deriving `document_places`, in the same commit.
- **`document_places` is the live location table; the other two are kept
  fossils.** No runtime path may write `document_observations` or
  `document_locations`, or read either as the record — they are the record as it
  was kept. Tests and a repair may read them, and that is the point: rung 11's
  correctness is checkable against them, and the fixtures in
  `tests/test_document_locations.py` build an older store by writing them. (The
  names alone are not the rule: `StorePort.document_locations` and
  `IngestionService.document_locations` are methods that read
  `document_places`.) All three tables are in `EVIDENCE_TABLES` in
  `tests/test_migrations.py`, which is what stops a later rung deleting from the
  one that holds custody evidence.
- **A step that changes the FTS column list must drop and recreate the delete
  trigger in the same transaction.** The trigger names the columns it feeds to
  FTS5's `'delete'`; a column it does not name leaves its tokens in the index on
  every ordinary reingest, and a strict integrity check then reports the database
  malformed.
