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
