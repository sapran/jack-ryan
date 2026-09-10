# Tasks

Waves are ordered by file ownership, not by number. Every task's acceptance is
observable; no task is complete on an agent's report alone.

## Wave 1 — the two units with disjoint files

### 1. One continuation rule for all three paged listings

- [ ] 1.1 Add `BoundedPage` to `storage/port.py` exactly as `design.md` fixes it: a plain class, not a dataclass, with an `entries` property raising `NotImplementedError`.
- [ ] 1.2 Make `DocumentPage`, `MentionDocumentPage` and `DocumentPassagePage` inherit it, each supplying `entries`, and delete the six copied property bodies.
- [ ] 1.3 Confirm no constructor signature moved: every field stays declared on its own page, in its current order.
- [ ] 1.4 `DocumentPage` now has `beyond_the_end`; `_nothing_listed` in `interfaces/mcp/server.py` reads it instead of `page.offset and page.total_matching`.
- [ ] 1.5 Regression test: the three pages agree on all three properties, driven from constructed pages rather than through a store.
- [ ] 1.6 Mutation proof: restore the inline re-derivation in `_nothing_listed`, and separately drop `beyond_the_end` from one page, and record that each goes red.

### 2. One renderer for the location record and the carrier envelope

- [ ] 2.1 Add `render_location_record` and `render_carrier_page` to `rendering.py` with the signatures `design.md` fixes.
- [ ] 2.2 `cli.py` and `server.py` call them; no location key and no envelope key is spelled in either adapter any more.
- [ ] 2.3 Both payloads stay byte-identical, including the CLI's empty-note omission and its two-key non-JSON path.
- [ ] 2.4 Guard: neither adapter contains the five location key literals, so a sixth surface cannot re-copy them.
- [ ] 2.5 Mutation proof: change one key in the shared renderer and record that both surfaces' parity tests go red.

## Wave 2 — three units, disjoint from each other

### 3. The service says why coverage is unknown

- [ ] 3.1 Add the four ground constants and `CasefileCoverage.ground`.
- [ ] 3.2 `CasefileService.coverage` decides the ground with the precedence in `design.md`, and the verdict logic is unchanged.
- [ ] 3.3 The overview tool selects its sentence from `coverage.ground` and re-derives nothing.
- [ ] 3.4 All three sentences reachable today are byte-identical; no payload key is added.
- [ ] 3.5 Test each ground, including a casefile carrying two at once, which no scenario covered before.
- [ ] 3.6 Mutation proof: return the wrong ground from the service and record the tool's sentence going red.

### 4. A named result at the store seam

- [ ] 4.1 Add frozen `StoredDocument`; `store_document` returns it in `port.py` and `sqlite.py`.
- [ ] 4.2 `services/ingestion.py` reads the two attributes; no tuple unpacking remains.
- [ ] 4.3 Guard in `tests/test_store.py`: walk `StorePort`'s AST and reject a bare or subscripted `dict`/`tuple` return annotation, asserting the walk was non-empty.
- [ ] 4.4 Mutation proof: add a method returning `tuple[Document, bool]` and record the guard going red for that method by name.

### 5. Guards for the invariants that had prose only

- [ ] 5.1 New `tests/test_architecture_invariants.py`; touch no other file.
- [ ] 5.2 `services/search.py` does not re-export `MAX_RESPONSE_CHARS`.
- [ ] 5.3 `CorpusIdentity` has no `parse`.
- [ ] 5.4 `storage/sqlite.py` reaches `migrations` by attribute, never by `from`-import.
- [ ] 5.5 No two file-signature literals hold the same value.
- [ ] 5.6 Nothing under `interfaces/` imports `rendering`.
- [ ] 5.7 Every guard asserts its own scan was non-empty.
- [ ] 5.8 Mutation proof for each of 5.2–5.6: add the forbidden thing, record red, remove it.

## Wave 3 — the leftover, run inline

### 6. One listing bound

- [ ] 6.1 One `DEFAULT_LISTING_PAGE` and one `MAX_LISTING_PAGE` in the service layer; the three pairs are gone with no alias left behind.
- [ ] 6.2 Every service method and adapter default imports them; the effective numbers stay 50 and 200.
- [ ] 6.3 `MAX_SEARCH_RESULTS` is untouched and the clamped search maximum is still 50.

## Gates and closeout

- [ ] 7.1 `uv run pytest -q` green after each wave, against the 830-passed/3-skipped baseline.
- [ ] 7.2 `openspec validate --all --strict` green.
- [ ] 7.3 Every mutation above actually watched, with a green control before and after.
- [ ] 7.4 Two independent reviewers on the diff; every finding fixed or dismissed with a reason.
- [ ] 7.5 `openspec archive`, with `### Requirement:`/`#### Scenario:` counts compared before and after for both touched specs.
- [ ] 7.6 Merge into `develop`, push, tear down the worktree, main checkout clean.
