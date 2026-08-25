## Context

M1 turns an empty workbench into one holding a searchable corpus. The shape was
settled in `docs/design.md`; this records the decisions taken while building it,
and the two places where the environment forced something to be recorded rather
than proven.

## Decisions

### Docling is the default engine, adopted now rather than swapped in later

Docling covers every M1 format and is what M3's OCR and VLM paths extend. The
alternative — light per-format libraries now, docling at M3 — would have cost
51MB instead of 5.2GB and produced identical output for born-digital files,
since docling's weight is precisely the machinery M1 does not use.

Adopting it now was chosen deliberately: the extraction path is the real one
from the first document, so no assumption formed against a lighter engine has to
be unwound at M3, and there is no migration of already-ingested text.

### Extraction is registered, not branched

`Extractor` implementations declare what they can take and are consulted in
order. The router owns selection; no extractor knows about another. Adding
spreadsheets or mailboxes at M3 is a registration, and the escalation ladder
docling needs for OCR fits inside one extractor rather than across the router.

### The embedder is a port, with a deterministic implementation for tests

Two implementations: the real ONNX model, and a deterministic one that derives
vectors from hashed token counts. The deterministic one exists so the suite
never downloads a model — a test that pulls 2.2GB is a test nobody runs, and CI
would pay it on every push.

It is a genuine embedder rather than a stub: identical text yields identical
vectors and shared vocabulary yields higher similarity, so fusion and ranking
are exercised for real. It is not semantically meaningful, and it is never the
default outside tests.

### `passage:` and `query:` prefixes are the embedder's business

The e5 family expects asymmetric prefixes, and omitting them measurably degrades
retrieval. The port exposes `embed_documents` and `embed_query` as separate
operations so the prefix is applied where the model is known, and no caller has
to remember. An embedder that needs no prefixes simply ignores the distinction.

### One integer key ties chunk text to its vector

A chunk's `rowid` is the FTS5 `content_rowid` and the vector table's key. Both
indexes address the same row in the same file, in one transaction, so a chunk
whose text exists without its vector is not a state the store can reach.

### Fusion is reciprocal rank fusion, not score blending

Keyword scores and vector distances are not comparable, and normalising them
introduces a tuning parameter that has to be maintained per corpus. RRF consumes
only rank, so it needs no calibration and cannot be skewed by one retriever's
score distribution. A chunk found by both retrievers outranks one found by
either alone, which is the property that matters.

## Risks / Trade-offs

- **5.2GB of dependencies for capability M1 does not exercise.** Accepted with
  eyes open; see above.
- **The deterministic embedder could be mistaken for the real one.** It is
  selected only by explicit configuration and is never a fallback: if the real
  model cannot load, ingestion fails loudly rather than silently producing
  vectors that mean nothing.
- **Contract change invalidates any existing store.** Correct behaviour of the
  M0 guard. No corpus exists.

## What could not be verified here, and why

The build environment blocks Hugging Face, so two paths are implemented and
tested by unit tests but never executed end to end:

- **PDF extraction.** Docling parses Markdown, HTML, DOCX, and PPTX with no
  network — all four are verified. PDF needs layout models fetched on first use,
  which the environment refuses.
- **The real embedder.** `multilingual-e5-large` downloads on first use.

Both are recorded as unchecked tasks rather than claimed. The image build
pre-fetches both sets of weights, which is also what makes a container offline
from its first run; that build runs where the network allows it.

## Migration Plan

Delete the data directory. The contract changed, so an M0 store will refuse to
open, and it holds nothing worth keeping.

## Open Questions

- Whether chunk boundaries should follow tokens rather than characters. M1 uses
  characters because it needs no tokenizer and is exactly reproducible; the
  contract records the unit, so changing it later is a contract change with a
  forced reingest, which is the intended mechanism.
