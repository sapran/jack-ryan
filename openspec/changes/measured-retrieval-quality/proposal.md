## Why

**Retrieval quality has never been measured.** `docs/handover.md` says so in three
places and names it the single largest unaddressed gap in the project. The
suite's ranking tests are three binary assertions on `hits[0].document.filename`
(`tests/test_search.py:24-48`); there is no recall figure, no reciprocal rank, no
per-leg attribution, and no baseline of any kind — a grep for `recall@`, `MRR`,
`ndcg` or `benchmark` across `src`, `tests`, `scripts` and `docs` returns nothing
but prose.

That is why this slice leads with measurement. The two remaining retrieval legs
of **M3** are cross-encoder rerank and section-window expansion, and rerank's
entire purpose is retrieval quality. Shipped without a baseline it can be run,
tested green, and still be silently making results worse — the exact failure this
repository keeps recording against itself: a check that proves the code executed,
not that it worked. A number measured before the change is the only thing that
can tell the difference afterwards.

**This pulls nothing forward.** `docs/design.md` § 10 defers "Retrieval quality —
cross-encoder rerank and section-window expansion" to M3, and M3 is where we are.
The prototype has shipped, hard formats shipped in slice 1, and the extraction
quality gate shipped in slice 2.

## What Changes

- **A retrieval evaluation harness**, `scripts/evaluate_retrieval.py`, in the
  shape of `scripts/verify_model_paths.py`: it builds a synthetic corpus in a
  temporary workspace, runs a fixed query set through `SearchService`, and reports
  recall@1/@5/@10 and MRR@10. It reports the two retrieval legs separately
  (keyword-only, vector-only) beside the fused figure, so a later gain can be
  attributed rather than assumed. It runs under the real embedder by default and
  under the deterministic stand-in as a negative control, proving the measurement
  can move.
- **A tracked baseline.** The harness writes a machine-readable result and
  compares against a committed baseline file, exiting non-zero when a metric falls
  below it. Before this change there is nothing to regress against; after it,
  every retrieval change has a number to beat.
- **Cross-encoder rerank** as a stage after fusion. `fastembed==0.8.0` — already
  pinned, already in `uv.lock` — ships `fastembed.rerank.cross_encoder.TextCrossEncoder`;
  this was confirmed by running the pinned wheel, not read from documentation, and
  it adds **no new dependency**. The reranker is a profile setting and **ships
  disabled**: no reranker model is named by default and no weights are added to
  the image. See `design.md` for why — the only multilingual reranker in
  fastembed's registry is CC-BY-NC-4.0, which does not sit comfortably in an
  AGPL-3.0 repository, and this corpus is English, Ukrainian and Russian.
- **A named reranker that cannot be built is fatal; a reranker that fails while
  scoring degrades to the fused order and says so in the response.** That splits
  the difference between `docs/handover.md:267` ("must degrade … never a hard
  dependency") and this codebase's loudest rule, that a model which cannot load
  must stop rather than silently produce worse output.
- **Section-window expansion.** A hit's returned text becomes a coherent window
  around the matched chunk, sliced from `documents.extracted_text` — which is
  already in memory for every hit (`src/jackryan/services/search.py:119`) — bounded
  by a character budget and by heading agreement where headings exist. The matched
  chunk keeps its identity: it remains the thing `case_get_passage` and `case_cite`
  address, and the citable span is still the chunk's.
- **The window rule moves behind the service layer.** `case_get_passage` today
  calls `context.store.get_document_chunks_around` directly from the MCP adapter
  with a hard-coded radius of one (`src/jackryan/interfaces/mcp/server.py:263-268`),
  and returns neighbours whose text the response's own provenance does not cover.
  It will use the same service-layer window rule, and its provenance will describe
  what it actually returned.
- **A response-level character budget.** There is none today on any surface: the
  worst case is `limit × chunk_max_chars`, and widening each result multiplies it.
- **New profile keys**: `reranker_model` (empty = off), `rerank_depth`,
  `window_max_chars`. All in `profiles`, none in `contract`.

**Not breaking, and no reingest.** Corpus identity is untouched — a reranker
writes nothing and a window is computed at read time from text already stored. No
schema change, no migration rung, no new dependency. Search payloads gain fields
and a result's `text` may be wider than its chunk; both are described in the spec
deltas below.

## Capabilities

### New Capabilities
- `retrieval-evaluation`: what it means to measure retrieval in this project — a
  fixed query set with recorded judgements, named metrics, synthetic material
  only, measurement through the service layer rather than around it, and the rule
  that a retrieval-quality claim names what was measured and on what.

### Modified Capabilities
- `hybrid-search`: fusion's guarantees are re-scoped to the fused candidate
  ordering, with rerank named as a later stage that may reorder it; the "agreement
  outranks a single retriever" scenario becomes a property of that ordering. A
  result's returned text may be a window wider than the matched chunk, which
  changes what "a result carries what is needed to use and to verify it" asserts.
  Rerank depth, the degradation rule and the response character budget are added.
- `layered-configuration`: records that reranking and window expansion live in
  `profiles` and not in `contract`, and why that is safe — neither produces a
  stored artefact, so neither can invalidate a corpus.
- `mcp-tool-surface`: a result's body is the window rather than the chunk, so the
  payload must name both spans; "a passage body appears exactly once" must survive
  two hits landing in one section.
- `untrusted-content-boundary`: provenance names the span actually returned and
  the matched chunk within it, rather than a chunk span that no longer describes
  the body.

## Impact

- `src/jackryan/services/search.py` — the rerank stage and the window rule; the
  candidate slice moves after rerank.
- `src/jackryan/storage/port.py` — `SearchHit` gains the returned span, the
  matched chunk's span and a rerank score; `score` keeps meaning the fusion score.
- `src/jackryan/reranking/` — new: the reranker port, the fastembed
  implementation, and `build_reranker`, mirroring `src/jackryan/embedding/`.
- `src/jackryan/app.py` — wires the reranker into `SearchService`.
- `src/jackryan/config.py` — three profile keys, validated the way `ocr_engine`
  and `embedder` already are.
- `src/jackryan/interfaces/mcp/server.py`, `shapes.py`, `fencing.py` — the new
  spans in the payload and in provenance; `case_get_passage` through the service.
- `src/jackryan/server.py`, `cli.py` — the same fields, and `read_as` on a search
  hit, which REST and the CLI omit today while the agent surface carries it.
- `scripts/evaluate_retrieval.py`, and a tracked baseline file — new.
- `Dockerfile` — the prefetch path gains a reranker line, used only when a model
  is named.
- **No change to `pyproject.toml` or `uv.lock`.**
