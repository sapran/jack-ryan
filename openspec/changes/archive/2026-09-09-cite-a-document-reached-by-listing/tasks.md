# Tasks

## 1. The storage seam

- [x] 1.1 Add `PassageReference` to `storage/port.py`: `id`, `document_id`,
  `ordinal`, `heading_path`, `char_start`, `char_end`, `characters`, and a
  `short_id` property. Document why it is not a `Chunk`.
- [x] 1.2 Add `DocumentPassagePage`: the passages, `total_matching`, `offset`,
  `limit`, and `document` set by the service. Derive `truncated`,
  `continue_from` and `beyond_the_end`.
- [x] 1.3 Declare `list_document_passage_page(document_id, offset, limit)` on
  `StorePort`, requiring the count under the same predicate, the total ordering,
  and no unbounded form.
- [x] 1.4 Implement it in `SqliteStore`: count, then the page chosen narrow and
  widened, ordered `ordinal, char_start, id`, both bounds floored where SQLite
  applies them.

## 2. The service layer

- [x] 2.1 Add `DEFAULT_PASSAGE_PAGE` and `MAX_PASSAGE_PAGE` beside the document
  page bounds in `services/ingestion.py`.
- [x] 2.2 Add `IngestionService.list_document_passage_page`: resolve the
  document through `resolve_document`, clamp both bounds at both ends, delegate,
  and attach the resolved document to the page.

## 3. The agent surface

- [x] 3.1 Add `_render_passage` and `_no_passages` to
  `interfaces/mcp/server.py`, the second answering the past-the-end page and the
  no-passages document as two different true statements.
- [x] 3.2 Add the `case_list_passages` tool: `casefile`, `document`, `offset`,
  `limit`; rows through `listing_payload`; `offset`, `total_matching`,
  `truncated`, `continue_from` and the resolved document echoed beside them.
- [x] 3.3 Admit it in `interfaces/mcp/profiles.py` and stamp it read-only in
  `interfaces/mcp/annotations.py`.
- [x] 3.4 Add it to `INSTRUCTIONS` as a step of the method, and point
  `case_read_document`'s and `case_list_documents`' descriptions at it.

## 4. REST

- [x] 4.1 Add `GET /api/casefiles/{reference}/documents/{document_reference}/passages`
  with the same parameters and field names, off the event loop.

## 5. The shipped pack

- [x] 5.1 Teach the route in `analyst/role.md`, in the step that already
  explains entering a container.

## 6. Tests

- [x] 6.1 `tests/test_document_passages.py`: the page sweep against an
  independent oracle — every passage exactly once, in ordinal order, both counts
  right at every page.
- [x] 6.2 Both bounds clamped at both ends, including a `limit` of 0 and an
  offset past the end preserving the true total.
- [x] 6.3 A document in another casefile refused, with the refusal naming
  nothing of that document.
- [x] 6.4 A document with no stored passages: an empty page that says what it
  means, driven by a real container holding no entries rather than by a
  hand-written row.
- [x] 6.5 The rows carry no passage text.
- [x] 6.6 REST and the agent surface agree field by field on a middle page.
- [x] 6.7 The journey through the tool surface with `case_search` removed from
  the server: intake, into the container, into a nested container, the passages
  of a chosen child, the passage read, the citation, and the citation's span
  checked against the original text.
- [x] 6.8 Update `test_an_agent_reaches_and_reads_a_child_without_searching` in
  `tests/test_document_paging.py`: its docstring records this gap and its
  citation goes through `case_search`. Both change.
- [x] 6.9 Add the tool's row to the advertised-parameter table in
  `tests/test_mcp_surface.py`.

## 7. Records

- [x] 7.1 Close the parked note in `docs/implementation-notes.md`, saying what
  closed it, and record anything this change found and did not fix.
- [x] 7.2 Record the capability and its verification in `docs/handover.md`.
- [x] 7.3 Add the pitfalls a directory listing does not show to `CLAUDE.md`:
  the prose-free listing promise, why all three paged listings choose a narrow
  query and widen afterwards, and why a document with no stored passages is a
  real state. Three rather than the two this task first named.

## 8. Gates

- [x] 8.1 `openspec validate --all --strict`.
- [x] 8.2 `uv run pytest -q`.
- [x] 8.3 `gitleaks detect --no-banner` and the tracked-tree grep for
  fingerprints.
- [x] 8.4 Mutation-prove every new guard: each must go red for the symptom it is
  named for, against a green control.
