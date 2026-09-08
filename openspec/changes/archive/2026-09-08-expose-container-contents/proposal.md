## Why

Jack Ryan expands archives, mailboxes and messages into child documents, records
the parent link, and marks a container in a listing with how many children it
has. `document-hierarchy` requires exactly that, and it works.

What no caller can do is act on the marking. The agent surface's
`case_list_documents(casefile)` takes one parameter and calls the service with
its defaults, and the REST route takes no query parameters at all.
`IngestionService.list_children` — the service method that answers "what came out
of this document" — has no adapter caller anywhere in the repository. So an agent
reads `children: 3` on an archive and has no tool that can name those three. The
evidence inside a container is reachable only if a search happens to surface it,
which is the one thing a container makes unlikely: an attachment's text is short,
its filename is generic, and it competes against the whole corpus.

That is the capability gap. There is a second defect beside it, in the code that
would serve it.

**`list_children` cannot mark a nested container.** `_row_to_document` reads
`child_count` only when the query aliases it, and defaults it to 0 otherwise.
`list_children` selects `*` and aliases nothing, so every child it returns
reports zero children whatever it holds. An archive inside an archive is
therefore invisible as a container, and a caller given those rows cannot tell
there is another level to enter. The method that exists to walk the hierarchy is
the one method that cannot walk past one level.

**Every listing is unbounded.** There is no `LIMIT` or `OFFSET` in any
document-listing SQL in the repository, at any layer. `list_documents` selects
`d.*`, which includes `extracted_text`, so one call materialises every matching
document's full text. On the intake selection that is survivable — a casefile
holds few directly ingested files. Applied to a container's contents, or to
`include_expanded`, it is the whole corpus in memory for one listing, and the
casefiles this tool is built for are the ones where that is 40,000 documents.
`mcp-tool-surface` already requires a read to be bounded and to declare its
truncation; a listing is a read, and was never held to it.

## What Changes

**Current behaviour.** Three listing entry points, none bounded, none able to
select a container's contents. A store method that can select children but
returns them mismarked and unscoped to a casefile. A service method with no
caller.

**Desired behaviour.** One bounded, paged, deterministically ordered document
listing, reachable identically from the agent surface and REST, which can select
the casefile's intake, everything in the casefile, or one container's direct
children.

- **`DocumentPage`** — a frozen dataclass carrying the documents, how many the
  selection holds, the offset and limit, which selection was listed, and the
  resolved container where one was asked for. `truncated` and `continue_from` are
  derived properties, in the same vocabulary `case_read_document` already uses for
  a truncated read, so an agent meets one continuation contract rather than two.
- **`StorePort.list_document_page`** replaces `list_children`. It scopes to the
  casefile, aliases `child_count` for every selection — which fixes the nesting
  defect — and computes its count under the same predicate as its page.
- **One predicate, one ordering, decided once** in `_document_selection`, because
  a total counted under a different predicate than the rows is a number a caller
  cannot act on and nothing downstream detects. Every ordering ends in a unique
  column, so a page boundary cannot fall inside a tie and repeat or skip a
  document.
- **`IngestionService.list_document_page`** owns the bound, the reference
  resolution and the casefile scoping. A parent in another casefile raises
  `NotFoundError` and its children are never queried.
- **The agent surface gains `parent`, `expanded`, `offset` and `limit`**, and its
  description teaches that a `children` count is a container to enter. The
  instructions gain it as a step of the method, and so does the shipped analyst
  role — a capability nothing tells an agent about is a capability it does not
  use.
- **REST gains the same four parameters**, spelled identically.

**A contract change, stated rather than hidden.** An existing REST caller's
request stays valid and now returns a bounded first page that says so, carrying
`total_matching`, `truncated` and `continue_from`. That is the intended change,
and the `mcp-tool-surface` delta states it.

**`total` keeps its published meaning** — the entries in this payload — because
that is what `listing_payload` computes for every list-shaped tool and what
`case_search` reports. The whole-selection figure is a new key beside it, not a
redefinition of an old one.

**Deliberately not in scope.** The CLI's `jackryan document list` is unchanged:
it already reaches expansions through `--expanded`, and paging it would turn its
`--json` output from a bare array into an object for no acceptance criterion
here. `ancestors` and `descendant_ids` are untouched. No index is added — see
Impact.

## Impact

- Affected specs:
  - `document-hierarchy` (MODIFIED — *Listing returns what was ingested, and
    reaches expansions on request*, reproducing its three paragraphs and all
    four published scenarios verbatim, and adding a third selection: one
    document's direct contents, confined to its casefile, marked for nesting)
  - `mcp-tool-surface` (MODIFIED — *Reads are bounded, and truncation is
    explicit*, reproducing its five paragraphs and all four published scenarios
    verbatim, and extending the bound from a read of text to a listing of
    entries, with the two counts separately named and the ordering required to
    be total)

- **Not** affected, established by reading each rather than by whether it felt
  in scope:
  - `storage-seam`. Its *port hands back domain objects* scenario asks that a
    port method reporting counts return a typed domain object whose fields are
    named. `DocumentPage` reports two counts and is exactly that, so the change
    satisfies the requirement rather than contradicting it. A MODIFIED block
    would be byte-identical, which the delta guidance says to cut.
  - `service-adapter-boundary`. The rule is that domain rules live in the
    service layer and adapters translate. The bound, the clamp, the reference
    resolution and the casefile scoping are all in the new service method; both
    adapters pass their arguments through. A new service method obeying the rule
    does not change the rule.
  - `mcp-surface-profiles`. No tool is added or removed. `case_list_documents`
    is already in the read-only allow-set and already stamped, and gaining
    parameters changes neither.
  - `untrusted-content-boundary`. Its *prose-free listing carries no summary*
    scenario holds: the per-row shape is unchanged, and every field added is a
    count, an offset or a resolved reference — no corpus prose, so still no
    fence.
  - `extraction-quality-gate`. Its *a person listing documents can see which
    were recognised* scenario holds: the per-row renderers are untouched, so
    every row still reports how its text was obtained.
  - `casefile-lifecycle`. Its *listing is newest first* sentence is about
    casefiles, which this change does not touch. The document intake selection
    remains newest first for the same reason it was.
  - `analyst-pack`. It requires the role to name the method and the tools it
    uses; adding a tool to that method is what the requirement asks for, and no
    count or enumeration in it goes stale.
  - `document-hierarchy`'s *A document records the document it came out of*.
    Its "ancestry SHALL be queryable in both directions" and its scenario
    "it is listed among its parent's children" both stay true — children are
    still queryable, through a method that additionally scopes and marks them.

- Affected code: `src/jackryan/storage/port.py`,
  `src/jackryan/storage/sqlite.py`, `src/jackryan/services/ingestion.py`,
  `src/jackryan/interfaces/mcp/server.py`, `src/jackryan/server.py`,
  `analyst/role.md`

- New tests: a paging file with an independent oracle for order and coverage,
  the nesting assertion the old `list_children` could not pass, the
  cross-casefile refusal, the agent journey driven through the tool surface, and
  REST/MCP field-by-field agreement. Six existing `list_children` call sites
  move to the paged method with their assertions unchanged; the advertised
  parameter table gains four names.

- **No migration and no schema change.** `documents` already carries
  `idx_documents_casefile` and `idx_documents_parent`, and nothing on
  `created_at` or `containment_path`, so each page sorts narrow rows — ids only —
  in SQLite's own sorter. No corpus-identity component moves: this change writes
  nothing, embeds nothing, and reads no setting that decides what a vector means,
  so no existing store is refused for it. Retrieval settings are profile for the
  same reason.
