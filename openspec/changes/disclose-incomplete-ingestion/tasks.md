## 1. The rule in the published specs

- [ ] 1.1 Add `ingestion-coverage` as a new capability delta, every block `## ADDED Requirements` with a `## Purpose`; verify a `Purpose` is honoured for a new capability rather than silently ignored as it is for an existing one.
- [ ] 1.2 Establish by falsification that no `MODIFIED` block is owed, re-reading each published text rather than judging by topic; record the table in the proposal's `## Impact`.
- [ ] 1.3 `openspec validate --all --strict` before any code is written.

## 2. One definition of incompleteness

- [ ] 2.1 Add `IngestReport.skipped`; verify it is counted apart from `refusals` and that the comment says why the two want different words.
- [ ] 2.2 Replace `complete` with derived `limitations` + `complete`; verify every existing assertion on `complete` still passes, and that a failed document now makes a run incomplete.

## 3. What the extractors already refused

- [ ] 3.1 Return the `Extraction` from `_ingest_work` as a third element; verify the `except ConfigError: raise` clause is untouched and still above the per-document handler.
- [ ] 3.2 Extend the run's refusals with `extraction.refusals`, prefixed by the container's containment path; verify a traversing zip entry now reaches the report, which before this only existed on the `Extraction`.
- [ ] 3.3 Route an unroutable folder file to `skipped` and an unroutable container entry to `refusals`; verify the container branch keeps its wording verbatim so the two existing assertions stay green.

## 4. Listed against delivered

- [ ] 4.1 Pass the `Extraction` into `_expand`; add `stopped_by_budget` and `expansion_failed` locals.
- [ ] 4.2 Reconcile `metadata["entries"]` against `len(produced)`; verify `isdigit()` guards the parse so the mail extractors are skipped rather than compared against zero.
- [ ] 4.3 Suppress the shortfall where a bound stopped the container or its expansion raised; verify exactly one refusal is reported, not two.

## 5. Schema step 8

- [ ] 5.1 Append the `ingest_runs` step to `_STEPS`; verify `_SCHEMA` is untouched and `SCHEMA_VERSION` still derives itself from the ladder.
- [ ] 5.2 Verify no trigger is needed — `casefiles.id` is a real foreign-key parent and `PRAGMA foreign_keys=ON` is set in `initialize`; the sidecar trigger exists only for virtual tables.
- [ ] 5.3 Verify no row is backfilled, and that an existing casefile having no row is exactly what reads as `unknown`.

## 6. One write, one aggregate read

- [ ] 6.1 Add `IngestRun` and `IngestionCoverage` to `storage/port.py`; verify `IngestionCoverage` holds counted facts only and no verdict.
- [ ] 6.2 Implement both methods in `sqlite.py` following `casefile_statistics`' shape — one lock hold, aggregates in the database, the alias-to-field mapping written out.
- [ ] 6.3 Read `documents_before_first_run` with an ordered `LIMIT 1` rather than `MIN`; verify the tie-break on `id` makes it deterministic.

## 7. Write the record, expose the verdict

- [ ] 7.1 Capture `started_at` and `documents_before` before the budget is built; verify `documents_before` is read once and nowhere later.
- [ ] 7.2 Record the run after the loop, not in a `finally`; verify a run that raised leaves no row and the write is allowed to raise.
- [ ] 7.3 Add `CasefileCoverage` and `CasefileService.coverage`; verify the verdict is the service's rule and the counts stay the store's.

## 8. Adapters, in one vocabulary

- [ ] 8.1 Add `render_report` to `rendering.py`; verify there is no import cycle and the `outcomes` entries keep exactly the five keys both adapters already emit.
- [ ] 8.2 Return it from both the CLI `--json` branch and REST; verify the two payloads have identical key sets.
- [ ] 8.3 Extend the CLI human branch; verify the `N ingested, M failed` line keeps its exact wording and the exit-code rule is unchanged.
- [ ] 8.4 Add the `ingestion` key and one verdict-chosen `formatted` line to `case_casefile_overview`; verify the third service call sits inside `@returns_error_payload`.
- [ ] 8.5 Extend the tool description and `INSTRUCTIONS`; verify the instructions still carry `"coverage"` for the existing assertion.

## 9. Tests, each shown red first

- [ ] 9.1 Three in `test_ingestion.py`: a failed document makes the run incomplete; an unroutable file is reported as skipped; a clean run reports complete.
- [ ] 9.2 Three in `test_containers.py`: a refused entry reaches the report; undelivered entries are reported; a bound is not reported twice.
- [ ] 9.3 One in `test_migrations.py`: an older store gains `ingest_runs` and its existing document still reads.
- [ ] 9.4 One in `test_store.py`: deleting a casefile deletes its ingest records, and no other casefile's.
- [ ] 9.5 Five in `test_mcp_surface.py`: the key set extended, plus the four verdict branches as separate tests.
- [ ] 9.6 One in `test_result_shape.py`: the two human surfaces return the same ingest result.
- [ ] 9.7 Two in `test_cli.py`: an incomplete run says so, and a clean run does not.

## 10. One parked note

- [ ] 10.1 Record the per-entry ceiling's three copies, what the reconciliation does and does not disclose, why a declared-size refusal was rejected, and what the honest fix would cost.

## 11. Prove every guard fails against the defect

- [ ] 11.1 Run the mutation table: apply, run only that test, confirm it fails naming the symptom, restore. A guard not shown red certifies nothing.

## 12. Sync, review, merge

- [ ] 12.1 `pytest -q` green, and `openspec validate --all --strict` again.
- [ ] 12.2 Drive the agent journey through a reopened store: ingest, new process, `case_casefile_overview`.
- [ ] 12.3 Verify the `unknown` case on a corpus that predates the record.
- [ ] 12.4 Verify REST and the CLI agree on a live instance.
- [ ] 12.5 Verify an older store is carried forward and its backup sits beside it.
- [ ] 12.6 `openspec archive disclose-incomplete-ingestion`, review the diff, merge, remove the worktree, tick the review todo with its evidence.