- [x] 8.5 Drive the journey through a real `jackryan serve-mcp` stdio process
  with `case_search` removed, on disposable synthetic data.

## Evidence

Every figure below is named with the commit it was taken at. A bare suite total
decays — `develop` moved twice during this change and any change merged
afterwards moves it again — so the test delta is stated separately, because it
survives concurrent work where a total does not.

**`develop` moved under this change, and the figures are restated for it.**
The branch was cut at `2c3afa2`, where the suite was **813 passed, 3 skipped**.
While it was in review, `develop` gained nine commits — PR #36
`migration-safe-location-identity` (schema rung 11 and `document_places`) and
PR #37's storage guidance — taking it to `1b4413c` at **817 passed, 3
skipped**. `develop` was merged in at `a55283e`; three files overlapped
(`CLAUDE.md`, `docs/implementation-notes.md`, `src/jackryan/storage/sqlite.py`)
and git resolved all three, which was then checked by diffing the merge result
against `develop` per file: **zero lines of `develop` deleted**, and both of its
new `implementation-notes` bullets present. An earlier draft of the handover
said **824 passed** and "eleven new tests"; that was measured before the
twelfth test existed and is corrected in place rather than quietly replaced.

**Gates at `debaa92`** (the tip: `a55283e` plus the tiebreak fixture fix):

- `uv run --no-sync pytest -q` → **830 passed, 3 skipped**, against **817
  passed, 3 skipped** at `1b4413c`. Attributed independently:
  `git diff 1b4413c debaa92 -- tests/ | grep -cE '^\+(async )?def test_'` →
  **13 added, 0 removed**.
- `openspec validate --all --strict` → **19 passed, 0 failed**.
- `gitleaks detect --no-banner` → **no leaks**; the tracked-tree grep for
  `/Users/`, `/home/`, `.ts.net`, `sk-`, `hf_`, `AKIA`, `ghp_` and
  `-----BEGIN` matches nothing.
- `docker compose build` → `jackryan:latest` built, both services.

**The acceptance journey, over a real MCP stdio transport.** A separate process
served the surface with `case_search` removed from the catalogue — the shipped
CLI has no flag for that, and a client that merely does not call a search
proves nothing — while the writer was closed first, so the store was genuinely
reopened. **37 checks, all passing, exit 0**, on disposable synthetic data
authored and retained by the harness: the intake, an archive of seven entries
paged four ways with no omission or duplication, a message's two attachments, a
nested archive entered from inside the first, a six-passage child indexed over
three pages in reading order, the chosen passage read, the citation's span
checked character-for-character against the authored text, an attachment cited
the same way, cross-casefile refusal in both directions disclosing nothing,
every pre-existing top-level call still answering, the empty archive reporting
that it has nothing to cite, and a page past the end saying something
different. Re-run after the `develop` merge, with the same result.

**Mutation table: 22 red, 3 green, every green one explained.** Control **29
passed** on every node, with the copied tree's editable `.pth` repointed into
the copy and the import asserted to resolve inside it — without which every
mutation reports green because the copy imports the original `src`.

**The verdict is read from pytest's summary line, never from the exit code**,
and that was got wrong first. This suite segfaults at interpreter teardown on a
*passing* node — the control returned `exit=-11` after reporting `29 passed` —
so the first isolation run scored a fully green control as a failure and
refused to proceed. Read from the exit code, the more dangerous direction is
the silent one: a mutated tree that passed every test and then crashed at
teardown would have been recorded RED with no failing test in it. The harness
now scores RED only when the summary reports `failed` or `error`, keeps the
exit-4 collection-error guard, and was self-tested against four summary shapes
— a teardown segfault, a genuine failure, a collection error, and a pass with
skips. `docs/handover.md` records the same trap for the task-1 harness, which
is where it should have been read from first.

| # | Mutation | Verdict |
|---|---|---|
| 1 | the count runs over every chunk in the store | RED — 5 tests |
| 2 | the page is ordered by identifier, not position | RED |
| 3 | the store trusts the caller's `limit` | RED |
| 4 | the store trusts the caller's `offset` | RED |
| 5 | the passage's text is aliased into `heading_path` | RED |
| 6 | the service does not clamp the limit | RED |
| 7 | the service does not clamp the offset | RED |
| 8 | a full document id bypasses the casefile check | RED — both surfaces |
| 9 | the resolved document is not echoed on the page | RED — 3 tests |
| 10 | `beyond_the_end` ignores the offset | RED — 2 tests |
| 11 | one message serves both empty pages | RED |
| 12 | a row addresses its document instead of its passage | RED — 4 tests |
| 13 | the index drops its content notice | RED |
| 14 | REST reports the whole document as this page | RED |
| 15 | `characters` is a constant | RED |
| 16 | `characters` measures the heading | RED |
| 17 | `characters` is `char_end - char_start` | **GREEN by construction** |
| 18 | `heading_path` is aliased from the identifier | RED |
| 19 | the inner ordering drops both tiebreaks | RED |
| 19a | the inner ordering drops only `char_start` | RED |
| 19b | the inner ordering drops only `id` | **GREEN, correct** |
| 20 | the outer ordering drops its tiebreak | **GREEN, accepted** |
| 21 | a row gains a clipped preview | RED |
| 22 | REST drops the passage short id | RED |
| 23 | the tool row drops its short id | RED — 5 tests |

