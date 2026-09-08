## 1. The rule in the published specs

- [x] 1.1 Read every published requirement in `mentions`, `hybrid-search`,
      `mcp-tool-surface`, `mcp-surface-profiles`, `analyst-pack`, `storage-seam`
      and `service-adapter-boundary`; verify none asserts a tool count,
      enumerates the tool set, or states anything this change falsifies, so both
      deltas are ADDED and no MODIFIED is owed.
- [x] 1.2 Verify `mcp-tool-surface`'s bounded-reads and index-and-bodies
      requirements already bind the new tool, so no scenario is owed there.
- [x] 1.3 `openspec validate follow-an-identifier-exhaustively --strict` before
      any code is written.

## 2. One definition of the identifier predicate

- [x] 2.1 Extract `mention_predicate(alias, casefile_id, mention_kind,
      mention_value)` in `storage/retrieval.py`, public and documented as shared.
- [x] 2.2 Rewrite `_mention_filter`'s body over it, keeping its empty-value guard
      and its whole docstring; verify the assembled SQL string and parameter
      order are byte-identical to what the two retriever legs bind today.
      *Mutation 10: drop the `AND kind = ?` branch — reddens the new kinded test
      and the existing `test_a_kinded_mention_filter_matches_only_that_kind`.*

## 3. Two domain objects and one port method

- [x] 3.1 `MentionCarrier` (document, mentions, chunk_id) and
      `MentionDocumentPage` (carriers, total_matching, offset, limit, kind,
      value, `truncated`, `continue_from`) in `storage/port.py`, frozen.
- [x] 3.2 Declare `documents_with_mention` on `StorePort`, stating that the count
      must be computed under the same predicate as the page and that no
      unbounded form is offered.

## 4. The query

- [x] 4.1 `documents_with_mention` in `storage/sqlite.py` beside
      `list_document_page`: count and page under one predicate and binds,
      narrow-then-widen join, repeated outer `ORDER BY`, floored offset.
      *Mutation 1: count drops `AND m.normalised = ?` — the sweep's bounded loop
      raises and the inventory disagrees. Mutation 3: inner `ORDER BY` removed —
      the sweep repeats or omits. Mutation 4: `LIMIT/OFFSET` moved outward — page
      contents wrong.*
- [x] 4.2 Count occurrences as `COUNT(DISTINCT m.document_offset)`.
      *Mutation 2: `COUNT(*)` — reddens the overlap test and the
      inventory-agreement test.*
- [x] 4.3 `_first_passages`: one statement for the page, earliest position then
      lowest chunk ordinal, called inside the caller's lock.
      *Mutation 5: drop the `document_id IN (...)` bound — a row's `chunk_id`
      addresses another document. Mutation 6: order by `document_offset DESC` —
      the citation journey's chunk id changes.*
- [x] 4.4 Verify no schema step is needed: both mention indexes serve the seek,
      `SCHEMA_VERSION` stays 8.

## 5. The service method

- [x] 5.1 `DEFAULT_CARRIER_PAGE = 50`, `MAX_CARRIER_PAGE = 200`, and
      `MAX_DOCUMENT_OFFSET` imported from `.ingestion` rather than re-spelled.
- [x] 5.2 `SearchService.mention_documents`: resolve the casefile, parse through
      `_parsed_mention`, refuse an empty value, clamp both bounds.
      *Mutation 7: pass `mention` through unparsed. Mutation 8: drop the empty
      guard. Mutation 9: drop the limit clamp.*

## 6. The agent surface

- [x] 6.1 `case_mention_documents` in `interfaces/mcp/server.py`, after
      `case_search`, `@returns_error_payload` below `@server.tool`, service call
      positional.
- [x] 6.2 `_no_carriers`: a message true of the page that produced it.
      *Mutation 15: one message for both branches.*
