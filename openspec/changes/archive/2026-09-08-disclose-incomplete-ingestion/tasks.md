## 1. The rule in the published specs

- [x] 1.1 Add `ingestion-coverage` as a new capability delta, every block `## ADDED Requirements` with a `## Purpose`; verify a `Purpose` is honoured for a new capability rather than silently ignored as it is for an existing one. *Four requirements, sixteen scenarios. The `Purpose` survived the archive into `openspec/specs/ingestion-coverage/spec.md`, checked by reading the published file rather than assuming.*
- [x] 1.2 Establish by falsification that no `MODIFIED` block is owed, re-reading each published text rather than judging by topic; record the table in the proposal's `## Impact`. *Seven published texts re-read this session. The near one was `container-extraction:127-131` — an oversized entry judged "by what was read rather than by the size the archive declares" — which is why the reconciliation counts against `metadata["entries"]` instead of refusing on a declared size. Table in `## Impact`.*
- [x] 1.3 `openspec validate --all --strict` before any code is written. *18 passed, 0 failed, before implementation and again after archiving.*

## 2. One definition of incompleteness

- [x] 2.1 Add `IngestReport.skipped`; verify it is counted apart from `refusals` and that the comment says why the two want different words. *A folder-walk file lands in `skipped`, a container entry in `refusals`; asserted both ways in `test_a_file_no_extractor_accepts_is_reported_as_skipped` (`refusals == []`).*
- [x] 2.2 Replace `complete` with derived `limitations` + `complete`; verify every existing assertion on `complete` still passes, and that a failed document now makes a run incomplete. *All three existing assertions are negative and stayed green. Mutation 1 restored the old `complete` and reddened `test_a_failed_document_makes_the_run_incomplete` with `assert not True`.*

## 3. What the extractors already refused

- [x] 3.1 Return the `Extraction` from `_ingest_work` as a third element; verify the `except ConfigError: raise` clause is untouched and still above the per-document handler. *Both `return` sites gained a third element and the clause order is unchanged; `tests/test_legacy_office.py`'s escape-path tests stayed green.*
- [x] 3.2 Extend the run's refusals with `extraction.refusals`, prefixed by the container's containment path; verify a traversing zip entry now reaches the report, which before this only existed on the `Extraction`. *`test_an_entry_the_reader_refused_reaches_the_report`. Mutation 4 emptied the iterable and it reddened with "the traversing entry never reached the report: []". Deleting the whole block was rejected as a mutation: the body is a comment plus one statement, so removal is an IndentationError, which is a collection error and not a red test.*
- [x] 3.3 Route an unroutable folder file to `skipped` and an unroutable container entry to `refusals`; verify the container branch keeps its wording verbatim so the two existing assertions stay green. *`test_containers.py:92` and `test_rar_containers.py:386` untouched and green.*

## 4. Listed against delivered

- [x] 4.1 Pass the `Extraction` into `_expand`; add `stopped_by_budget` and `expansion_failed` locals. *`containers.py` is not edited — it already published the count.*
- [x] 4.2 Reconcile `metadata["entries"]` against `len(produced)`; verify `isdigit()` guards the parse so the mail extractors are skipped rather than compared against zero. *`test_entries_the_reader_never_delivered_are_reported` with `MAX_ENTRY_BYTES` at 64. The mailbox tests stayed green, which is the `isdigit()` guard doing its job — the mail extractors publish no `entries`.*
- [x] 4.3 Suppress the shortfall where a bound stopped the container or its expansion raised; verify exactly one refusal is reported, not two. *Mutation 6 dropped the `not stopped_by_budget` conjunct and reddened, naming both refusals: `['wide.zip: more than 3 expanded documents', 'wide.zip: 5 of 8 listed entries...']`.*

## 5. Schema step 8

