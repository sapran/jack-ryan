## 1. The rule in the published specs

- [ ] 1.1 CREATE the `mentions` capability with a `Purpose` block and four requirements — the registry as the NER seam, precision as the acceptance bar, mentions rebuilt with their chunks, and the counted inventory; verify the `Purpose` is in the delta, which is only permitted because the capability is new
- [ ] 1.2 ADD to `hybrid-search` the mention-filter requirement; verify it states that the filter is applied by the retrievers rather than to their results, that it adds no rank leg and no score, and that it is therefore transparent to reranking
- [ ] 1.3 ADD to `storage-seam` the requirement that anything derived from a chunk is written in the chunk's own transaction; verify it argues from chunk ids being minted afresh rather than from tidiness, and that it forbids a separate method rather than merely discouraging one
- [ ] 1.4 MODIFY `mcp-tool-surface`'s *A result separates its index from its bodies and carries chaining identifiers*, reproducing all five published scenarios verbatim; verify the `chunk_id`/`document_id` sentence is scoped to entries that address a passage, since a facet entry addresses none — and that the new scenario says an inventory entry carries what turns it into a search
- [ ] 1.5 Establish by falsification, not by the plan's list, that `mcp-surface-profiles` needs no delta; verify its requirements name no tool and are satisfied rather than falsified by adding one, and that `analyst-pack` likewise requires the role to name its tools without enumerating them. Record the divergence from the plan in `proposal.md` § Impact rather than silently omitting it
- [ ] 1.6 Confirm `schema-migration` needs no delta; verify creating a table and an index is already permitted verbatim and that the step is non-destructive

## 2. The extractor registry

- [ ] 2.1 Create `src/jackryan/mentions/port.py` with `MentionExtractor` as a `typing.Protocol` carrying `kind`, `name` and `find`, and `Found` as a frozen dataclass of `value`, `normalised`, `char_start`, `char_end`; verify offsets are documented as relative to the chunk and why
- [ ] 2.2 Create `src/jackryan/mentions/patterns.py` with the four extractors; verify each declares its own `kind` and `name` and none imports another
- [ ] 2.3 Implement the IBAN mod-97 check rather than a shape match; verify a transposed digit is rejected and that the test proves it with a real IBAN and its corrupted twin
- [ ] 2.4 Anchor `registration_number` to a preceding `ЄДРПОУ`/`ЕДРПОУ`/`ИНН`/`ІПН`/`EDRPOU` within 40 characters; verify a bare run of digits of the right length does not fire, since that is the case that makes the facet useless
- [ ] 2.5 Normalise each kind as the design table states; verify the value as it appeared is kept beside the normalised form, so a quotation still shows what the document said
- [ ] 2.6 Create `src/jackryan/mentions/__init__.py` with `default_extractors()` returning the four; verify selection lives in the registry so that adding an extractor is registering one

## 3. Storage

- [ ] 3.1 Add `Mention` to `storage/port.py` as a frozen dataclass mirroring the columns; verify it carries chunk, document and casefile ids so a mention can be counted per document without a join back to chunks
- [ ] 3.2 Append the migration step to `_STEPS` creating the `mentions` table and the three indexes; verify `to_version=7` — change 1 took 6, and two changes claiming one version produce a store neither ladder can carry forward
- [ ] 3.3 Leave `_SCHEMA` untouched; verify the reason recorded under change 1's task 4.4 still holds — the baseline is frozen at 4 and `initialize` runs it and then the whole ladder, so a table in both places raises on every fresh store
- [ ] 3.4 Confirm the cascade works without touching `_SIDECAR_TRIGGER`; verify `chunks.id` is a legal foreign-key parent, that `PRAGMA foreign_keys=ON` is set, and that the trigger exists only for the two virtual tables which never observe a cascade
- [ ] 3.5 Add `mentions` as a parameter of `StorePort.replace_chunks` and the `SqliteStore` implementation, writing them inside the existing transaction; verify no separate write path exists and that every test double is updated in the same pass
- [ ] 3.6 Add `MentionFacet` and `StorePort.mention_facets`, implemented as one `GROUP BY` with `COUNT(*)` and `COUNT(DISTINCT document_id)`; verify the service layer holds no SQL, which `storage-seam` requires

## 4. Extraction at ingest

- [ ] 4.1 Run extraction in `_prepare_chunks` over the built chunks, before anything is written; verify it joins the existing write-free sequence rather than adding a second write, which is the invariant change 1's review round established
- [ ] 4.2 Pass the mentions into `replace_chunks` alongside the chunks and embeddings; verify a document that fails leaves no mention, by the same transaction that leaves no chunk
- [ ] 4.3 Gate extraction on nothing; verify no profile setting is added and the design records why a switch would let a noisy extractor survive rather than be fixed

## 5. The pivot

