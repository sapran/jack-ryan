# Design

## Decision 1: a listing of the document's passages, not passage ids on the read

`docs/implementation-notes.md` parked this gap with a guess at the fix — "closing
it means adding chunk identifiers to a read payload". That is the smaller diff
and it was rejected. Three reasons, in the order they decided it:

**The read bound is the agent adapter's, so the span is not the service's to
reason about.** `MAX_DOCUMENT_CHARS` lives in `interfaces/mcp/server.py`, and
`case_read_document` computes its own `start`, `span`, `window` and `truncated`;
there is no service-side read at all, and REST has no bounded text route to
disagree with it. Selecting the passages that overlap the returned window is a
domain rule — which passages a span reaches — and `service-adapter-boundary`
forbids an adapter holding one. Closing the gap in the read payload therefore
means either moving the read bound and its arithmetic into the service, which is
a change to an accepted contract that no acceptance criterion here asks for, or
passing the adapter's computed span into a service method, which is a service
rule taking its input from arithmetic an adapter did. Neither is smaller than a
listing; the second is smaller-looking and worse.

**Citing would then cost a read.** `case_read_document` is described on the
surface as the most expensive call available and the instructions say to reach it
last. Making it the only route to a passage identifier inverts that: to cite one
paragraph of a 400 KB document an agent must read the 20,000-character window it
sits in, and to find which window that is it may page the document. The listing
carries metadata for the whole document at a bounded page each, which is what an
index is for — and `case_get_passage` then reads exactly the one passage chosen.

**Two continuations in one payload.** `case_read_document` already carries
`truncated` and `continue_from` for its text. A passage index inside it that can
also be cut needs a second, independent continuation in the same payload, and
this surface has none. `mcp-tool-surface` asks for one continuation contract
"rather than two" precisely so an agent that has learned to follow a truncated
read need not learn a second spelling; a payload with two of them at once is the
shape that requirement argues against.

The listing, by contrast, is the third instance of a shape the surface already
has twice — `case_list_documents` and `case_mention_documents` — with the same
field names, the same clamps, the same count-under-the-same-predicate rule and
the same total-ordering requirement.

## Decision 2: the listing carries no passage text

A row carries `chunk_id`, `document_id`, `ordinal`, `heading_path`, `char_start`,
`char_end` and `characters`. It deliberately does not carry a preview of the
passage's words, which was considered and rejected.

`untrusted-content-boundary` says a payload "built on the promise of carrying no
corpus prose SHALL NOT be used to carry derived text", and `listing_payload`'s
own docstring is that promise: "A listing that carries no corpus prose, so it
needs no fence." A clipped preview would either ship corpus prose unfenced or
force a fence into a shape whose stated reason for not needing one had quietly
stopped being true — which is the failure that paragraph exists to name.

The cost is real and is accepted: in a document with no headings, the rows
distinguish themselves only by position. Relevance is then established the way
the surface already establishes it — `case_get_passage` reads one candidate
passage with its surroundings, bounded, and `case_cite` returns the passage's own
words beside the citation. An agent that has read the document can also map an
offset it saw to the row whose span covers it. What the listing must never do is
look like evidence; it is an index into evidence.

The heading path is corpus-derived and does reach the payload, collapsed to one
line like every other document-derived value, and the payload carries the content
notice for the reason `case_mentions` carries it — every value in it was written
by whoever wrote the documents. That is metadata of the same kind as a filename,
which every existing listing row already carries.

## Decision 3: the service method lives on `IngestionService`

Passages are retrieval objects and `SearchService` owns `resolve_passage`,
`passage_window` and the mention enumeration. This method still belongs to
`IngestionService`, for one reason: it takes a *document* reference, and
`resolve_document` — the one definition of how a document reference is resolved
inside a casefile, with 8-character prefixes and the ambiguity refusal — is
`IngestionService`'s. `SearchService` holds no document resolution, and giving it
one would be a second definition of the rule that decides casefile confinement
for this call. `IngestionService` already carries the document navigation queries
this joins — `list_document_page`, `containment_chain`, `document_locations` —
and already reaches chunks through `list_document_chunks` for the offset repair,
so no new dependency appears.

## Decision 4: the ordering is the passage's position, and it ends in an identifier

`ORDER BY ordinal, char_start, id`.

`ordinal` is the document's own reading order, which is what an agent walking a
document wants and what makes the listing an index. `chunks` does not enforce
uniqueness on `(document_id, ordinal)` — the chunker produces them sequentially,
but the schema does not say so — so the ordering cannot rest on it:
`mcp-tool-surface` requires a total order so that a page boundary cannot fall
inside a tie and repeat or skip an entry.

`char_start` is the corpus-derived tiebreak. `id` is last, and that is
deliberately unlike the fused-ranking rule which forbids breaking a tie by an
identifier: that rule exists so two stores built from the same documents rank
alike, and chunk ids are minted afresh by every reingest. Here the requirement is
only that one unchanged store pages consistently, and `id` is reached only where
two passages share both an ordinal and a start — passages at the same place in
the same document, which is the case `hybrid-search` itself calls the exception
because "whichever is returned first, the caller is reading the same words at the
same place".

## Decision 5: `characters` comes from the stored text, not from the span

A row reports `LENGTH(text)` rather than `char_end - char_start`. On a corpus
ingested after `a-chunk-begins-where-its-text-does` the two agree exactly, by
construction. On an older one they do not: those rows record the untrimmed
window, so the span overstates the passage by however much whitespace was
trimmed. `characters` is what the caller would receive if it read the passage, so
it is read from the passage.

It is computed on the chosen page and not on every passage in the document. The
page is selected on a query over `id` and the ordering columns and widened
afterwards, exactly as `list_document_page` and `documents_with_mention` are: an
`ORDER BY` that requires a sort makes SQLite compute the output columns for every
matching row, so `LENGTH(text)` in a single-statement form would read every
passage's text in the document to report a page of integers — the cost this shape
exists to avoid.

## Decision 6: a document with no stored passages is answered, not empty

A document can hold no passages, and it is reachable rather than theoretical.
`router.extract` refuses to store a document whose text is not usable — "an empty
document, which is worse than a failure because it looks ingested" — but exempts
a container, "because an archive's value is in its entries". An archive holding
no entries therefore produces no listing text, is stored, and has no chunks. An
older corpus may hold empty documents from before that guard.

The payload says so in words, and says what to do instead, rather than returning
an empty list a caller reads as "this document has no evidence in it". This is
the same rule `_nothing_listed` and `_no_carriers` already apply on this surface,
and the same rule that makes an unknown facet kind an error naming the kinds
rather than an empty result: an empty answer that stands in for a different fact
is the most damaging thing this tool can return.

It deliberately does **not** report the document's child count, even though
"enter it instead" is the useful next move for the container case. `resolve_document`
selects `*` and aliases no `child_count`, so the resolved document reports zero
children whatever it holds — the self-contradiction `list_document_page` already
has to repair for its `parent`. The message names the tool to use rather than
asserting a count it cannot support.
