## Why

`expose-container-contents` gave an agent a way into a container: a row's
`children` count marks a document to enter, and `case_list_documents` with a
`parent` lists what came out of it, bounded and paged. That works, and it is
accepted.

What it did not give is a way to *cite* what it reached. `case_cite` takes a
`chunk_id`, and no tool on this surface hands one back for a document reached
through `case_list_documents`: `case_read_document` returns text, spans and
provenance, and no passage identifier. So the journey the capability exists for —
list the intake, enter an archive, read an attachment — has to fall back to
`case_search` to recover an id before it can cite the words it has just read.

That is not a cosmetic gap. The premise of container navigation is that a
container is exactly where retrieval is *least* likely to surface the evidence:
an attachment's text is short, its filename is generic, and it competes against
the whole corpus. Requiring a ranked search to close the journey puts the
citation back behind the one mechanism the navigation was built to route around.
A child that carries no distinctive phrase — a scanned receipt, a two-line
covering note — is then reachable, readable and uncitable.

The gap was recorded rather than guessed at. It is parked in
`docs/implementation-notes.md` under *A document reached by listing cannot be
cited without a search*, and the journey test
`test_an_agent_reaches_and_reads_a_child_without_searching` says so in its own
docstring after an earlier version claimed more than it proved. Independent
verification of task 2 reproduced it: the selected child's read payload exposed
document identifiers and character spans but no passage identifier, and passing
the document id to `case_cite` returned `not_found`.

`follow-an-identifier-exhaustively` narrowed it and deliberately did not close
it. `case_mention_documents` hands back a `chunk_id` per carrier, so a document
reached by *identifier* is citable with no search. A document reached by
*browsing* still is not, and browsing is the path that exists for evidence no
identifier and no query names.

## What Changes

**Current behaviour.** A document's passages are reachable only as search
results. `StorePort` can list one document's chunks — `list_document_chunks`,
added for the offset repair — but unbounded and carrying every chunk's text, so
it is a maintenance call rather than a surface one. No service method and no
adapter offers a document's passages.

**Desired behaviour.** One bounded, paged, deterministically ordered listing of
one document's stored passages, owned by the service layer and reachable
identically from the agent surface and REST. Each entry addresses a passage that
`case_get_passage` and `case_cite` already accept, so a document reached by
browsing is citable without a ranked search.

- **`PassageReference`** — a frozen dataclass carrying a passage's identifier,
  its document, its ordinal, its heading path, its span and how many characters
  it holds. A passage addressed *without* its text, which is the whole reason it
  is not `Chunk`: a listing that carried every passage's text would pay for the
  document's whole corpus to answer a question about its shape, and a `Chunk`
  with `text=""` is indistinguishable from a passage that holds nothing.
- **`DocumentPassagePage`** — the passages, how many the document holds, the
  offset and limit, and the document the page belongs to. `truncated`,
  `continue_from` and `beyond_the_end` are derived properties, in the vocabulary
  `case_read_document` and both existing paged listings already use, so an agent
  meets one continuation contract rather than a third.
- **`StorePort.list_document_passage_page`** — one page and the count, under the
  same predicate, ordered by the passage's own position in its document. The
  page is chosen on a narrow query and widened afterwards, as both existing
  paged listings are, so `LENGTH(text)` is paid for the page rather than for
  every passage in the document.
- **`IngestionService.list_document_passage_page`** owns the bounds, the
  reference resolution and the casefile scoping, all inherited from
  `resolve_document`. A document in another casefile raises `NotFoundError` and
  its passages are never queried.
- **`case_list_passages`** on the agent surface — a new tool, admitted to the
  read-only allow-set and stamped read-only. Its rows carry `chunk_id` and
  `document_id`, which is what `mcp-tool-surface` requires of an entry that
  addresses a passage. The instructions gain it as a step of the method and so
  does the shipped analyst role.
- **REST gains `GET …/documents/{document_reference}/passages`**, with the same
  parameters and the same field names, so the two surfaces answer one question
  the same way.
- **A document with no stored passages is answered explicitly.** The payload
  says the document has nothing to cite rather than returning an entry that
  addresses nothing. This is reachable rather than theoretical: `router.extract`
  exempts a container from the empty-text refusal, so an archive holding no
  entries is stored with no text and therefore no passages.

**Deliberately not the alternative the parked note guessed at.** That note said
closing this "means adding chunk identifiers to a read payload". It was
rejected, for reasons recorded in `design.md`: the read bound lives in the agent
adapter, so a passage index computed against the returned window would either
move that bound into the service or feed a service rule with arithmetic an
adapter did — and citing a passage of a large document would then cost a read of
the region it sits in, which is the most expensive call on the surface.

