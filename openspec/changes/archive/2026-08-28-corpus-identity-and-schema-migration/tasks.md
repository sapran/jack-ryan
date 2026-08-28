## 1. The frozen baseline

- [x] 1.1 Recover the pre-`text_source` `_SCHEMA` from git history and restore it as the frozen baseline, with a comment saying it is frozen and why editing it would silently not alter an existing store; verify the recovered text matches the version in the commit before `text_source` was added
- [x] 1.2 Freeze `_SIDECAR_TRIGGER` and the `chunk_vectors` statement alongside it, so the ladder and the create path cannot drift through the two artefacts that are not `_SCHEMA`
- [x] 1.3 Define `_BASELINE_VERSION = 4` and `_OLDEST_MIGRATABLE = 4`; verify a test asserts the baseline creates a store with no `text_source` column

## 2. The ladder

- [x] 2.1 Define a `_Step` carrying a target version, a one-line reason, and its statements; define `_STEPS` with the single `v4 → v5` rung adding `text_source`; verify a test reads the reason and finds it non-empty for every step
- [x] 2.2 Derive `SCHEMA_VERSION` from the ladder rather than declaring it; verify a test asserts it equals the highest step's target
- [x] 2.3 Implement the runner: read the recorded version unlocked, return early when current, refuse below `_OLDEST_MIGRATABLE` or above `SCHEMA_VERSION`, back up, then `BEGIN IMMEDIATE`, re-read the version inside the transaction, apply every step above it, stamp the new version, one commit; verify a test asserts the re-read happens by racing a version change between the two reads
- [x] 2.4 Place the runner before the `schema_version` and `contract_fingerprint` checks; verify a test asserts a store with both an old schema and a different identity is migrated and then refused on identity
- [x] 2.5 Roll back and raise `ConfigError` on any step failure; verify a test asserts a store whose step fails is left at its recorded version with no partial change

## 3. Making the rule mechanical

- [x] 3.1 Add a test that reads every statement in `_STEPS` and fails on `DROP TABLE`, `DROP INDEX`, or a `CREATE TABLE` naming `documents`, `casefiles` or `chunks`; verify it fails when a destructive step is added
- [x] 3.2 Add a test comparing `sqlite_master` from a fresh store against one built at the baseline and walked up the ladder, asserting they are identical; verify it fails when a step and the baseline disagree
- [x] 3.3 Add a test parsing the `chunks_after_delete` trigger from `sqlite_master` and asserting its `'delete'` column list equals `PRAGMA table_info(chunks_fts)`; verify it fails against a two-column FTS table with today's trigger
- [x] 3.4 Record the rule in the module: a step changing the FTS column list drops and recreates the trigger in the same transaction

## 4. The backup

- [x] 4.1 Back up to `<db>.v<recorded>.bak` using SQLite's backup API, only when steps will run, never deleted; verify a test asserts the copy opens with `sqlite_vec` loaded and holds the same chunk and vector counts as the original
- [x] 4.2 Refuse the migration when the backup cannot be written, naming the path; verify a test asserts no step ran

## 5. The split refusal

- [x] 5.1 Give `schema_version` its own refusal text naming the recorded version, the running version, the floor and a schema remedy; verify a test asserts the schema refusal does not contain the identity remedy's wording
- [x] 5.2 Leave the corpus-identity refusal exactly as it is; verify the existing test asserting it names both values and says how to proceed still passes unchanged

## 6. Corpus identity escaping

- [x] 6.1 Escape `\`, `|` and control characters per component in `Contract.fingerprint` and `corpus_fingerprint`, leaving `=` unescaped; verify a test asserts the default identity string is byte-identical to the one recorded before this change
- [x] 6.2 Verify two different configurations cannot share one identity, and watch it fail with the plain join. *Amended: the test this task described was written and found vacuous — it passed with the escaping removed, because a clause injected into `embed_model` alone lands where the honest value never sits. A real collision needs both ends, `embed_model` carrying the head of the tail components and the embedder name carrying their end. That is what shipped.*
- [x] 6.3 Verify the existing assertion that the contract fingerprint is a substring of corpus identity still holds — it does, unchanged, because the contract's fingerprint is already escaped component by component and is joined into corpus identity raw

## 7. The embedder width check

- [x] 7.1 Compare `chosen.dimensions` with `contract.embed_dimensions` in `build_context`, after the embedder and before `SqliteStore` is constructed; raise `ConfigError` naming both widths and which side to change
- [x] 7.2 Verify a test asserts `build_context(config, embedder=DeterministicEmbedder(64))` against a 1024-wide contract raises, and that no database file exists afterwards — proof the check ran ahead of the store
- [x] 7.3 Note in the code that this compares declared widths only, and that `ModelEmbedder` already guards the loaded model

## 8. `text_source` for the human

- [x] 8.1 Move `read_as` from `interfaces/mcp/fencing.py` to `ingestion/quality_gate.py` beside `TEXT_SOURCES`, and re-export it from `fencing.py`; verify the MCP tests pass unchanged
- [x] 8.2 Add `read_as` to the CLI document renderer and to the list line; verify a test asserts `jackryan document list` output carries it
- [x] 8.3 Add `read_as` to `serialize_document` in the REST adapter; verify a test asserts both document endpoints carry it
- [x] 8.4 Add `read_as` to the MCP `_render_document`, so `case_list_documents` carries it as the other agent surfaces do; verify a test asserts it
- [x] 8.5 Verify one vocabulary: a test asserts an unrecognised stored value collapses to `unrecorded` on all four surfaces alike

## 9. Prove the tests can fail

- [x] 9.1 Reintroduce the unescaped join and verify the impersonation test goes red
- [x] 9.2 Remove the width comparison and verify the composition-root test goes red with a store file left on disk
- [x] 9.3 Stamp the version without applying a step and verify the migration test goes red
- [x] 9.4 Add a destructive step and verify the additive-rule test goes red

## 10. Verification and documentation

- [x] 10.1 Build a populated store at the frozen v4 shape, open it with the current binary, and assert it migrates, its documents still read, and they report `unrecorded`
- [x] 10.2 Run `scripts/verify_model_paths.py --only pdf --only ocr` and confirm nothing regressed
- [x] 10.3 Update `docs/handover.md` with what this settles and what it does not, including that the migration path has been exercised only against a synthetic v4 store
- [x] 10.4 Move the four addressed findings from Parked to Fixed in `docs/implementation-notes.md`, and record the two new ones: originals are never archived despite `docs/design.md` § 5, and the ingest-root/derived-identifier change
- [x] 10.5 Update `CLAUDE.md` pitfalls: the baseline is frozen, steps are additive, the FTS trigger travels with the FTS columns, and identity is escaped but not hashed
