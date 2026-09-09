## 1. Reproduce

- [x] 1.1 Build a genuine schema-9 corpus with old code (`85c24a4`) from a tar holding `./note.txt`; migrate and reingest with current code; record two locations, outcome `new`, verdict `complete`.

## 2. Carry a location forward as the runtime spells it

- [x] 2.1 Schema rung 11: `document_places`, keyed `(document_id, location_path)`.
- [x] 2.2 Register `join_location` on the migrating connection as `jr_join_location`, so the rung uses the runtime's one definition.
- [x] 2.3 Copy this build's own observations across as they are; re-derive everything rung 10 built from the raw `document_locations` pairs.
- [x] 2.4 Collapse two spellings of one place, keeping the earlier `first_seen_at`.
- [x] 2.5 Leave rung 10 and both older tables untouched.
- [x] 2.6 Move the store's five location statements to `document_places`.

## 3. Prove it

- [x] 3.1 Migration-and-reingestion regression: schema-9 archive entry, then a real reingest of the unchanged archive.
- [x] 3.2 Already-migrated schema-10 store holding both spellings.
- [x] 3.3 Repeated separators, and a `/`-root record.
- [x] 3.4 Two genuinely different custodian locations both survive.
- [x] 3.5 Mutation-prove each new assertion against the rung removed.
- [x] 3.6 Interruption, retry-history and same-file regressions stay green.
- [x] 3.7 Full suite, `openspec validate --all --strict`, and the shipped CLI and MCP journeys against a genuine old-code corpus.