**Deliberately not in scope.** The CLI gains nothing, for the reason
`expose-container-contents` gave for leaving `jackryan document list` alone:
there is no acceptance criterion here that a human surface serves, and the
existing citation journey is an agent's. Ranked search, the mention enumeration,
duplicate-location storage and the offset repair are untouched. No index is
added — see Impact.

## Impact

- Affected specs:
  - `mcp-tool-surface` (ADDED — *A document reached by navigation is citable
    without a ranked search*: a bounded, paged enumeration of one document's
    stored passages, each entry addressing a citable passage and carrying its
    position; confined to its casefile; explicit about a document that holds
    none; and carrying no passage prose)

- **Not** affected, established by reading each rather than by whether it felt
  in scope:
  - `mcp-tool-surface`'s *Reads are bounded, and truncation is explicit*. Its
    listing paragraphs already govern any listing on this surface — bounded,
    both counts separately named, one continuation vocabulary, a total ordering
    so a page boundary cannot fall inside a tie. The new listing obeys them, so
    the requirement is satisfied rather than changed and a `MODIFIED` block
    would be byte-identical, which the delta guidance says to cut.
  - `mcp-tool-surface`'s *A result separates its index from its bodies and
    carries chaining identifiers*. "An entry that addresses a passage SHALL
    carry `chunk_id` and `document_id`" is exactly what the new rows carry, and
    "an identifier a tool returns SHALL be accepted by the tools that address
    that kind of object" is what makes the journey work. Satisfied, not changed.
  - `untrusted-content-boundary`. Its *a prose-free listing carries no summary*
    scenario holds: the new listing carries no passage text and no derived text,
    which is why it needs no fence — the same standing this payload shape has
    everywhere else on the surface. The heading path is corpus-derived metadata
    and is collapsed to one line like every other such value, and the payload
    carries the content notice for the reason `case_mentions` does.
  - `mcp-surface-profiles`. Its rules are that an allow-set is explicit and that
    "a tool added later is hidden until it is admitted deliberately", and that
    every tool is stamped. Admitting and stamping one tool is the behaviour those
    requirements prescribe; neither names a tool or a count.
  - `hybrid-search`'s *Ranked search is bounded and is not an enumeration*.
    "Completeness SHALL be reachable by a separate path rather than by raising
    the depth" is what this adds another instance of. Nothing in it names the
    identifier path as the only such path, and ranked search is untouched.
  - `storage-seam`. Its *port hands back domain objects* scenario asks that a
    port method reporting counts return a typed object whose fields are named.
    `DocumentPassagePage` and `PassageReference` are exactly that.
  - `service-adapter-boundary`. The bounds, the clamp, the reference resolution
    and the casefile scoping are all in the new service method; both adapters
    pass their arguments through and translate. A new service method obeying the
    rule does not change the rule.
  - `chunking-and-embedding`. Nothing about how a document is divided, embedded
    or bounded changes. A passage's stored span and text are read, never
    rewritten.
  - `document-hierarchy`. Its listing requirement is about documents and their
    ancestry; a passage is neither. Every scenario in it stays true.
  - `analyst-pack`. It requires the role to name the method and the tools it
    uses; adding a tool to that method is what the requirement asks for, and no
    count or enumeration in the pack goes stale.
  - `mentions`. Its *citable carrier* requirement and its scenario *A carrier is
    cited without a ranked search* stay true and stay the identifier path's own.

- Affected code: `src/jackryan/storage/port.py`,
  `src/jackryan/storage/sqlite.py`, `src/jackryan/services/ingestion.py`,
  `src/jackryan/interfaces/mcp/server.py`,
  `src/jackryan/interfaces/mcp/annotations.py`,
  `src/jackryan/interfaces/mcp/profiles.py`, `src/jackryan/server.py`,
  `analyst/role.md`

- New tests: `tests/test_document_passages.py` — the ordering and coverage sweep
  against an independent oracle, the clamps at both ends of both bounds, the
  cross-casefile refusal, a document with no stored passages, the prose-free
  promise, REST/MCP field agreement, and the journey driven through the tool
  surface with `case_search` removed from the server. One existing test changes:
  `test_an_agent_reaches_and_reads_a_child_without_searching` in
  `tests/test_document_paging.py`, whose docstring records the gap this change
  closes and whose citation step goes through `case_search` because it had to.
  The advertised-parameter table in `tests/test_mcp_surface.py` gains a row.

- **No migration and no schema change.** `chunks` already carries
  `idx_chunks_document`, and the ordering is `ordinal` — an integer column of
  the same rows the index selects. No corpus-identity component moves: this
  change writes nothing, embeds nothing, and reads no setting that decides what
  a vector means, so no existing store is refused for it and no corpus needs
  reingesting to gain the capability.
