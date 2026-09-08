## 1. The rule in the published specs

- [ ] 1.1 MODIFY `document-hierarchy`'s *Listing returns what was ingested, and reaches expansions on request*, reproducing its three published paragraphs and all four published scenarios verbatim and adding the container selection; verify the four surviving scenario titles are reproduced by parsing both files rather than by reading them, since a by-title omission is a validation ERROR that blocks archive.
- [ ] 1.2 MODIFY `mcp-tool-surface`'s *Reads are bounded, and truncation is explicit*, reproducing its five published paragraphs and all four published scenarios verbatim and extending the bound to a listing; verify the two counts are required to be separately named and the ordering required to be total, since those are the two claims the SQL has to satisfy.
- [ ] 1.3 Establish by falsification that `storage-seam`, `service-adapter-boundary`, `mcp-surface-profiles`, `untrusted-content-boundary`, `extraction-quality-gate`, `casefile-lifecycle` and `analyst-pack` need no delta; verify by reading what each scenario actually asks rather than by whether the change feels in scope, and record the argument in the proposal's Impact.
- [ ] 1.4 Run `openspec validate expose-container-contents --strict`; verify it is clean before any code is written, since this is the one gate that runs before implementation.

## 2. The value a paged listing returns

- [ ] 2.1 Add `DocumentPage` to `storage/port.py` beside `CasefileStatistics` as a frozen dataclass carrying the documents, `total_matching`, `offset`, `limit`, `selection` and an optional `parent`; verify the field names say what they are, so a count cannot be read as the other count.
- [ ] 2.2 Make `truncated` and `continue_from` derived properties rather than fields; verify they cannot disagree with the documents actually carried, which is the reason `SearchHit.is_widened` and `Document.is_expanded` are properties too.
- [ ] 2.3 Use `truncated` and `continue_from` verbatim from `case_read_document`'s existing continuation contract rather than a new `has_more`/`next_cursor` pair; verify the two spellings match, so an agent meets one contract.

## 3. The port and the store

- [ ] 3.1 Declare `list_document_page` on `StorePort` beside `list_documents`, documenting that `parent_id` takes precedence over `include_expanded` and that the count SHALL be computed under the same predicate as the page; verify the docstring states why, since nothing downstream detects a mismatched total.
- [ ] 3.2 Remove `list_children` from `StorePort` and `SqliteStore`; verify its capability is wholly covered by `list_document_page(..., parent_id=...)`, which additionally scopes to the casefile and marks nesting — neither of which it did.
- [ ] 3.3 Add `_document_selection`, returning the predicate, the ordering and the selection name together; verify the page and the count cannot be built from different predicates, because one call site produces both.
- [ ] 3.4 Order the intake and `all` selections newest-first and a container's contents by containment path; verify each ordering ends in `d.id` so it is total, and record why an identifier is admissible here where the fused ranking forbids one.
- [ ] 3.5 Implement `list_document_page` as a count plus a narrow id subquery joined back for the rows; verify `extracted_text` never enters the sorter, which is the cost the page exists to avoid.
- [ ] 3.6 Repeat the `ORDER BY` on the outer query; verify by deleting it that the join does not preserve the subquery's order, which is the defect that makes consecutive pages overlap.
- [ ] 3.7 Alias `child_count` for every selection; verify a nested container inside a container's contents reports a non-zero count, which is the assertion `list_children` could not pass.
- [ ] 3.8 Reduce `list_documents` to a delegate with its signature unchanged; verify it and the paged method cannot come to disagree about what a casefile's documents are, and that its docstring names the paged method as what an adapter must call.

## 4. The service

- [ ] 4.1 Add `DEFAULT_DOCUMENT_PAGE = 50` and `MAX_DOCUMENT_PAGE = 200` beside `MAX_FILE_BYTES`; verify both adapters import them rather than restating a bound, and that no second tighter adapter bound is added, since a listing row carries metadata rather than prose.
- [ ] 4.2 Add `IngestionService.list_document_page`, clamping the limit and flooring the offset; verify it clamps rather than refuses, as every other bound on this surface does.
- [ ] 4.3 Resolve `parent_reference` through `resolve_document` only when it is non-empty; verify an omitted parent is treated as the default rather than as the mistake `resolve_document` refuses.
- [ ] 4.4 Set `parent` on the returned page in the service; verify the casefile scoping lives here and nowhere else, and that a parent in another casefile raises `NotFoundError` before any child is queried.
- [ ] 4.5 Remove `IngestionService.list_children`; verify the six call sites are migrated rather than left with a shim.