Number **17** is green because the redundancy is provable, not because the
field is unguarded: `a-chunk-begins-where-its-text-does` made
`source[char_start:char_end] == text` an invariant, so no corpus this pipeline
writes can distinguish `LENGTH(text)` from the span. Asserting a difference was
tried and fails for every passage; `design.md` Decision 5 records the
measurement in place of its earlier argument.

Number **20** is green because the inner subquery selects one row per page, so
the outer ordering has nothing to reorder — the same accepted position
`_document_selection` records for `list_document_page`'s repeated ordering,
which is insurance against a query plan SQLite is free to change rather than a
guard a test can reach.

Number **19b** is green because it should be: `id` is the last resort in the
ordering, reached only where two passages share both an ordinal and a start —
two passages at the same place in the same document, which `hybrid-search`
itself calls the exception because "whichever is returned first, the caller is
reading the same words at the same place". **19a is the node that matters**, and
it only reddens because the fixture was rebuilt twice: the tied passages are
stored later-first, so rowid order contradicts position, *and* the later one
carries the lower identifier, so identifier order contradicts it too. With
either agreement left in place the test proved that some tiebreak existed
rather than that a value of the corpus decides, which is what its docstring and
the store's comment claim.

**Four mutations were refused by the harness before any verdict**, and each
refusal was a defect in the mutation rather than in the guard: two anchors
matched several sites in `sqlite.py`, because `documents_with_mention` floors
the same two bounds, so a verdict would have described a partial mutation; and
two replacements *contained* their own anchor, which the "original text still
present" check caught. All four were narrowed and re-run.

**Two guards passed for the wrong reason and were only caught by mutation**,
which is the reason the table exists:

- The **tiebreak** test stored its two tied passages in positional order, so
  removing `, char_start, id` left SQLite falling back to rowid order — which
  for that fixture *is* positional order. Storing the later passage first makes
  the two disagree, and the mutation then reddens.
- The **no-prose** guard probed with whole sentences, so a clipped opening of
  each passage — the exact defect it is named for — passed whenever the clip was
  shorter than the probe. The row's key set is now pinned exactly and each
  passage's own opening is probed from the chunker's oracle.

**Review.** Two reviewers on `9f85d9f`, correctness and security. **No
blocker.** Four SHOULDs, all fixed here: three fields returned by the new query
and compared against nothing (`characters`, `heading_path`, the ordering's
tiebreak), the no-prose guard's blind spot, the unticked task list, and the
stale suite figure. Three NOTEs recorded rather than fixed — the delta now
states that an entry may carry the heading path, and the two
`docs/implementation-notes.md` entries below. The security review found no
blocker and no SHOULD: compartment integrity clean (a cross-casefile reference
and a never-existed one produce byte-identical refusals, so there is no
existence oracle), no SQL built from a non-bind value, the read-only stamp
truthful over the whole reachable path, and the prose-free promise kept by every
field the payload emits.

**Recorded, not fixed** — both in `docs/implementation-notes.md`, both
pre-existing classes this change widens:

- `one_line` strips whitespace only, so control characters and bidi overrides
  reach the analyst's terminal. This change adds a fourth sink — a row-level
  `heading_path` and the echoed `document` block — and the note's enumeration
  was updated to match. The review also established two limits worth keeping: a
  heading path cannot forge a *row*, because the chunker builds it from stripped
  `splitlines` output, and `search_payload` passes `heading_path` to
  `provenance()` **uncollapsed**, so the pre-existing search path is looser with
  the same value than either listing is.
- `content_notice` rides on payloads that contain no fence while its wording
  names one. Third instance of a pattern `case_mentions` and
  `case_mention_documents` established; the fix is a second constant for
  prose-free payloads, which is a change to a published untrusted-content claim.
