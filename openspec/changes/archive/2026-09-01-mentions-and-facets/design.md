## Context

See `proposal.md` § Why. Six properties of the code as it stands shape everything below, each read on
`change/mentions-and-facets` at its base commit `3f99d8c`.

**Chunk identifiers are minted afresh on every reingest.** `_prepare_chunks` builds each `Chunk` with
`uuid.uuid4().hex`, and `replace_chunks` deletes the document's chunk rows and inserts new ones. Any
row keyed on a chunk id must therefore be written by the same call.

**One transaction already covers chunks, full-text entries and vectors.** `replace_chunks`
(`storage/sqlite.py`) opens a transaction, deletes by `document_id` — which the `AFTER DELETE` trigger
turns into deletions from `chunks_fts` and `chunk_vectors` — then inserts all three per chunk. This is
the transaction mentions must join.

**Both retrievers fetch a bounded depth.** `SearchService.search` computes `depth = limit * 5`, raised
to `rerank_depth` when a reranker is configured, and passes it to both legs. Everything about where the
mention predicate goes follows from this one fact.

**The vector leg already makes this exact argument for the casefile.** `search_vector` puts the
casefile constraint inside the `MATCH` subquery, with a comment saying that filtering after a global
KNN "would silently lose hits whenever another casefile owned the top of the list". The mention
predicate is the same problem and takes the same answer.

**`PRAGMA foreign_keys=ON` is set, and `chunks.id` is `TEXT NOT NULL UNIQUE`.** SQLite accepts a
UNIQUE text column as a foreign-key parent, so `ON DELETE CASCADE` from a mentions table works. The
sidecar trigger exists only because `chunks_fts` and `chunk_vectors` are virtual tables, which never
observe a cascade; a real table does.

**The MCP surface has five registration points for a tool, and two of them fail loudly.**
`stamp_for` raises `UnstampedToolError` at tool-definition time, so omitting `ANNOTATIONS` fails the
build. `test_only_the_profiles_tools_are_advertised` asserts exact set equality, so omitting
`READONLY_TOOLS` fails a test. The other three — `INSTRUCTIONS`, the tool itself, and `analyst/role.md`
— are containment-checked or unchecked, so omitting them drifts silently.

## Goals / Non-Goals

**Goals.** Four precise pattern extractors behind a registry that is the NER seam. Mentions written in
the chunk transaction. A search filter applied inside both retrievers. A counted inventory reachable
from all three surfaces.

**Non-Goals.** Any model-backed extraction. Tag, actor, date or language facets. Promoting a mention to
a curated entity. Changing corpus identity, which mentions must not touch.

## Decisions

### The predicate goes inside the SQL of both legs, and this is the whole change

Everything else here is plumbing. This is the part that is easy to get wrong and impossible to notice.

Both retrievers are asked for `depth = limit * 5` candidates. A caller searching for "payment" filtered
by an IBAN gets, if the predicate is applied to the retrievers' output: the top fifty candidates for
"payment", intersected with the passages carrying that IBAN. On a corpus of 36,000 chunks that
intersection is empty almost always, and the response is indistinguishable from "this casefile does not
mention that account" — which is the single most damaging wrong answer an evidence tool can give.

Applied inside the SQL, each retriever returns the top fifty candidates *that carry the IBAN*, and
fusion ranks them. The store holds the answer either way; only one arrangement returns it.

```sql
AND c.id IN (SELECT chunk_id FROM mentions
             WHERE casefile_id = ? AND normalised = ? [AND kind = ?])
```

Two further consequences worth stating because they are the reason this is not merely a performance
choice. Filtering in the store keeps the filter *before* fusion, so `hybrid-search`'s guarantee that
reranking only reorders what fusion produced still holds unchanged. And it keeps the filter out of the
scoring path entirely: there is no rank leg for mentions, no bonus, nothing to tune. A filter that
touched the score would be a third retriever wearing a filter's name, and the prohibition on blending
scores would be circumvented rather than honoured.

**The trap:** `mcp/server.py` calls `anyio.to_thread.run_sync(context.search.search, casefile, query,
bounded)`, and `run_sync` takes positional arguments only. The new parameter must be passed positionally
or wrapped in `functools.partial`. Starlette's `run_in_threadpool` does forward keywords, so REST is
unconstrained — the asymmetry is exactly the kind that gets discovered at runtime.

### Mentions cross the port as a parameter of `replace_chunks`, not as a new method

`replace_chunks(document_id, chunks, embeddings, mentions)`. `StorePort` is a `typing.Protocol`, so this
breaks type-checking rather than imports, and every test double is updated in the same pass.

