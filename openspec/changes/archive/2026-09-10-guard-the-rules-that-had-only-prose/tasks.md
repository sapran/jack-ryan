# Tasks

Waves are ordered by file ownership, not by number. Every task's acceptance is
observable; no task is complete on an agent's report alone. Evidence is the
italic note beside each box: the command run, the figure observed, or the
mutation watched.

## Wave 1 — the two units with disjoint files

### 1. One continuation rule for all three paged listings

- [x] 1.1 Add `BoundedPage` to `storage/port.py` exactly as `design.md` fixes it: a plain class, not a dataclass, with an `entries` property raising `NotImplementedError`. *Shipped at `6f0e31e`.*
- [x] 1.2 Make `DocumentPage`, `MentionDocumentPage` and `DocumentPassagePage` inherit it, each supplying `entries`, and delete the six copied property bodies. *Eight property bodies deleted; `grep "def truncated\|def continue_from\|def beyond_the_end"` returns one of each, on `BoundedPage`.*
- [x] 1.3 Confirm no constructor signature moved: every field stays declared on its own page, in its current order. *`dataclasses.fields()` and `inspect.signature()` compared against `develop` for all three pages by the implementer and again by review: identical.*
- [x] 1.4 `DocumentPage` now has `beyond_the_end`; `_nothing_listed` in `interfaces/mcp/server.py` reads it instead of `page.offset and page.total_matching`. *No `page.offset and page.total_matching` remains in the module.*
- [x] 1.5 Regression test: the three pages agree on all three properties, driven from constructed pages rather than through a store. *`tests/test_document_paging.py`, +38 cases, including a vacuity guard that a truncated and a past-the-end page are actually exercised.*
- [x] 1.6 Mutation proof. *M1 restored the inline re-derivation → 3 failed in `test_document_paging.py`. M2 forced `beyond_the_end` to `False` → 12 failed across three files. Both on isolated copies, green control either side.*

### 2. One renderer for the location record and the carrier envelope

- [x] 2.1 Add `render_location_record` and `render_carrier_page` to `rendering.py` with the signatures `design.md` fixes. *Shipped at `c8ab23d`, plus `location_paths`, the third shared name — recorded in `design.md`.*
- [x] 2.2 `cli.py` and `server.py` call them; neither adapter spells a location **detail** key or an envelope key any more. *`locations_recorded` and `locations` remain in `cli.py`, deliberately: its non-JSON path prints those two columns, and it now reads them off the shared block. The original wording of this task claimed all five keys were gone from both adapters, which was never what was built.*
- [x] 2.3 Both payloads stay byte-identical, including the CLI's empty-note omission and its two-key non-JSON path. *Implementer compared `json.dumps(indent=2)` of each of the four payloads, built from `develop`'s code and from the shipped adapters, across five document shapes: 10 comparisons, 0 differences, key order included. Review re-verified independently.*
- [x] 2.4 Guard: neither adapter contains the three location **detail** key literals (`observed_at`, `locations_truncated`, `locations_note`), so a third human surface cannot re-copy the block. *`test_only_the_shared_renderer_spells_the_location_detail_keys`; it asserts the three keys ARE found in `rendering.py` first, so it cannot pass by scanning nothing.*
- [x] 2.5 Mutation proof. *M3 renamed `observed_at` in the shared renderer → 2 failed, one being the cross-surface parity test. M13 added the literal back to `cli.py` → the guard failed. Both on copies.*

## Wave 2 — three units, disjoint from each other

### 3. The service says why coverage is unknown

- [x] 3.1 Add the four ground constants and `CasefileCoverage.ground`. *Shipped at `ed37cf6`.*
- [x] 3.2 `CasefileService.coverage` decides the ground with the precedence in `design.md`, and the verdict logic is unchanged. *The verdict block is byte-identical to `develop`; only the ground is new.*
- [x] 3.3 The overview tool selects its sentence from `coverage.ground` and re-derives nothing. *No `recorded.runs == 0` / `continuity_breaks` / `documents_before_first_run` test remains in the sentence ladder; the counts are still printed inside the sentences.*
- [x] 3.4 All three sentences reachable today are byte-identical; no payload key is added. *Both versions parsed with `ast` and every `coverage_line` expression compared whole, interpolations included: all five pre-existing expressions unchanged.*
- [x] 3.5 Test each ground, including a casefile carrying two at once. *`test_no_recorded_run_outranks_the_other_two_grounds` and `test_a_continuity_break_outranks_documents_that_predate_the_record`, each asserting both grounds are genuinely present before asserting which sentence wins.*
- [x] 3.6 Mutation proof. *M6 made the service name the wrong ground → 2 failed in `test_mcp_surface.py`.*

### 4. A named result at the store seam

