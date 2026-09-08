## 1. The rule in the published specs

- [ ] 1.1 Write four `MODIFIED` deltas — `document-ingestion`, `document-hierarchy` (two requirements), `untrusted-content-boundary`, `mcp-tool-surface` — reproducing every existing scenario verbatim and retitling none.
- [ ] 1.2 Establish by falsification that no delta is owed for `ingestion-coverage`, `schema-migration`, `storage-seam` or `hybrid-search`, re-reading each published text rather than judging by topic; record the table in the proposal's `## Impact`.
- [ ] 1.3 `openspec validate --all --strict` before any code is written.

## 2. Schema step 9

- [ ] 2.1 Append one `_Step` creating `document_locations` with a composite primary key and `ON DELETE CASCADE`; verify no separate index is added and `SCHEMA_VERSION` stays derived.
- [ ] 2.2 Add `documents.locations_recorded` with a constant default of 0; verify `_SCHEMA` and `BASELINE_DOCUMENT_COLUMNS` are untouched and the frozen-baseline test still passes.
- [ ] 2.3 Verify `test_no_step_is_destructive` and the baseline-equals-ladder test both pass with the new rung.

## 3. The port speaks in domain objects

- [ ] 3.1 Add `DocumentLocation` and `DocumentLocationSet` as frozen dataclasses, with `truncated` derived rather than stored.
- [ ] 3.2 Add `locations_recorded` and `location_count` to `Document`, both defaulted, with the comment saying why `False` is the honest default.
- [ ] 3.3 Declare `record_document_location` and `document_locations` on `StorePort`.

## 4. The store stops overwriting, and records

- [ ] 4.1 Remove `filename` and `containment_path` from `upsert_document`'s `DO UPDATE SET`, leaving the comment that states the rule; verify the trailing comma moved to the new last clause.
- [ ] 4.2 Add `locations_recorded` to the insert list and **not** to `DO UPDATE SET`; verify a reingest cannot raise a migrated document's flag.
- [ ] 4.3 Implement `record_document_location` with `INSERT OR IGNORE` returning whether the row was new; verify `OR REPLACE` would report every reingest as a discovery.
- [ ] 4.4 Implement `document_locations` with a total ordering and a bound; verify the count is of the whole set, not of the page.
- [ ] 4.5 Add the `location_count` correlated subquery to `list_document_page` beside the existing `child_count` one.

## 5. The verdict, and the vocabulary

- [ ] 5.1 Add `MAX_DOCUMENT_LOCATIONS` and the six vocabulary constants.
- [ ] 5.2 Add `IngestOutcome.location`, defaulted to empty for an outcome that never got that far.
- [ ] 5.3 Add `IngestReport.new_locations`, derived, and verify it is **not** folded into `limitations`.
- [ ] 5.4 Add `DocumentLocationRecord` with `also_found_at`, `truncated` and the single-sourced `note`.
- [ ] 5.5 Record the location in `_ingest_work` after the upsert and before the chunks, and decide the four-value verdict with `unknown` tested before the store's answer.
- [ ] 5.6 Add `IngestionService.document_locations`, resolving through `resolve_document`.

## 6. Every surface

- [ ] 6.1 Add `location` to the shared `render_report` so neither human surface can drift.
- [ ] 6.2 CLI: mark a multi-location document in a listing, report the full record in `document show` and its `--json` form, and print the new-locations block below the limitations one.
- [ ] 6.3 REST: return the record on the document detail route only, leaving `serialize_document` shared and unwidened.
- [ ] 6.4 MCP: emit a `locations` provenance block only when it says something; mark a listing row; extend the two tool descriptions.
- [ ] 6.5 Verify `case_search`, `case_cite` and `case_get_passage` are untouched.

## 7. Proof

- [ ] 7.1 Ten tests in `tests/test_document_locations.py`, including the negative twin that stops the provenance block being emitted unconditionally.
- [ ] 7.2 One test in `tests/test_migrations.py` for a document carried forward from a v4 baseline, staying `unknown` across a reingest.
- [ ] 7.3 Eleven mutations, each red with the symptom its test is named for, against a green unmutated control.
- [ ] 7.4 Gates: `pytest -q`, `openspec validate --all --strict`, `gitleaks detect`.
- [ ] 7.5 End-to-end synthetic proof under a temporary data directory, including through a real `serve-mcp` stdio process and a v4 store carried forward.
- [ ] 7.6 Tick `docs/functional-review-todo.md` item 5 with its evidence.