- [x] 5.1 Append the `ingest_runs` step to `_STEPS`; verify `_SCHEMA` is untouched and `SCHEMA_VERSION` still derives itself from the ladder. *`_SCHEMA` unchanged; `test_the_version_is_derived_from_the_ladder` and `test_the_ladder_and_the_baseline_produce_the_same_schema` green.*
- [x] 5.2 Verify no trigger is needed — `casefiles.id` is a real foreign-key parent and `PRAGMA foreign_keys=ON` is set in `initialize`; the sidecar trigger exists only for virtual tables. *Not argued, asserted: `test_deleting_a_casefile_deletes_its_ingest_records`. Mutation 8 dropped `ON DELETE CASCADE` and it reddened with `sqlite3.IntegrityError: FOREIGN KEY constraint failed`.*
- [x] 5.3 Verify no row is backfilled, and that an existing casefile having no row is exactly what reads as `unknown`. *`test_an_older_store_gains_the_ingest_run_record` asserts `ingestion_coverage("c1").runs == 0` for the baseline store's pre-existing casefile.*
- [x] 5.4 **Added during the work:** guard that the ladder's versions strictly increase. *Not in the plan, and it is the one thing that made mutation 7 provable. `migrate` computes the store's version once and then runs every step whose `to_version` exceeds it, so from the baseline a duplicated version still applies and looks healthy — it is skipped only on a store already stamped at that version, which is every store already in service. `test_the_ladder_versions_strictly_increase` asserts the property; mutating `to_version=8` to `7` reddens it with "got [5, 6, 7, 7]".*

## 6. One write, one aggregate read

- [x] 6.1 Add `IngestRun` and `IngestionCoverage` to `storage/port.py`; verify `IngestionCoverage` holds counted facts only and no verdict. *Ten and eight fields respectively, no verdict field; the verdict lives in `CasefileService.coverage`.*
- [x] 6.2 Implement both methods in `sqlite.py` following `casefile_statistics`' shape — one lock hold, aggregates in the database, the alias-to-field mapping written out. *Three statements in one `with self._lock:`, so the totals, the earliest run and the bounds describe one instant.*
- [x] 6.3 Read `documents_before_first_run` with an ordered `LIMIT 1` rather than `MIN`; verify the tie-break on `id` makes it deterministic. *Exercised with two runs whose `documents_before` are 0 and 1 and whose order is decided by `started_at`; the earliest run's 0 is returned, which `MIN` would also give but for the wrong reason.*

## 7. Write the record, expose the verdict

- [x] 7.1 Capture `started_at` and `documents_before` before the budget is built; verify `documents_before` is read once and nowhere later. *One read site in `ingest`, before the workspace exists.*
- [x] 7.2 Record the run after the loop, not in a `finally`; verify a run that raised leaves no row and the write is allowed to raise. *`test_the_workspace_is_removed_even_when_the_ingest_raises` already drives an ingest that raises mid-run; the record is after the `finally`, so no row is written for it. **Insufficient as first written, and corrected after review**: leaving a raised run unrecorded only makes the verdict `unknown` for a *first* run. Three reviewers reproduced the consequence by execution — an abort after a clean run read `complete` with four documents held against six offered. Each row now carries `documents_after` as well as `documents_before`, and a gap between consecutive runs is a continuity break forcing `unknown`, which also catches a killed process and a failed record write. Pinned by `test_a_run_that_raised_part_way_keeps_the_verdict_unknown` and mutation-proved.*
- [x] 7.3 Add `CasefileCoverage` and `CasefileService.coverage`; verify the verdict is the service's rule and the counts stay the store's. *`test_no_adapter_reaches_the_store` still green, which is what forced the method onto the service rather than letting the tool reach the store.*

## 8. Adapters, in one vocabulary

- [x] 8.1 Add `render_report` to `rendering.py`; verify there is no import cycle and the `outcomes` entries keep exactly the five keys both adapters already emit. *Import checked directly: `from jackryan.rendering import render_report` resolves. Five keys unchanged.*
- [x] 8.2 Return it from both the CLI `--json` branch and REST; verify the two payloads have identical key sets. *`test_the_two_human_surfaces_return_the_same_ingest_result`, plus a live check: both surfaces returned the same nine keys and the same values for a folder holding a good file, an unroutable file and an empty one. Mutation 14 gave REST its own dict back and it reddened on the key sets.*
- [x] 8.3 Extend the CLI human branch; verify the `N ingested, M failed` line keeps its exact wording and the exit-code rule is unchanged. *`test_cli.py:89`'s substring untouched. Two tests, not one: mutation 15 deleted the warning block and reddened the incomplete case; mutation 15b made the warning unconditional and reddened the clean case. A summary that always warns teaches an operator to ignore it.*
- [x] 8.4 Add the `ingestion` key and one verdict-chosen `formatted` line to `case_casefile_overview`; verify the third service call sits inside `@returns_error_payload`. *Key set extended, never relaxed — it caught the new key on first run, which is the assertion working. Mutation 9 renamed the key to `ingest` and it reddened.*
- [x] 8.5 Extend the tool description and `INSTRUCTIONS`; verify the instructions still carry `"coverage"` for the existing assertion. *Checked mechanically after a botched edit had duplicated step 2 and clobbered `case_mentions`: seven numbered steps, seven distinct tool names, `case_casefile_overview` appearing once.*

