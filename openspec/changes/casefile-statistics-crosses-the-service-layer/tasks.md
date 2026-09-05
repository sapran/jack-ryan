## 1. The rule in the published specs

- [x] 1.1 MODIFY `storage-seam`'s *All persistence goes through the storage port*, reproducing its published scenario verbatim and adding two; verify the additions make the requirement's existing SHALLs testable rather than asserting anything new. *Both sentences were already in the requirement — "no adapter SHALL reach a store directly" and the port "SHALL speak in domain objects rather than rows" — and neither had a scenario. 1/1 reproduced, +2, checked mechanically.*
- [x] 1.2 Establish by falsification that `service-adapter-boundary` needs no delta; verify by reading what its scenario actually asks, not by whether the change feels adapter-shaped. *Its scenario asks that no adapter "validates input or resolves references itself". The old code resolved through `context.casefiles.resolve`, so it satisfied that — what it did wrong was reach a store, which is `storage-seam`'s rule. A MODIFIED block would be byte-identical; cut. Recorded in the proposal's Impact.*
- [x] 1.3 Confirm `mcp-tool-surface` needs no delta; verify the payload is unchanged rather than assuming it. *Asserted by the tool's new key-set test, which passed against the unchanged code before anything moved and still passes after.*

## 2. The tool's first test, before anything moves

- [x] 2.1 Add a behavioural test for `case_casefile_overview`; verify it passes against the **unchanged** code, so it characterises what ships rather than what is about to be written. *Passed on the pre-change tool. Nothing had exercised this tool before — its only occurrence outside `src/` asserted that the analyst pack mentions the name.*
- [x] 2.2 Assert the payload's key set exactly rather than key by key; verify the assertion catches a renamed key, which is the failure the SQL aliases invite. *Watched failing by renaming `documents_ingested` to the SQL's `ingested`: `Extra items in the left set: 'ingested'` / `right set: 'documents_ingested'`. Key-by-key assertions would all still have passed.*

## 3. The domain object

- [x] 3.1 Add `CasefileStatistics` to `storage/port.py` as a frozen dataclass and retype the port method; verify the field names are the payload's, not the SQL's, and that the reason is recorded where the next reader meets it. *Named in the dataclass docstring: `documents_ingested` reads as what it is, where a bare `ingested` beside `documents` reads as a different unit.*
- [x] 3.2 Return it from `SqliteStore.casefile_statistics` with the SQL untouched; verify only the packing changed. *Both queries are byte-identical; the `return` is the only edit, plus a docstring paragraph explaining why the aliases and the fields differ on purpose.*
- [x] 3.3 Keep `by_type` a mapping; verify a precedent exists for a mapping inside a frozen dataclass rather than arguing it from convenience. *`Extraction.metadata` is a `dict[str, str]` in a frozen dataclass. Cited in the design so the purity argument does not have to be re-had.*

## 4. The seam

- [x] 4.1 Add `CasefileService.statistics`; verify it resolves like the service's other queries rather than taking an id. *Mirrors `SearchService.mention_facets` and `IngestionService.list_documents`, both of which resolve then delegate.*
- [x] 4.2 Point `case_casefile_overview` at it and convert ten subscripts to attribute reads; verify `context.store` no longer appears anywhere under `interfaces/`. *Grepped clean, and now asserted by 4.4 rather than by the grep.*
- [x] 4.3 Declare `Context.store` as `StorePort`; verify the claim is recorded as documentation rather than described as a guard, since no type checker runs here. *Stated in the field's docstring, including that several tests reach `context.store._db` and would be flagged by a checker if one were added.*
- [x] 4.4 Add `test_no_adapter_reaches_the_store`, matching the attribute reach by parsing; verify a literal search would have been defeated by binding the store to a name first, and that a comment cannot trip the parsed version. *Any `<expr>.store` under `interfaces/` is reported. Watched failing by restoring the old call: `assert not ['server.py:171']`. The test's own docstring names `context.store` and does not trip it.*

## 5. Verification

- [x] 5.1 Convert the four tests that called the store directly; verify each moves to the service method rather than to a different store call. *`test_containers.py`, `test_regressions_m2.py` and two in `test_summarising.py`, all now `context.casefiles.statistics(...)`. They failed loudly first with `TypeError: 'CasefileStatistics' object is not subscriptable`, which is the change working as intended.*
- [x] 5.2 Run the full suite; verify the count rises by exactly the two new tests. *693 → 694 with the guard added; 692 before this change, so +2 and no test lost.*
- [x] 5.3 Read the whole diff before committing; verify no mutation from 2.2 or 4.4 survived. *Both reversed and re-grepped: no `context.store` under `interfaces/`, and the payload key is `documents_ingested`.*
- [x] 5.4 Run `openspec validate --all --strict` and the mechanical title audit.
