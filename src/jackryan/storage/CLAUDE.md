# Storage — schema and migrations

These rules live here rather than in the root memory file because `_SCHEMA` and
`_STEPS` appear in exactly one source file, `sqlite.py`. A session that cannot
cause the failure does not need to carry the warning.

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
