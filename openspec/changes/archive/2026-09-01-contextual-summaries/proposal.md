## Why

`docs/handover.md` § *What is left in M3* names the summarization layer as one of the two remaining
legs: per-chunk contextual summaries folded into what is embedded, then a per-document map-reduce
summary. The previous change (`2026-09-01-embed-input-is-corpus-coupled`) built the guard for it and
deliberately built nothing else — a rule in `layered-configuration`, a tripwire in
`tests/test_embedding.py`, and a corpus check in the retrieval harness. This change is the feature that
guard was built for.

Three things are absent today and each is load-bearing:

1. **There is no generation seam at all.** `llm_url`, `embed_url` and `api_key` are declared at
   `config.py:116-118` and read at `config.py:498-500`, and nothing consumes any of them. There is no
   LLM client, no HTTP client on the runtime path, and no port for text generation anywhere in `src/`.
   `httpx` is a dev-only dependency.
2. **`_rebuild_chunks` embeds the chunk's own text**, which is correct and is what the tripwire
   asserts. Turning that into "the chunk's text, optionally preceded by a summary" is the change the
   tripwire exists to force into the open, and the tripwire has to be extended rather than deleted.
3. **A real corpus now exists.** `data/jackryan.db` is 435 MB holding 1,760 documents and 36,305
   chunks across two casefiles, recorded under
   `chunk_max_chars=2000|chunk_overlap_chars=200|embed_model=intfloat/multilingual-e5-large|embed_dimensions=1024|embed_library=fastembed==0.8.0|embedder=model`.
   `docs/handover.md:263-266` justified the two previous deliberate fingerprint invalidations with "no
   corpus outside development exists". That is no longer true, and it changes what a correct
   implementation looks like.

## What Changes

**Current behaviour.** Ingestion chunks a document's extracted text and hands each chunk's own text to
the embedder. Nothing summarises anything. A document stores the text recovered from it and nothing
derived from that text. `corpus_fingerprint` is the contract's fingerprint joined with the embedder's
name.

**Desired behaviour.**

- **A summariser port** with three operations — `check`, `summarise_chunks`, `summarise_document` —
  and one implementation against an OpenAI-compatible chat-completions endpoint. Absent unless the
  profile names a model, exactly as the reranker is.
- **The per-chunk summary is folded into what is embedded** when `chunk_summaries` is on. The chunk's
  stored `text` is unchanged; only what the embedder is given changes. That asymmetry is the reason
  the setting is corpus-coupled.
- **The summariser's identity enters corpus identity by composition, not by declaration.** Its name is
  the model plus a hash of the prompt, the document-truncation limit and the sampling parameters —
  values that live in shipped code, which an operator cannot know and must not be asked to declare.
  With folding off the identity string is byte-identical to today's, so the existing corpus still
  opens. With folding on it gains a `|summariser=` component and the existing corpus is refused,
  which is the correct refusal.
- **A summariser failure fails the document.** It never degrades to an unsummarised embed. This is a
  deliberate departure from the reranker's precedent: a reranker only reorders, so serving the fused
  order is honest, whereas a document embedded bare inside a folded corpus is silently incomparable
  with every other document and nothing downstream can detect it.
- **The fold is recorded.** A chunk stores the context that was folded into what was embedded, and a
  document stores its summary and which summariser wrote it. Neither enters the full-text index:
  model-written words must not answer a keyword search as though a document contained them.
- **A summary is fenced as untrusted, and marked as derived.** A model's summary of untrusted text is
  untrusted text, and a reader must be able to tell a document's own words from a model's.
- **A per-document summary alone moves no vector**, so it leaves corpus identity untouched and can be
  turned on over an existing corpus.

**Deliberately not in scope.** No new MCP tool. No contract field. No mentions, NER or metadata
cascade — those are the next change. No measurement of whether folding improves retrieval: that needs
a summarised corpus and a re-recorded baseline, and is a reported measurement after this merges rather
than a claim made inside it.

## Impact

- Affected specs: `layered-configuration` (MODIFIED), `chunking-and-embedding` (RENAMED + MODIFIED +
  ADDED), `storage-seam` (ADDED), `untrusted-content-boundary` (ADDED)
- New code: `src/jackryan/summarising/` (`port.py`, `model.py`, `__init__.py`)
- Affected code: `src/jackryan/config.py`, `src/jackryan/app.py`,
  `src/jackryan/services/ingestion.py`, `src/jackryan/storage/port.py`,
  `src/jackryan/storage/sqlite.py`, `src/jackryan/interfaces/mcp/fencing.py`,
  `src/jackryan/interfaces/mcp/server.py`, `src/jackryan/server.py`, `src/jackryan/cli.py`
- Affected dependencies: `httpx` moves from dev to runtime in `pyproject.toml`
- Affected prose: `CLAUDE.md`, `docs/design.md`, `docs/handover.md`, `config.yaml.example`
- Migration: one additive step to schema version 6. The existing corpus is carried forward and still
  opens, because with folding off its recorded corpus identity is unchanged.
