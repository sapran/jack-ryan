## Why

The location record ships correct for stores this build wrote and wrong for
stores it carried forward. PM verification of task 5 reproduced it at `2c3afa2`;
it was reproduced again, from genuine old code, before this proposal was
written.

Schema rung 10 built `document_observations` by concatenating the old root and
the path within it, `source_root || '/' || containment_path`. Every live
observation is spelled by `join_location`, which normalises through
`PurePosixPath`. The two agree on most paths and disagree on paths a real dump
routinely holds.

```
old code (85c24a4) ingests bundle.tar holding entry "./note.txt"
  pair recorded:      ('<dump>', 'bundle.tar/./note.txt')
migrate to schema 10
  observation:        <dump>/bundle.tar/./note.txt
reingest the unchanged archive with current code
  observation added:  <dump>/bundle.tar/note.txt      <- nothing was discovered
  locations: 2   outcome: new   locations_recorded: complete
```

One physical place, recorded twice, announced to the analyst as a newly
discovered copy — which is exactly the failure the published identity rule
("that path alone SHALL be what makes one location distinct from another") was
written to make impossible. It reaches every surface: CLI detail, the REST
detail route and `case_read_document` all report `locations: 2` and print the
same file twice.

Three shapes were reproduced, and they are not equally repairable:

- `./` components and doubled separators inside the path within the root.
- A source root of `/`, which concatenates to `//lease.md`. This one is the
  reason the fix cannot be "normalise the stored string": `//lease.md` is
  already its own normal form under POSIX rules, so only the surviving pair
  `('/', 'lease.md')` says that `/lease.md` was meant.

The normalisation itself is correct and stays: it is what makes two roots
reaching one file one place, which the previous change established.

## What Changes

- Schema rung **11** adds `document_places`, holding a location keyed on the
  path alone, spelled by the same `join_location` the runtime spells one with —
  registered on the migrating connection as a SQL function so there is one
  definition rather than a copy in SQL.
- Rung 11 carries forward from **both** older tables: observations this build's
  own code wrote are copied as they are, and everything rung 10 derived is
  re-derived from the raw `document_locations` pairs, which is the only place
  the intended spelling survives. Two spellings of one place collapse, and the
  earlier `first_seen_at` wins — the timestamp the wholeness of the record is
  judged against.
- The store reads and writes `document_places`. `document_locations` and
  `document_observations` stay in place, unwritten and unread, as rung 10 left
  its predecessor: they are the record as it was kept, and rung 11's own
  correctness is checkable against them.
- Rung 10 is left byte-identical in what it executes. A rung already applied
  cannot be corrected by editing it, so editing it would only change what a
  not-yet-migrated store receives — two populations diverging by the day they
  were first opened.

Not in scope, and deliberately left standing: the failed-backup residue defect,
the identifier-carrier listing's omitted location count, and the pair-identity
tradeoff note. All three are recorded in `docs/implementation-notes.md`.

## Impact

- Affected specs: `document-ingestion` (one `ADDED` requirement).
- Affected code: `storage/migrations.py` (rung 11, the registered function),
  `storage/sqlite.py` (five statements move table), `tests/`.
- **Data migration:** every store below schema 11 gains `document_places` on
  first open, after the full-file backup `schema-migration` already requires.
  No evidence row is rewritten or deleted. A store whose locations were already
  spelled correctly gets a byte-identical set of places, so the only visible
  change is to the stores that were wrong.
- No change to corpus identity: nothing here touches what is chunked, embedded
  or stored as text, so no store is refused for it.
