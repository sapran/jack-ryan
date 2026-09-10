# Guard the rules that had only prose

## Why

The seven changes of 2026-09-06 and 2026-09-07 each gave one shared rule a single
owner. An audit on 2026-09-10 found all seven owners intact: nothing was undone,
and the five functional changes that followed routed through every one of them —
the new enumeration query reuses `retrieval.mention_predicate` rather than
respelling the filter, all ten agent tools inherited the one error translation by
being decorated, and `render_report` went into `rendering.py` instead of becoming
a fourth copy.

What the audit also found is that every erosion since then sits in a rule the
programme left to review rather than to a test:

1. **The two human surfaces build the same payload by hand again.** The five
   location keys are assembled in `cli.py` and again in `server.py`; the
   identifier-carrier envelope likewise. This is the shape
   `one-renderer-for-the-two-human-surfaces` removed, and it is held together
   only by a parity test that runs after the fact.
2. **An adapter re-derives a decision the service made.** The overview tool
   re-derives which of three grounds produced an `unknown` coverage verdict,
   with a precedence the service never states. Today the final branch is
   unreachable; the moment a fourth ground is added to the service it prints
   "0 documents predate the first recorded ingest run" in the one line an agent
   is told to read first.
3. **A rule two of three page types own.** `MentionDocumentPage` and
   `DocumentPassagePage` each carry `beyond_the_end`, whose docstring says the
   decision belongs to the page "because every surface has to answer the same
   question and must not answer it differently". `DocumentPage` lacks it, so the
   agent surface re-spells it inline — and the `truncated`/`continue_from`
   arithmetic is copied three times, which is how the third copy came up one
   property short.
4. **One bound spelled three times.** Three hand-written 50/200 pairs whose
   comments assert they are one rule. Equality maintained by comment is the
   `sniffing`/`legacy_office` shape that `one-owner-for-a-file-signature`
   removed, because two spellings drifting apart is silent.
5. **Seven declared invariants with no guarding test** — including "the port
   speaks in domain objects rather than rows", which is why `store_document`
   still returns `tuple[Document, bool]` and nothing objects.

The fifth is the cause of the other four. A rule with prose and no test is a
rule the next change erodes for free, so this change closes the four and then
makes the prose checkable.

## What Changes

- One `BoundedPage` base owns `truncated`, `continue_from` and `beyond_the_end`
  for all three paged listings; `DocumentPage` gains the property it lacked and
  the agent surface reads it instead of re-deriving it.
- `CasefileCoverage` carries the `ground` of an `unknown` verdict, decided in
  `CasefileService.coverage` with a stated precedence; the overview tool only
  words it.
- `rendering.py` gains `render_location_record` and `render_carrier_page`; both
  human surfaces call them instead of assembling those payloads twice.
- The three 50/200 pairs collapse to one default and one maximum in the service
  layer. `MAX_SEARCH_RESULTS` in the agent adapter is a *search* bound, not a
  listing bound, and is deliberately untouched — sweeping it in would move the
  clamped search maximum from 50 to 200, which no requirement authorises.
- `store_document` returns a frozen `StoredDocument(document, location_is_new)`.
- Parsing guard tests for the invariants that had prose only: the port returning
  domain objects rather than rows or unnamed tuples, `services/search.py` not
  re-exporting `MAX_RESPONSE_CHARS`, `CorpusIdentity` having no `parse`, a file
  signature having one definition, `sqlite.py` reaching `migrations` by
  attribute rather than by `from`-import, and the agent surface staying out of
  `rendering.py`.

**No observable behaviour changes.** Every payload, message, field name and
number stays byte-identical. This is deliberate: a change whose purpose is to
make existing rules enforceable must be provable by the existing suite staying
green, plus new guards that go red when the rule is broken.

## Impact

Two capabilities owe a delta, and both were established by falsification rather
than by topic — three published specs were read in full and classified
requirement by requirement:

- **`storage-seam`** — MODIFIED, widened: the requirement that the port speaks in
  domain objects defines the forbidden shape as an untyped mapping. An unnamed
  tuple is the same defect and was the last instance of it.
- **`service-adapter-boundary`** — MODIFIED, widened: the requirement placing
  business rules in the service layer covers validation and reference resolution
  but not an adapter re-deriving a decision the service already made. Plus one
  ADDED requirement: the shared-presentation rule for the two human surfaces
  exists today only in a module docstring, and no published requirement in this
  capability contains the word "render" at all.

Classified and owing nothing, each checked against all five units:

- **`mcp-tool-surface`** — 5 requirements, 22 scenarios. States no page-size
  number or constant anywhere, pins no empty-page or coverage wording, and
  assigns no surface the job of deciding emptiness. Its one-continuation-contract
  duty is made *more* true by the shared base.
- **`ingestion-coverage`** — 4 requirements, 16 scenarios. Never says where the
  verdict's ground is decided, quotes none of the tool's sentences, and asserts
  no precedence among the three grounds. Its requirement 4 already forbids the
  *store* holding a second opinion about the verdict; that an *adapter* held one
  about the ground is the gap this change closes. Note the tripwire at
  `ingestion-coverage/spec.md:135`: the ground count is fixed at exactly three,
  so a fourth ground is a spec change, which is now also a code change rather
  than a silent wrong sentence.
- **`document-hierarchy`** — 4 requirements, 19 scenarios. No page-size number,
  no default page size, no continuation field; its only bound is
  `MAX_DOCUMENT_LOCATIONS`, which this change does not touch.

Data and migrations: none. No schema change, no corpus identity component, no
reingest. The store is untouched apart from `store_document`'s return type,
which is internal to the seam.
