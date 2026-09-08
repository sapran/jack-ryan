## 1. The rule in the published specs

- [ ] 1.1 Read every published requirement in `mentions`, `hybrid-search`,
      `mcp-tool-surface`, `mcp-surface-profiles`, `analyst-pack`, `storage-seam`
      and `service-adapter-boundary`; verify none asserts a tool count,
      enumerates the tool set, or states anything this change falsifies, so both
      deltas are ADDED and no MODIFIED is owed.
- [ ] 1.2 Verify `mcp-tool-surface`'s bounded-reads and index-and-bodies
      requirements already bind the new tool, so no scenario is owed there.
- [ ] 1.3 `openspec validate follow-an-identifier-exhaustively --strict` before
      any code is written.

## 2. One definition of the identifier predicate

- [ ] 2.1 Extract `mention_predicate(alias, casefile_id, mention_kind,
      mention_value)` in `storage/retrieval.py`, public and documented as shared.
- [ ] 2.2 Rewrite `_mention_filter`'s body over it, keeping its empty-value guard
      and its whole docstring; verify the assembled SQL string and parameter
      order are byte-identical to what the two retriever legs bind today.
      *Mutation 10: drop the `AND kind = ?` branch — reddens the new kinded test
      and the existing `test_a_kinded_mention_filter_matches_only_that_kind`.*

## 3. Two domain objects and one port method

- [ ] 3.1 `MentionCarrier` (document, mentions, chunk_id) and
      `MentionDocumentPage` (carriers, total_matching, offset, limit, kind,
      value, `truncated`, `continue_from`) in `storage/port.py`, frozen.
- [ ] 3.2 Declare `documents_with_mention` on `StorePort`, stating that the count
      must be computed under the same predicate as the page and that no
      unbounded form is offered.

## 4. The query

- [ ] 4.1 `documents_with_mention` in `storage/sqlite.py` beside
      `list_document_page`: count and page under one predicate and binds,
      narrow-then-widen join, repeated outer `ORDER BY`, floored offset.
      *Mutation 1: count drops `AND m.normalised = ?` — the sweep's bounded loop
      raises and the inventory disagrees. Mutation 3: inner `ORDER BY` removed —
      the sweep repeats or omits. Mutation 4: `LIMIT/OFFSET` moved outward — page
      contents wrong.*
- [ ] 4.2 Count occurrences as `COUNT(DISTINCT m.document_offset)`.
      *Mutation 2: `COUNT(*)` — reddens the overlap test and the
      inventory-agreement test.*
- [ ] 4.3 `_first_passages`: one statement for the page, earliest position then
      lowest chunk ordinal, called inside the caller's lock.
      *Mutation 5: drop the `document_id IN (...)` bound — a row's `chunk_id`
      addresses another document. Mutation 6: order by `document_offset DESC` —
      the citation journey's chunk id changes.*
- [ ] 4.4 Verify no schema step is needed: both mention indexes serve the seek,
      `SCHEMA_VERSION` stays 8.

## 5. The service method

- [ ] 5.1 `DEFAULT_CARRIER_PAGE = 50`, `MAX_CARRIER_PAGE = 200`, and
      `MAX_DOCUMENT_OFFSET` imported from `.ingestion` rather than re-spelled.
- [ ] 5.2 `SearchService.mention_documents`: resolve the casefile, parse through
      `_parsed_mention`, refuse an empty value, clamp both bounds.
      *Mutation 7: pass `mention` through unparsed. Mutation 8: drop the empty
      guard. Mutation 9: drop the limit clamp.*

## 6. The agent surface

- [ ] 6.1 `case_mention_documents` in `interfaces/mcp/server.py`, after
      `case_search`, `@returns_error_payload` below `@server.tool`, service call
      positional.
- [ ] 6.2 `_no_carriers`: a message true of the page that produced it.
      *Mutation 15: one message for both branches.*
- [ ] 6.3 Payload echoes `mention`, `kind`, `value`, `offset`, `total_matching`,
      `truncated`, `continue_from`, `content_notice`.
      *Mutation 11: rename `total_matching`. Mutation 12: omit `chunk_id`.*
- [ ] 6.4 Renumber `INSTRUCTIONS` with the new step 6; `case_get_passage` 6→7,
      `case_read_document` 7→8, `case_cite` 8→9.
- [ ] 6.5 One sentence in `case_search`'s description: its `total` counts
      returned passages, and the new tool reaches every carrier.
      *Mutation 14: remove it.*
- [ ] 6.6 Register in `annotations.py`, `profiles.py` (`READONLY_TOOLS`),
      `analyst/role.md` step 5, and the `expected` map in
      `tests/test_mcp_surface.py`.
      *Mutation 13: omit from `READONLY_TOOLS`.*

## 7. REST and CLI

- [ ] 7.1 `GET /api/casefiles/{reference}/mentions/documents` in `server.py`,
      `mention` a required query parameter, keywords through
      `run_in_threadpool`.
- [ ] 7.2 `jackryan mention-documents` in `cli.py`, a top-level command, printing
      the envelope under `--json` and the continue hint when truncated.

## 8. Parked notes

- [ ] 8.1 Append to the write-only-mentions note: the aggregate read now exists
      with a production caller; the per-row read still has none.
- [ ] 8.2 Park the stale port-method count in `services/windowing.py:207-210` —
      already stale before this change, not corrected because the file is
      untouched here.

## 9. Tests

- [ ] 9.1 `tests/test_mention_documents.py` with the `carriers` fixture asserting
      its own premises: 60 shuffled carrier files, a heavy carrier, an
      overlap-boundary occurrence, two near-misses, a differently-spelled
      carrier, and one identifier-free document.
- [ ] 9.2 The bounded sweep, the inventory-agreement oracle against literals, the
      overlap count, the heaviest-first order, the near-miss exclusion,
      normalisation, kinded matching, the two refusals, the empty page, casefile
      confinement, both clamps, and the store's reported offset.
- [ ] 9.3 The three async MCP tests, including the citation journey with
      `case_search` removed from the server. No `TestClient` in this module.
- [ ] 9.4 Four cross-surface tests in `tests/test_result_shape.py`, with exact
      key sets for the row and the payload.
- [ ] 9.5 All 15 mutations red against a green control, sources restored and
      re-checksummed.

## 10. Gates and landing

- [ ] 10.1 `uv run pytest -q`, `openspec validate --all --strict`,
      `gitleaks detect --no-banner`; baseline is 759 passed / 3 skipped at
      `25eb9b8`.
- [ ] 10.2 End-to-end over the shipped stdio transport in a disposable data
      directory, plus REST parity; the real corpus is read-only.
- [ ] 10.3 Grep the diff for `sk-`, `hf_`, `AKIA`, `ghp_`, `-----BEGIN`,
      `.ts.net`, `/Users/`, `/home/`.
- [ ] 10.4 `openspec sync-specs`, `openspec archive`, review the diff with two
      reviewers, merge, remove the worktree.