- [ ] 5.1 Thread `mention: str = ""` through `SqliteStore.search_keyword` and `search_vector` as a predicate **inside** the SQL; verify the vector leg's predicate sits beside the casefile constraint it copies the argument from
- [ ] 5.2 Thread it through `StorePort.search_keyword` and `search_vector`; verify both signatures match the adapter
- [ ] 5.3 Thread it through `SearchService.search` after `limit`; verify an unknown kind raises `ValidationError` naming the four kinds rather than returning an empty list
- [ ] 5.4 Parse `<kind>:<value>` and a bare `<value>`; verify matching is on the normalised form, so a pivot finds an identifier written another way
- [ ] 5.5 Thread it through `case_search`, being careful that `anyio.to_thread.run_sync` takes positional arguments only; verify the parameter is passed positionally or through `functools.partial`, and that REST's `run_in_threadpool` is unaffected because it forwards keywords
- [ ] 5.6 Add `mention=` to the REST search route and `--mention` to the CLI search command; verify the CLI dispatch passes it through

## 6. The facet

- [ ] 6.1 Add `SearchService.mention_facets(casefile_reference, kind="", limit=50)` resolving the casefile first; verify the unknown-kind refusal is the same one the search filter gives
- [ ] 6.2 Add the `case_mentions` MCP tool; verify it returns `listing_payload` and that the design records the condition under which that is correct — bare identifiers and counts only, no surrounding snippet
- [ ] 6.3 Register the tool in `ANNOTATIONS` as read-only, non-destructive, closed-world; verify omitting it would fail the build through `UnstampedToolError` rather than advertising it unstamped
- [ ] 6.4 Register it in `READONLY_TOOLS`; verify `ANALYST_TOOLS` and `ADMIN_TOOLS` are aliases so one edit covers all three profiles, and that `test_only_the_profiles_tools_are_advertised` asserts exact set equality
- [ ] 6.5 Add the tool to `INSTRUCTIONS`; verify `test_the_surface_teaches_the_method` sees it, since this is one of the three registration points that drift silently
- [ ] 6.6 Add it to `analyst/role.md` step 4, which is already *Pivot — follow names, dates, and identifiers you find into new searches*; verify the analyst-pack test uses containment, so omitting this drifts silently and it must be added deliberately
- [ ] 6.7 Add `jackryan mentions <casefile> [--kind K] [--limit N]` to the CLI and `GET /api/casefiles/{reference}/mentions` to REST; verify all three surfaces answer the same question

## 7. Verification

- [ ] 7.1 **The filter is applied by the retrievers, not to their results.** Build a casefile where a chunk carrying the target mention ranks below `depth` for the query unfiltered, then search with the filter and assert it is returned; watch it fail with the predicate moved outside the SQL. This is the test that would have caught the whole class of defect, so it must be seen failing
- [ ] 7.2 **Mentions are rebuilt on reingest.** Ingest, record the mention rows, reingest the same file, and assert every `chunk_id` still resolves to a live chunk and the counts match; verify this is the assertion that catches a mentions write left outside `replace_chunks`, since chunk ids are minted fresh
- [ ] 7.3 **A failed chunk write leaves no mention**, extending the existing rollback test; verify it asserts against the store rather than reading the report
- [ ] 7.4 **Deleting a casefile leaves no mention**, so the cascade is proved rather than assumed
- [ ] 7.5 **IBAN mod-97 rejects a bad checksum**, and `registration_number` does not fire on a bare run of digits; verify both use a real example and its corrupted twin rather than a synthetic string
- [ ] 7.6 **An unknown `--mention` kind is a `ValidationError`** naming the four kinds, on both the search filter and the facet; verify it is not an empty result
- [ ] 7.7 **The filter changes candidacy and not ranking.** Run one query filtered and unfiltered and assert the passages present in both keep their relative order and their scores; verify this pins that no rank leg or score bonus was added
- [ ] 7.8 **Cross-surface parity** in `tests/test_result_shape.py` for the mention filter and the facet call; verify it follows that module's existing pattern of driving MCP through `anyio.run` from a synchronous test, which is deliberate because a FastAPI TestClient and an MCP server in one module abort the interpreter at teardown on macOS
- [ ] 7.9 **The new tool is stamped, gated and taught**; verify the three existing surface tests cover it once `ANNOTATIONS` and `READONLY_TOOLS` are edited, and confirm `test_the_surface_teaches_the_method` sees it in `INSTRUCTIONS`
- [ ] 7.10 Run the full suite; verify it is green and report the count against the 516 this change starts from
- [ ] 7.11 Run `scripts/evaluate_retrieval.py`; verify the figures have not moved, since the change adds no rank leg and no filter is applied by default — a moved figure means something was filtered that should not have been
- [ ] 7.12 Run `openspec validate --all --strict` and re-run the mechanical title audit; verify validate passing is not treated as proof the delta applies
- [ ] 7.13 Verify every new assertion by breaking what it defends and watching it fail, against a throwaway copy of `src` rather than the worktree; verify the copy is byte-identical to the worktree's `src` afterwards

## 8. Prose

- [ ] 8.1 Record in `docs/handover.md` what mentions ship, and state plainly that a casefile ingested before this change has no mentions until it is reingested — so an empty facet over an old casefile is indistinguishable from a corpus that contains none; verify the M3 table row is struck through as the others are
- [ ] 8.2 Add the `CLAUDE.md` pitfall that a search filter belongs inside the retrievers' SQL, with the depth argument; verify it names the failure — an empty result that reads as "this casefile does not mention that"
- [ ] 8.3 Correct `docs/design.md` § 5's facet list, which says the mention facet arrives with the feature that populates it; verify the mention facet is now struck through and the tag and actor facets are left as they are
