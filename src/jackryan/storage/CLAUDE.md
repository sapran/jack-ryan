# Storage — schema and migrations

These rules live here rather than in the root memory file because `_SCHEMA` and
`_STEPS` are defined in one file, `sqlite.py`, and adding a column or a step
means editing it — which is what loads this file. A session that cannot cause
the failure does not need to carry the warning.

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
- **A step that changes the FTS column list must drop and recreate the delete
  trigger in the same transaction.** The trigger names the columns it feeds to
  FTS5's `'delete'`; a column it does not name leaves its tokens in the index on
  every ordinary reingest, and a strict integrity check then reports the database
  malformed.
