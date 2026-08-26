## 1. Contract and configuration

- [x] 1.1 Replace the placeholder contract keys with the ones the pipeline consumes: `chunk_max_chars`, `chunk_overlap_chars`, `embed_model`, `embed_dimensions`.
- [x] 1.2 Keep an unknown contract key fatal, and confirm the fingerprint changes.
- [x] 1.3 Add an `embedder` profile setting selecting the real or deterministic implementation.
- [x] 1.4 Update `config.yaml.example` to the new keys.

## 2. Store schema

- [x] 2.1 Add `documents`: casefile scope, content hash, filename, media type, byte size, extracted text, status, timestamps.
- [x] 2.2 Add `chunks` with an integer rowid, ordinal, heading path, text, and character offsets.
- [x] 2.3 Add an FTS5 index over chunk text, keyed by chunk rowid.
- [x] 2.4 Add a sqlite-vec table sized from the contract's dimensions, keyed by the same rowid.
- [x] 2.5 Load the sqlite-vec extension on every connection.
- [x] 2.6 Bump the schema version, and keep the contract guard working across the change.
- [x] 2.7 Delete a casefile's documents, chunks, and vectors with the casefile.

## 3. Format router and extraction

- [x] 3.1 Define `Extractor` — what it accepts, and a normalised result carrying text, structure, and native metadata.
- [x] 3.2 Implement the router: sniff by extension and content, consult extractors in order, fail with a typed error when none accepts.
- [x] 3.3 Implement the docling extractor for PDF, DOCX, PPTX, HTML, and Markdown.
- [x] 3.4 Implement a plain-text extractor that needs no engine.
- [x] 3.5 Refuse a file that produces no usable text, rather than storing an empty document.
- [x] 3.6 Bound file size, and refuse symlinks and paths outside the ingest root.

## 4. Documents, dedup, and stable identifiers

- [x] 4.1 Hash file bytes; treat the hash as the document's identity within a casefile.
- [x] 4.2 Reingesting identical bytes reuses the existing document's identifier and rebuilds its chunks.
- [x] 4.3 The same bytes in two casefiles are two documents, because casefiles are compartments.
- [x] 4.4 Record extraction failures against the document rather than losing them silently.

## 5. Chunking and embedding

- [x] 5.1 Chunk on the contract's size and overlap, preferring paragraph boundaries.
- [x] 5.2 Record each chunk's character offsets so a passage can be located in the source text.
- [x] 5.3 Define the embedder port with separate document and query operations.
- [x] 5.4 Implement the real ONNX embedder, loading the model lazily.
- [x] 5.5 Implement the deterministic embedder used by tests.
- [x] 5.6 Fail loudly when the configured embedder cannot load — never fall back.
- [x] 5.7 Refuse an embedding whose width disagrees with the contract.

## 6. Hybrid search

- [x] 6.1 Keyword search over FTS5, ranked, with query text treated as terms rather than operators.
- [x] 6.2 Semantic search over the vector table using the embedded query.
- [x] 6.3 Fuse both by reciprocal rank fusion.
- [x] 6.4 Scope every search to one casefile.
- [x] 6.5 Return each hit with its text, its document, its offsets, and identifiers for follow-up.
- [x] 6.6 Bound result counts.

## 7. Adapters

- [x] 7.1 CLI: `ingest` accepting a file or a folder, reporting per-document outcomes.
- [x] 7.2 CLI: `search`, with `--json`.
- [x] 7.3 CLI: `document list` and `document show`.
- [x] 7.4 REST: ingest, list documents, and search.
- [x] 7.5 Keep both adapters free of domain rules.

## 8. Packaging

- [x] 8.1 Add `docling`, `fastembed`, and `sqlite-vec` as dependencies.
- [x] 8.2 Pre-fetch extraction and embedding weights in the image build, so a container is offline from its first run.
- [x] 8.3 Confirm CI still passes without any model download.

## 9. Verification

- [x] 9.1 Whole suite green.
- [x] 9.2 Extraction verified for Markdown, HTML, DOCX, and PPTX.
- [x] 9.3 End-to-end: ingest a folder, search it, and get ranked passages that resolve to their source.
- [x] 9.4 Dedup verified: reingesting the same bytes keeps the identifier.
- [x] 9.5 PDF extraction exercised on a machine with model access — done 2026-08-26 by `scripts/verify_model_paths.py`; see `docs/handover.md`.
- [x] 9.6 The real embedder exercised on a machine with model access — done 2026-08-26 by `scripts/verify_model_paths.py`; see `docs/handover.md`.

## 10. Adversarial review

- [x] 10.1 Review the implementation across correctness, storage integrity, security, spec conformance, and adapter behaviour.
- [x] 10.2 Refutation-test every finding; keep only what reproduces.
- [x] 10.3 Fix all twelve confirmed defects.
- [x] 10.4 Add a regression test per defect, each failing against the original code.
- [x] 10.5 Re-verify the whole suite and the end-to-end path.