- [x] 4.1 Add frozen `StoredDocument`; `store_document` returns it in `port.py` and `sqlite.py`. *Shipped at `7ce5bb5`; constructed by keyword after review, so a field reordering cannot silently rebind the pair.*
- [x] 4.2 `services/ingestion.py` reads the two attributes; no tuple unpacking remains. *`grep store_document src/` shows two defs, one comment and one call site.*
- [x] 4.3 Guard in `tests/test_store.py`: walk `StorePort`'s AST and reject an unnamed return, asserting the walk was non-empty. *34 protocol methods inspected against a floor of 25, with `store_document` required among the names read. Hardened after review to judge unions and container elements recursively, and to derive permitted `dict` value types only from `@dataclass`-decorated classes in `port.py`.*
- [x] 4.4 Mutation proof. *M4 `-> tuple[Document, bool]` and M5 `-> dict[str, str]` each failed naming the offending method. Review then proved three further shapes passed — `tuple[...] | None`, `list[tuple[...]]`, `Sequence[tuple[...]]` — and a `TypedDict` value type; all four are red after the hardening, with the same green control.*

### 5. Guards for the invariants that had prose only

- [x] 5.1 New `tests/test_architecture_invariants.py`; touch no other file. *Shipped at `5d57add`.*
- [x] 5.2 `services/search.py` does not re-export `MAX_RESPONSE_CHARS`. *Also refuses a star-import from `windowing`, which would bind it invisibly.*
- [x] 5.3 `CorpusIdentity` has no `parse`. *And no `from_string`: the refusal is of the capability, not of one spelling.*
- [x] 5.4 `storage/sqlite.py` reaches `migrations` by attribute, never by `from`-import. *`from . import migrations` is deliberately not matched — that is the required form.*
- [x] 5.5 No two file-signature literals hold the same value. *Duplicate detection, not location: `containers.py`'s RAR signatures legitimately live outside `sniffing.py` because they answer which reader to use, not what a file is.*
- [x] 5.6 Nothing under `interfaces/` imports `rendering`. *Scans at least five modules and requires at least five relative imports found, so an empty walk cannot pass.*
- [x] 5.7 Every guard asserts its own scan was non-empty. *Each also carries a positive control — the same detector pointed at a file that legitimately holds what it hunts.*
- [x] 5.8 Mutation proof for each of 5.2–5.6. *M7 re-exported the budget; M8 added a `parse`; M9 from-imported `migrations`; M10 duplicated `_ZIP_MAGIC`; M11 imported `rendering` from the agent surface. Each failed on its own named guard. M8 first failed for the wrong reason — a syntax error from a badly placed insertion — and was corrected and re-run before being counted.*

## Wave 3 — the leftover, run inline

### 6. One listing bound

- [x] 6.1 One `DEFAULT_LISTING_PAGE` and one `MAX_LISTING_PAGE` in the service layer; the three pairs are gone with no alias left behind. *Shipped at `7924727`; `grep` for all six old names returns nothing in `src/` or `tests/`.*
- [x] 6.2 Every service method and adapter default imports them; the effective numbers stay 50 and 200. *Asserted by importing them in the worktree: 50 and 200.*
- [x] 6.3 `MAX_SEARCH_RESULTS` is untouched and the clamped search maximum is still 50. *Confirmed 50. Mutation then showed nothing guarded it — raising it to 200 left the whole suite green — so `test_the_agent_search_bound_is_not_the_listing_bound` was added at `d79815b` and proved twice: raised to 200, and coupled to `DEFAULT_LISTING_PAGE`.*

## Gates and closeout

- [x] 7.1 Full suite green after each wave. *Run uv-free, because the worktree deliberately has no virtualenv: `PYTHONPATH=$PWD/src <main venv>/bin/python -m pytest -q -p no:cacheprovider`. Baseline on `develop` was 830 passed / 3 skipped; wave 1 `c8ab23d` 869/3; wave 2 `5d57add` 882/3; wave 3 and the added guard `d79815b` 883/3. The earlier `uv run pytest -q` wording in this file named a command that was never used here.*
- [x] 7.2 `openspec validate --all --strict` green. *19 passed, 0 failed, re-run after the delta and Purpose edits.*
- [x] 7.3 Every mutation actually watched, with a green control before and after. *17 in total, each applied to an isolated copy of the tree with `PYTHONPATH` pointed at that copy and the import resolution proved by printing `__file__` first. Two initially went red for the wrong reason (a syntax error, an import error) and were corrected before counting.*
- [x] 7.4 Two independent reviewers on the diff; every finding fixed or dismissed with a reason. *`reviewer` and `security-reviewer` in parallel; no must-fix on the code. Two mutation-verified guard blind spots fixed, three record inaccuracies corrected in this file, one stale constant name fixed in the notes, the published `Purpose` extended, and one out-of-scope finding parked.*
- [ ] 7.5 `openspec archive`, with `### Requirement:`/`#### Scenario:` counts compared before and after for both touched specs.
- [ ] 7.6 Merge into `develop`, push, tear down the worktree, main checkout clean.
