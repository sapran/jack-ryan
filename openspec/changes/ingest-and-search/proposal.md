## Why

M0 produced a workbench with no corpus in it. Casefiles exist, but nothing can
be put in one, so nothing can be found. M1 is the milestone that makes the tool
do its job for the first time: documents go in, and good search comes back out,
offline.

It is also the last milestone before the assistant arrives. M2 puts an agent on
top of this retrieval path, so whatever M1 returns is what the assistant will
reason from — which is why search quality, not merely search presence, is the
acceptance bar.

## What Changes

**Current behavior.** A casefile is an empty labelled container. There is no
way to add a document, and nothing to search.

**Desired behavior.** Point the CLI at a file or a folder, and its documents are
extracted, chunked, embedded, and stored. Ask a question and get back passages
ranked by combined keyword and semantic relevance, each resolving to the
document and position it came from.

- Add a **format router**: a registry of extractors selected by sniffing the
  file, each returning a normalised extraction result. Adding a format is
  registering an extractor, not editing the pipeline.
- Adopt **docling** as the default extraction engine, covering PDF, DOCX, PPTX,
  HTML, Markdown, and plain text.
- Add **documents** with content-hash dedup and **identifiers that survive
  reingest**, so references to a document stay valid when it is ingested again.
- Add **chunking** governed by the corpus contract, with character offsets back
  into the extracted text.
- Add an **embedder port** with two implementations: a real ONNX model
  (`multilingual-e5-large`, 1024 dimensions, covering English, Ukrainian, and
  Russian) and a deterministic one used by tests so the suite never downloads a
  model.
- Add **hybrid search**: FTS5 keyword ranking and sqlite-vec nearest-neighbour
  search over the same store, fused by reciprocal rank fusion.
- Extend **CLI and REST** with ingest and search.

Deliberately absent, per the staged plan: OCR, the VLM escalation path,
container and mailbox recursion, spreadsheets, per-chunk summarisation,
reranking, section-window expansion, and mentions. Those are M3.

## Capabilities

### New Capabilities

- `document-ingestion` — the format router, extraction, dedup, and the
  identifier that survives reingest.
- `chunking-and-embedding` — how extracted text becomes retrievable units, and
  the embedder boundary.
- `hybrid-search` — keyword and semantic retrieval fused into one ranking.

### Modified Capabilities

- `storage-seam` — the requirement that text and vectors share one file was
  published narrowed, because no retrieval data existed. This is the capability
  that introduces retrieval data, so it becomes normative here.
- `layered-configuration` — the contract keys change from placeholders to the
  values the pipeline actually consumes.

## Impact

- **New**: `ingestion/` (router, extractors, chunker), `embedding/` (port and
  two implementations), `services/ingestion.py`, `services/search.py`, and their
  tests.
- **Modified**: the store gains documents, chunks, an FTS5 index, and a vector
  table; the CLI and REST adapters gain ingest and search; the contract block
  changes.
- **Dependencies**: `docling`, `fastembed`, `sqlite-vec`.

## Risks

**The image grows by roughly 5GB.** Docling brings a full ML stack. That cost
buys nothing in M1, which has no OCR and no VLM, and everything in M3, which is
what it exists for. Adopting it now was chosen over swapping engines mid-stream.

**The contract changes, so any existing store refuses to open.** That is the M0
guard doing its job rather than a defect. No corpus exists yet, so the remedy is
an empty data directory.

**First ingest downloads the embedding model** (~2.2GB, cached in the data
volume). Steady-state operation is offline, but a first run is not. Baking the
weights into the image is the fix and is proposed for the image build, so a
container is offline from its first run.
