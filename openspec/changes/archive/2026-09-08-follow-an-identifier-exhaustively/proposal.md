## Why

An analyst pivots on an identifier: `case_mentions` reports an email address in sixty
documents, and the only way to reach them is `case_search` filtered to that identifier.
That search is bounded twice over — each retriever is asked for `limit * 5` candidates and
the fused result is cut to the caller's limit, which the agent surface caps at 50 with no
paging. Sixty carriers come back as ten passages, and nothing in that response says so: the
payload's `total` counts the passages returned, and an agent reading it as a quantity of
evidence reports the first ten documents as the whole set.

Raising the depth is not the fix. Reciprocal rank fusion ties routinely — the root
`CLAUDE.md` records ties being broken by an identifier costing 0.058 recall@1 until they were
broken by the corpus — so two requests at different depths do not agree about which candidate
sits at any given position. Pages cut out of that ordering repeat and omit entries without
saying so, which is a quieter version of the same wrong answer.

The two figures the instance already reports about one identifier cannot be reconciled by a
caller either: `case_mentions` says "60 documents", `case_search` returns 10 passages, and
there is no path from the first number to the documents it counts.

## What Changes

**Current behaviour.** The documents carrying an identifier are reachable only through
ranked search, bounded by a result limit and a candidate depth, with no paging and no
statement that the bound was reached.

**Desired behaviour.**

- **A new exhaustive enumeration**, store → service → agent surface, with REST and CLI
  counterparts: every document in a casefile carrying one normalised identifier, a bounded
  deterministic page at a time. The domain vocabulary is a **carrier** — a document that
  carries an identifier: `MentionCarrier`, `MentionDocumentPage.carriers`.
- **Each entry carries what reads and cites it**: the document, how many textual occurrences
  it holds, and the passage identifier addressing the earliest of them. That last field is
  what makes the enumeration evidence rather than a list — a document reached this way is
  citable through `case_cite` with no search having run.
- **The occurrence counts reconcile with the inventory.** They are counted by distinct
  document position, the way `mention_facets` counts, so the entries' counts sum to the
  facet's `mentions` and the number of entries equals its `documents`. A row count would be
  wrong by exactly the contract's chunk overlap, invisibly.
- **The ordering is total** — occurrences descending, then containment path, creation time
  and document id — so a page boundary cannot fall inside a tie, and the most heavily
  carrying document is reached first. Deliberately unlike the fused-ranking rule that
  forbids breaking a tie by an identifier: that rule exists so two stores built from the
  same documents rank alike, and this one only requires that one unchanged store pages
  consistently.
- **One definition of the identifier predicate.** `mention_predicate` is extracted in
  `storage/retrieval.py` and used by both the search filter and the enumeration, so the two
  cannot drift into disagreeing about what carries an identifier — the failure the root
  `CLAUDE.md` already records for `sniffing.py`/`legacy_office`.
- **Ranked search states what its count is.** `case_search`'s description says its `total`
  counts the passages returned, never how many the casefile holds, and names the new tool.
  No search behaviour changes.
- **An empty identifier is refused.** `_parsed_mention` returns no filter for one, which is
  right for a search and wrong here: the store would match `normalised = ''`, find nothing,
  and the caller would read an empty carrier set as "this casefile carries no such
  identifier" — the silent false negative this capability exists to remove.

**Deliberately not in scope.** Ranked search itself is unchanged — no paging, no depth
change, no new field. `jackryan repair mention-offsets` is not run: a corpus ingested before
the chunk-offset fix holds stale positions, so its per-carrier counts and the inventory's
mention counts inherit the same known overcount, while the carrier *set* and `total_matching`
stay correct because those come from `COUNT(DISTINCT document_id)`.

## Impact

**Why this cannot be deferred.** The prototype's premise is that the assistant works the
corpus and answers with resolvable citations. A pivot that silently truncates makes a partial
answer indistinguishable from a complete one, and the tool's own instructions demand a
coverage claim that names what was searched — which is unanswerable when the surface cannot
say whether a bound was reached. An empty or partial carrier set read as a census is the most
damaging wrong answer this tool can give.

- **Specs:** `mentions` (1 ADDED — the exhaustive enumeration) and `hybrid-search` (1 ADDED —
  ranked search is bounded and is not an enumeration). **No MODIFIED anywhere.** Established
  by reading every published requirement in `mentions`, `hybrid-search`, `mcp-tool-surface`,
  `mcp-surface-profiles`, `analyst-pack`, `storage-seam` and `service-adapter-boundary`: none
  asserts a tool count, enumerates the tool set, or states anything this change falsifies.
  `mcp-tool-surface`'s *"Reads are bounded, and truncation is explicit"* already binds the new
  tool — both counts separately named, `truncated`, `continue_from`, a total ordering, clamped
  arguments — and its *"A result separates its index from its bodies and carries chaining
  identifiers"* already requires `chunk_id` and `document_id` on an entry addressing a
  passage, so a scenario there is not owed. No `Purpose` block is falsified, and a delta could
  not reach one. There is no `openspec/config.yaml` in this repository, so no project-context
  prose to audit.
- **Code:** `storage/retrieval.py` (the predicate extracted; the assembled SQL and its
  parameter order are byte-identical), `storage/port.py` (two domain objects, one port
  method), `storage/sqlite.py` (the paged query and its passage pick), `services/search.py`
  (`mention_documents`, two bounds), `interfaces/mcp/server.py`, `interfaces/mcp/annotations.py`,
  `interfaces/mcp/profiles.py`, `analyst/role.md`, `server.py` and `cli.py`.
- **Data:** **no schema change.** `idx_mentions_pivot(casefile_id, normalised)` serves the
  seek and `idx_mentions_facet(casefile_id, kind, normalised)` serves it with a kind, so
  there is no `_STEPS` entry, `SCHEMA_VERSION` stays 8, and no corpus is refused or migrated
  by this change. Nothing is written: the enumeration is a read.
- **Tests:** a new `tests/test_mention_documents.py` (the bounded sweep, the
  inventory-agreement oracle, the overlap count, refusals, clamping, and the citation journey
  with `case_search` removed from the server), and four cross-surface tests in
  `tests/test_result_shape.py`.