## 5. The agent surface

- [ ] 5.1 Give `case_list_documents` `parent`, `expanded`, `offset` and `limit`, forwarding them positionally; verify the call is positional because `anyio.to_thread.run_sync` forwards no keywords, which fails at the first paged call rather than at import.
- [ ] 5.2 Rewrite the tool's description to teach that a `children` count is a container to enter and how to follow `continue_from`; verify it names `parent`, `total_matching`, `truncated` and `continue_from`, since an agent learns the payload from the description.
- [ ] 5.3 Add `offset`, `total_matching`, `truncated`, `continue_from` and `selection` to the payload, leaving `total` meaning the entries in this payload; verify `total` is not redefined, since `listing_payload` computes it for every list-shaped tool.
- [ ] 5.4 Echo the resolved container under `parent` when one was asked for; verify an agent that passed an 8-character prefix can see which container it entered and cite it.
- [ ] 5.5 Add `_nothing_listed`, giving an empty page a message true of that page; verify an empty container does not read as an empty casefile, which is the same false negative as an empty result standing in for an unknown facet kind.
- [ ] 5.6 Leave the per-row shape unchanged; verify a listing still carries no `summary`, `summary_by` or `fence_nonce`, and that `formatted` still holds exactly one line per row.
- [ ] 5.7 Teach the tool in `INSTRUCTIONS` as step 3 and renumber the rest; verify the instructions still name `case_list_casefiles`, `case_search`, `case_cite` and `coverage` and still say content is not instructions.

## 6. REST

- [ ] 6.1 Give the documents route `parent`, `expanded`, `offset` and `limit`, spelled identically to the agent surface; verify every shared field name matches, since two spellings of one field is two contracts.
- [ ] 6.2 Move the route onto `run_in_threadpool` with keyword arguments; verify keywords are safe here where they are a `TypeError` on the agent surface, and that the route no longer reads rows on the event loop.
- [ ] 6.3 Leave `total`, `documents` and `serialize_document` unchanged; verify the nine shared fields and exactly four REST extras still hold, and that an existing caller's request is still valid.

## 7. The shipped analyst role

- [ ] 7.1 Add container navigation to `analyst/role.md` as step 3 under Method and renumber the rest; verify the pack still names its tools and carries no vendor-specific text, and that a capability the role does not name is one the agent will not use.

## 8. Tests

- [ ] 8.1 Migrate the six `list_children` call sites in `test_containers.py`, `test_content_routing.py` and `test_rar_containers.py`; verify each assertion is unchanged, so the migration proves the new method covers the old one.
- [ ] 8.2 Add the four new parameters to the advertised-parameter table; verify the table fails naming the tool if they are missing, rather than failing somewhere else.
- [ ] 8.3 Page a five-entry archive at `limit=2` over three offsets; verify the concatenated ids equal the entries exactly, against an oracle the test builds itself rather than a second call to the code under test.
- [ ] 8.4 Assert `total_matching`, `truncated` and `continue_from` on every page; verify a page past the end returns nothing while still reporting the selection's size, so it does not read as an empty container.
- [ ] 8.5 Assert an over-large limit is clamped to `MAX_DOCUMENT_PAGE`; verify it clamps rather than raising.
- [ ] 8.6 Assert a nested container appears among the children with a non-zero child count and can itself be paged; verify this is the assertion the removed `list_children` could not pass.
- [ ] 8.7 Assert a parent in another casefile raises `NotFoundError`; verify nothing about its contents is returned.
- [ ] 8.8 Mutation-prove the outer `ORDER BY` and the count predicate; verify the named test reddens for each and is restored, since a guard whose failure was not watched certifies nothing.
- [ ] 8.9 Drive the agent journey through the tool surface — intake, then `parent` by 8-character prefix, then three pages, then read and cite a child; verify the citation names the containment path and no search ran.
- [ ] 8.10 Assert REST and the agent surface agree field by field on the same arguments; verify the default REST call still lists intake only.
- [ ] 8.11 Run `pytest -q` and `gitleaks detect`; verify the suite rises by exactly the new tests and no test is lost.
- [ ] 8.12 Page the real corpus read-only; verify `total_matching` matches the casefile's reported ingested count and that a container can be entered, ingesting nothing.