A separate `write_mentions` called afterwards is the obvious alternative and is wrong twice over. Chunk
ids are minted fresh, so the mentions would reference rows that had just been replaced — and the
failure is undetectable afterwards, because the rows would be well-formed and would reference
identifiers that did once exist. Second, a seam that can be used in the wrong order eventually is. The
codebase already documents this hazard as the reason chunk text, its index entry and its vector share
one call.

### Four extractors, and precision is the acceptance bar

| kind | rule | normalised |
|---|---|---|
| `email` | local@domain, standard character classes | lowercased |
| `phone` | leading `+`, 8–15 digits, separators allowed | `+` then digits |
| `iban` | ISO 13616 shape **and a passing mod-97 check** | uppercase, spaces stripped |
| `registration_number` | 8–12 digits anchored to a preceding `ЄДРПОУ`/`ЕДРПОУ`/`ИНН`/`ІПН`/`EDRPOU` within 40 characters | digits only |

The mod-97 check and the keyword anchor are what make these worth faceting rather than decorative. A
bare eight-digit regex over a corpus of this size returns every date written `20240115`, every invoice
line and every page number, and produces an inventory an analyst scrolls past once and never opens
again. Precision over recall is a deliberate trade and is stated in the spec so a later change cannot
loosen it silently.

The contingency, if `registration_number` proves noisy on real material: drop that extractor and ship
three. Loosening the anchor is not on the table — it converts a precise facet into the useless one.

### The facet is a separate port method, not an envelope on search

`SearchService.search` returns a bare `list[SearchHit]`. Facet counts have nowhere to live in that, and
introducing an envelope would change three surfaces for a question none of them asked. So
`StorePort.mention_facets(casefile_id, kind, limit) -> list[MentionFacet]`, one `GROUP BY kind,
normalised` with `COUNT(*)` and `COUNT(DISTINCT document_id)`, ordered by count descending.

Both counts are carried because neither substitutes for the other: an identifier mentioned forty times
in one document is a different fact from one mentioned once in each of forty, and an analyst deciding
where to look needs to tell them apart.

### The facet payload uses `listing_payload`, and that is a decision the return shape forces

`listing_payload`'s docstring is that it "carries no corpus prose, so it needs no fence". A facet entry
carries a kind, a normalised identifier, and two integers. A normalised IBAN or email address is
corpus-derived, but it is not prose: it has no sentences for an instruction to hide in, it is bounded
in length by its own format, and it is passed through the same one-line collapse every corpus value
gets before reaching a line-oriented block.

So `listing_payload` holds — provided the payload returns the bare identifier and the counts and
nothing else. It stops holding the moment a facet entry carries a surrounding snippet, and a later
change that adds one must move to `search_payload`'s fencing. Stated here because the choice is only
correct under a condition, and the condition is invisible from the call site.

### An unknown kind is a `ValidationError`, not an empty list

Asked for `--mention passport:12345`, the instance must refuse and name the four kinds. Returning an
empty result would tell the analyst the casefile contains no such identifier, which is not what
happened and not true. This is the same reasoning `document-ingestion` uses for refusing text that is
punctuation alone rather than treating it as empty: a wrong answer that looks like a real one is worse
than an error.

## Risks / Trade-offs

**Existing corpora gain no mentions until reingested.** The migration creates an empty table. A
casefile ingested before this change has no mentions, so its facet is empty and a filtered search over
it returns nothing — which is indistinguishable, to the analyst, from a corpus that genuinely contains
none. That is the one place this change can mislead. It is not fixable by a migration: the mentions
have to be extracted from chunk text, which means re-running extraction, which is a reingest. Recorded
in `docs/handover.md` rather than papered over, because the honest mitigation is telling the operator.

**Four regexes over every chunk of every document, at ingest.** Measured cost is milliseconds per
document and the extractors reach no endpoint, which is why there is no setting. The risk is not
performance but the absence of a switch: an extractor that turns out to be noisy cannot be turned off
without a code change. That is deliberate — a switch would let a noisy extractor survive rather than be
fixed or dropped.

**Precision over recall means real identifiers are missed.** A registration number written without its
keyword, an IBAN typed with a transposition, a phone number in a purely local format: all invisible to
the facet. An analyst who trusts the facet as complete will draw a wrong conclusion. The facet is an
inventory of what was *found*, never a claim about what is *there*, and the analyst pack's own rule that
absence of evidence is not evidence of absence applies to it exactly.