## 9. Tests, each shown red first

- [x] 9.1 Three in `test_ingestion.py`: a failed document makes the run incomplete; an unroutable file is reported as skipped; a clean run reports complete.
- [x] 9.2 Three in `test_containers.py`: a refused entry reaches the report; undelivered entries are reported; a bound is not reported twice.
- [x] 9.3 One in `test_migrations.py`: an older store gains `ingest_runs` and its existing document still reads. *Two stores, and the docstring records that this test cannot pin `to_version` — its notion of "the previous version" is derived from `_STEPS`, so a duplicated version moves it too. Task 5.4 is what pins it.*
- [x] 9.4 One in `test_store.py`: deleting a casefile deletes its ingest records, and no other casefile's.
- [x] 9.5 Five in `test_mcp_surface.py`: the key set extended, plus the four verdict branches as separate tests. *Separate rather than parametrised, following the convention the expansion-clause pair states: branches asserting opposite things about one string belong in separate tests.*
- [x] 9.6 One in `test_result_shape.py`: the two human surfaces return the same ingest result. *Needed a `rest_post` helper — the module's existing driver is GET-only. Two casefiles ingesting one folder means `casefile_id` and each outcome's `document_id` differ by construction, so both are excluded from the value comparison and separately asserted present.*
- [x] 9.7 Two in `test_cli.py`: an incomplete run says so, and a clean run does not.

## 10. One parked note

- [x] 10.1 Record the per-entry ceiling's three copies, what the reconciliation does and does not disclose, why a declared-size refusal was rejected, and what the honest fix would cost. *In `docs/implementation-notes.md` under `## Parked`.*

## 11. Prove every guard fails against the defect

- [x] 11.1 Run the mutation table: apply, run only that test, confirm it fails naming the symptom, restore. A guard not shown red certifies nothing. **16/16 red.** *The harness needed two adaptations, both measured rather than assumed. Copying `.venv` per `skill://mutation-harness-for-uv-python` made one test take 84s instead of 4s and the interpreter exit -11, because `sqlite_vec` ships a loadable `.dylib` macOS re-validates and then crashes unloading; only the sources are copied and the original interpreter runs them under `PYTHONPATH=<copy>/src`, with `jackryan.__file__` asserted inside the copy. And the verdict is read from pytest's own summary, never the exit code: this suite segfaults at teardown even on a single passing node. An unmutated control was GREEN on all 16 nodes first.*

## 12. Sync, review, merge

- [x] 12.1 `pytest -q` green, and `openspec validate --all --strict` again. *728 passed, 3 skipped, from a 713-passed baseline. 18/18 specs.*
- [x] 12.2 Drive the agent journey through a reopened store: ingest, new process, `case_casefile_overview`. *Through real stdio against `jackryan serve-mcp`, a separate process from the ingest. `coverage: "incomplete"`, `runs_recorded: 1`, `runs_with_limitations: 1`, `files_without_extractor: 1`, and the formatted line beginning `coverage: incomplete — 1 of 1 recorded ingest runs reported a limitation`.*
- [x] 12.3 Verify the `unknown` case on a corpus that predates the record. *The run rows deleted to stand in for a pre-change corpus, then one clean ingest on top: the CLI printed `1 ingested, 0 failed` with no limitation, and the overview still said `coverage: unknown` with `documents_predating_the_record: 1` and `runs_with_limitations: 0`. A two-state verdict would have claimed `complete` there, which is the defect the whole design exists to prevent.*
- [x] 12.4 Verify REST and the CLI agree on a live instance. *A live uvicorn instance returned `"complete": false`, `"limitations": ["1 offered file has no registered extractor"]`, `"skipped": ["activate.bat"]`, `"refusals": []`, `"exhausted_by": null` — the same nine field names and the same values the CLI's `--json` printed for the same folder.*
- [x] 12.5 Verify an older store is carried forward and its backup sits beside it. *A baseline store opened, gained all ten `ingest_runs` columns, kept its pre-existing document text, and left `old.db.v4.bak` (118,784 bytes) beside it.*
- [x] 12.6 `openspec archive disclose-incomplete-ingestion`, review the diff, merge, remove the worktree, tick the review todo with its evidence.