- [x] 6.3 Payload echoes `mention`, `kind`, `value`, `offset`, `total_matching`,
      `truncated`, `continue_from`, `content_notice`.
      *Mutation 11: rename `total_matching`. Mutation 12: omit `chunk_id`.*
- [x] 6.4 Renumber `INSTRUCTIONS` with the new step 6; `case_get_passage` 6→7,
      `case_read_document` 7→8, `case_cite` 8→9.
- [x] 6.5 One sentence in `case_search`'s description: its `total` counts
      returned passages, and the new tool reaches every carrier.
      *Mutation 14: remove it.*
- [x] 6.6 Register in `annotations.py`, `profiles.py` (`READONLY_TOOLS`),
      `analyst/role.md` step 5, and the `expected` map in
      `tests/test_mcp_surface.py`.
      *Mutation 13: omit from `READONLY_TOOLS`.*

## 7. REST and CLI

- [x] 7.1 `GET /api/casefiles/{reference}/mentions/documents` in `server.py`,
      `mention` a required query parameter, keywords through
      `run_in_threadpool`.
- [x] 7.2 `jackryan mention-documents` in `cli.py`, a top-level command, printing
      the envelope under `--json` and the continue hint when truncated.

## 8. Parked notes

- [x] 8.1 Append to the write-only-mentions note: the aggregate read now exists
      with a production caller; the per-row read still has none.
- [x] 8.2 Park the stale port-method count in `services/windowing.py:207-210` —
      already stale before this change, not corrected because the file is
      untouched here.

## 9. Tests

- [x] 9.1 `tests/test_mention_documents.py` with the `carriers` fixture asserting
      its own premises: 60 shuffled carrier files, a heavy carrier, an
      overlap-boundary occurrence, two near-misses, a differently-spelled
      carrier, and one identifier-free document.
- [x] 9.2 The bounded sweep, the inventory-agreement oracle against literals, the
      overlap count, the heaviest-first order, the near-miss exclusion,
      normalisation, kinded matching, the two refusals, the empty page, casefile
      confinement, both clamps, and the store's reported offset.
- [x] 9.3 The three async MCP tests, including the citation journey with
      `case_search` removed from the server. No `TestClient` in this module.
- [x] 9.4 Four cross-surface tests in `tests/test_result_shape.py`, with exact
      key sets for the row and the payload.
- [x] 9.5 All mutations red against a green control. *Ran as 22 rather than the
      15 planned: review added guards for the casefile joins, the store's limit
      floor, the page's own past-the-end predicate, the CLI branch and the alias
      check, and round one found the earliest-occurrence rule unguarded — which
      is what the second commit adds. 22/22 red, each naming its own symptom. A
      23rd is GREEN by design and was measured rather than assumed: the passage
      pick's casefile guard is unreachable behind the page query's, so it is a
      proven redundancy, not a gap. Sources were restored with `git checkout`
      and the tree asserted clean after every mutation, which is a stronger
      oracle than the checksum this line originally planned — it compares
      against the committed bytes rather than against a number the harness
      computed itself.*

## 10. Gates and landing

- [x] 10.1 `uv run pytest -q`, `openspec validate --all --strict`,
      `gitleaks detect --no-banner`; baseline is 759 passed / 3 skipped at
      `25eb9b8`.
- [x] 10.2 End-to-end over the shipped stdio transport in a disposable data
      directory, plus REST parity; the real corpus is read-only.
- [x] 10.3 Grep the diff for `sk-`, `hf_`, `AKIA`, `ghp_`, `-----BEGIN`,
      `.ts.net`, `/Users/`, `/home/`.
- [x] 10.4 `openspec archive` — there is no `sync-specs` subcommand in OpenSpec
      1.12.0; `archive` updates the main specs itself. Review the diff with two
      reviewers, merge, remove the worktree. *Reviewed by `reviewer` and
      `security-reviewer`; seven in-scope defects fixed, two parked. Merged as
      `7644809` via PR #35 after all three CI gates passed.*
