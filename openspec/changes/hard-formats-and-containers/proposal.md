## Why

A real dump is not a folder of PDFs. It is a ZIP holding a mailbox holding
attachments, and the evidence an analyst needs is usually three levels down. The
prototype ingests only what arrives as a single born-digital file, so today that
dump ingests as one unreadable archive or fails outright — the material the case
turns on never reaches the corpus at all.

This is the first slice of **M3**. It pulls nothing forward: containers, the
hard formats, and document hierarchy were all deferred behind the prototype
(design.md § 10), and the prototype has shipped.

## What Changes

**Current behaviour.** An extractor takes one file and returns one flat block of
text. A document's identity is the hash of the bytes on disk. Nothing in the
model expresses that one document came out of another, and a citation names a
document with no way to say where that document was found.

**Desired behaviour.** An extractor may return child documents as well as text.
A container is ingested by recursing into it through the same pipeline, so a
format is supported inside an archive exactly when it is supported outside one.
Every document knows its parent, and a citation names the path an analyst would
follow to find it by hand.

- **Container extractors** for ZIP and TAR archives, and for directory trees,
  emitting their entries as child documents through the same router.
- **Mail extractors** for EML, MBOX, and MSG. A message is a document; its
  attachments are its children, recursed through the same pipeline.
- **Spreadsheet extractors** for XLSX and CSV/TSV, with each sheet rendered as
  text an embedder and a reader can both use.
- **Document hierarchy** — a document may carry a parent, ancestry is queryable,
  and a child is scoped to the same casefile as its container.
- **Recursion guards** — bounds on depth, on child count, and on total bytes
  produced, so a crafted archive exhausts a budget and is refused rather than
  exhausting the disk.
- **BREAKING (storage)**: documents gain a parent column, so the schema version
  advances and an existing corpus is not readable by the new store. No corpus
  outside development exists yet; the contract fingerprint already refuses a
  mismatched store rather than corrupting it.

**Not in this slice.** OCR and the VLM escalation, cross-encoder rerank,
summaries, and statistical NER are the model-dependent legs of M3 and follow
separately. PST stays last, as the plan has it. This slice needs no model and no
endpoint, which is why it is first.

## Capabilities

### New Capabilities

- `container-extraction`: how a file that holds other files is expanded — the
  recursion through one router, and the depth, count, and expansion budgets that
  bound it.
- `document-hierarchy`: what a parent–child relationship means to the rest of
  the system — ancestry, casefile scoping, listing, deletion, and the path a
  citation reports.

### Modified Capabilities

- `document-ingestion`: an extractor may return child documents, not only text;
  and a child's identity is derived from its own extracted bytes rather than
  from a file on disk, since it has none.
- `untrusted-content-boundary`: the provenance accompanying corpus text names
  the containment path, so a passage from an attachment inside an archive
  resolves to somewhere an analyst can actually look.

## Impact

- `src/jackryan/ingestion/extractors.py` — the `Extraction` result grows child
  documents; new mail, spreadsheet, and archive extractors join the registry.
- `src/jackryan/ingestion/router.py` — unchanged in shape; selection still owns
  which extractor runs.
- `src/jackryan/services/ingestion.py` — recursion, the guard budget, and child
  identity.
- `src/jackryan/storage/sqlite.py`, `storage/port.py` — a parent column, ancestry
  queries, and cascading deletion; schema version advances.
- `src/jackryan/interfaces/mcp/` — citation and provenance carry the containment
  path.
- Dependencies: `openpyxl` for XLSX and `extract-msg` for MSG. EML, MBOX, ZIP,
  TAR, and CSV are standard library.
