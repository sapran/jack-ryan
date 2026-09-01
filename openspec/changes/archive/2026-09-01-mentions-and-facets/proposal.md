## Why

Mentions are the last leg of M3 other than PST. `docs/handover.md` names it:
classical NER plus pattern identifiers, as facets and pivots, with pattern extraction needing no model
and able to ship first.

The gap it closes is a specific one. An analyst opening a casefile of 1,760 documents can search for a
term they already suspect, and cannot ask what the corpus contains. `docs/design.md` § 5 lists facets —
doc type, language, date, path, mention, tag, actor — and says the mention, tag and actor facets arrive
with the features that populate them. This is that feature for mentions: the corpus tells the analyst
what it calls things, which is the step the analyst role's own method calls *pivot*.

Three things are absent today:

1. **No extraction of any kind beyond chunking.** `src/jackryan/` has no mentions module, no entity
   model, and nothing that reads a chunk for structure. `openspec/specs/` has no mentions, entities or
   facets capability — this change creates it.
2. **No way to filter a search.** `SearchService.search` takes a casefile, a query and a limit.
   `StorePort.search_keyword` and `search_vector` take a casefile, a query or embedding, and a depth.
   There is no predicate anywhere.
3. **No inventory call.** `casefile_statistics` counts documents, characters and media types. Nothing
   aggregates over the content of the text.

## What Changes

**Current behaviour.** Ingestion chunks a document, optionally folds a summary into what is embedded,
and stores chunks with their full-text entries and vectors in one transaction. Search runs two
retrievers at a bounded depth, fuses by rank, optionally reranks, and widens each hit. Nothing reads a
chunk for identifiers, and nothing can narrow a search to a subset of the corpus.

**Desired behaviour.**

- **A registry of mention extractors**, four of them shipped, run over a document's chunks at ingest
  with no setting to enable. The registry is the seam a classical NER model arrives through later: it
  registers as one more extractor with a kind and a name, and needs no schema, facet or surface change.
- **Precision over recall, stated as a rule and enforced by the shipped set.** The IBAN extractor
  validates the mod-97 check digits rather than matching the shape; the registration-number extractor
  requires a naming keyword within a short distance. A bare eight-digit pattern fires on every date,
  invoice line and page number in a corpus of this size, and a facet nobody can use costs more than an
  absent one.
- **Mentions written inside the transaction that writes the chunks.** Chunk identifiers are minted
  afresh on every reingest, so a separate call afterwards would attach mentions to identifiers that
  had just been replaced. `StorePort.replace_chunks` takes them as a parameter.
- **A search filter applied by the retrievers, not to their results.** `--mention <kind>:<value>` or
  `--mention <value>`, matched on the normalised form, as a predicate inside the SQL of both legs. Both
  retrievers fetch a bounded depth, so filtering their output would silently drop every matching
  passage that ranked below that depth unfiltered.
- **An inventory of a casefile's identifiers**, counted by mentions and by documents, ordered by
  frequency and bounded, reachable from the CLI, REST and one new MCP tool.
- **An unknown kind is an error naming the four**, never an empty result. An empty result reads as
  "this corpus contains none", which is a different and false statement.

**Deliberately not in scope.** No classical NER model and no model-backed pass — the registry is the
seam, and shipping the model is a separate change with its own download, licence and measurement
questions. No tag or actor facet. No promotion of a mention to a curated entity, which `docs/design.md`
places in P6. No date or language facet.

## Impact

- Affected specs: `mentions` (ADDED — new capability), `hybrid-search` (ADDED), `storage-seam` (ADDED),
  `mcp-tool-surface` (MODIFIED)
- **Not** affected, contrary to the plan this change was written from: `mcp-surface-profiles`. Its
  requirements are about the mechanism — an explicit allow-set, narrowing on a mistake, a stamp for
  every tool — and name no tool. Adding one satisfies them rather than falsifying them, and a MODIFIED
  block reproducing it byte-identically would be noise. `analyst-pack` likewise requires the role to
  "name the tools that method uses" without enumerating them.
- New code: `src/jackryan/mentions/` (`port.py`, `patterns.py`, `__init__.py`)
- Affected code: `src/jackryan/storage/port.py`, `src/jackryan/storage/sqlite.py`,
  `src/jackryan/services/ingestion.py`, `src/jackryan/services/search.py`,
  `src/jackryan/interfaces/mcp/server.py`, `src/jackryan/interfaces/mcp/annotations.py`,
  `src/jackryan/interfaces/mcp/profiles.py`, `src/jackryan/server.py`, `src/jackryan/cli.py`,
  `analyst/role.md`
- Migration: one additive step to schema version 7 — a table and three indexes, no column change
- Corpus identity is untouched. Mentions are rows beside the evidence and move no vector, so an
  existing corpus opens unchanged and gains mentions as its documents are reingested.
