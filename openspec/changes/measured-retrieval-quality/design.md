## Context

See `proposal.md` — Why.

Four facts about the code as it stands shape everything below.

**Fusion produces a bare list of chunk ids, already truncated.**
`SearchService.search` fuses into `scores: dict[str, float]`, sorts, and slices to
`limit` in one expression (`src/jackryan/services/search.py:102-109`) before it
fetches any text at all (`:111`). Each retriever is asked for `depth = limit * 5`
candidates (`:87`), a hard-coded multiplier, not a parameter. A reranker needs
passage text and a deeper pool, so both the slice and the multiplier have to move.

**The full document text is already in memory on every hit.**
`documents.extracted_text` is a real column (`src/jackryan/storage/sqlite.py:76`)
and `search` loads the whole `Document` for each hit's document
(`src/jackryan/services/search.py:119`). A window is therefore a slice of a string
already in hand — no new store method, no second query.

**Chunk ids are not stable, and chunk text is not the document's text.**
Ingestion mints a fresh `uuid4` per chunk on every rebuild
(`src/jackryan/services/ingestion.py:370`) while document ids are deliberately
reused (`:324`). And `chunk.text` is `piece.strip()` while `char_start`/`char_end`
bound the unstripped window (`src/jackryan/ingestion/chunker.py:113`), with chunks
overlapping by `chunk_overlap_chars`. So judgements cannot be pinned to chunk ids,
and a window cannot be assembled by joining chunk texts.

**The reranker is already in the dependency tree.** `fastembed==0.8.0` — pinned
in `pyproject.toml` and locked — contains `fastembed.rerank.cross_encoder.TextCrossEncoder`.
This was established by running the pinned wheel, not by reading documentation:
`rerank(query, documents, batch_size=64)` returns a lazy generator of plain
`float` logits, one per document, in input order. Nothing is added to
`pyproject.toml` or `uv.lock`.

## Goals / Non-Goals

**Goals:**

- A retrieval figure that exists, is reproducible, and can fail.
- Rerank and window expansion built behind that figure, so each can be shown to
  help rather than assumed to.
- Per-leg attribution — keyword, vector, fused — so a later gain is explicable.
- No corpus invalidated, no reingest, no schema change, no new dependency.
- A default configuration that is offline, permissively licensed, and unchanged
  in behaviour except for windows.

**Non-Goals:**

- A quality claim about real case material. The shipped set is synthetic; it
  detects regression and demonstrates direction, and the spec requires every
  figure to name what produced it.
- Choosing the project's recommended reranker model. That is what the harness is
  for, and this change deliberately ships without naming one.
- A CI gate. The measurement needs model weights; CI cannot download them, which
  is why `scripts/verify_model_paths.py` exists in the shape it does.
- Tuning `RRF_K`, the chunker, or the embedding model. Any of those may follow
  from what the harness reports; none is in this slice.
- Summaries and mentions, the remaining M3 legs.

## Decisions

### The harness is a script beside `verify_model_paths.py`, not a pytest gate

`scripts/evaluate_retrieval.py`, following that file's conventions exactly: a
docstring whose first line is the parser description, function-local `jackryan`
imports so an unselected check costs nothing, a `record`-style reporter that
prints the measured quantity rather than "ok", a `tempfile.mkdtemp` workspace
removed unless `--keep`, and `raise SystemExit(main())`.

*Why:* the suite is required to run offline and every test uses the deterministic
embedder. A measurement that must download `intfloat/multilingual-e5-large`
cannot live in `pytest -q`.

*Why not extend `verify_model_paths.py`:* its registry is built for pass/fail
claims with a one-line detail. A metric table is a different artefact, and mixing
them would make `--only retrieval` report through a reporter shaped for booleans.

### The baseline is a tracked file, and an ordinary run cannot rewrite it

The harness writes its figures as JSON and compares them against a committed
baseline. Below baseline it exits non-zero and names each metric that fell and by
how much. `--record` is the only way to move the baseline.

*Why:* retrieval degrades silently — ten results still come back, and they are
still plausible. This is the only failure in the project with no symptom at all.

*Why not a hand-chosen threshold:* the recognition gate could pick `0.75` because
the measured gap was 0.85 against 0.11. Here there is no gap to read a number
from, so the previous measurement is the only defensible bar.

*Cost:* the tracked baseline is machine- and model-dependent; a different host may
produce different figures. The file records the conditions, and a mismatch is a
prompt to re-record deliberately rather than a silent pass.

### A tied fused score is broken by position, not by identifier

*Added during implementation, not designed up front.* The first measurement was
not reproducible: reingesting the same corpus moved one query's answer from rank
3 to rank 2 and shifted fused MRR by 0.014. Exact ties are ordinary in
reciprocal rank fusion — a chunk ranked first by one retriever and second by the
other scores exactly what a chunk ranked second and first scores — and they were
being broken by `chunk_id`, which is a fresh `uuid4` after every reingest.

*Consequence:* the candidate chunks are now fetched before the ordering rather
than after it, so the sort can fall back to properties of the corpus. Phase 3
needs those texts in hand at the same point anyway, to score them.

*Corrected once during implementation:* falling back to the document and the
ordinal fixed a reingest and not a rebuild — a document's id is fresh in a store
built from scratch, so two runs of the harness still disagreed. The order is
settled by the ordinal and the passage text, and by the chunk id only where two
passages are identical in both, which is the one case where the order does not
matter.

*Why it is not a drive-by:* a measurement that cannot be reproduced cannot
detect a regression, and the baseline gate would report failures that are noise.
It is a precondition of the phase, and `retrieval-evaluation` already requires
the figures to be the same across a rebuild.

### Judgements are keyed to a document and a substring, never to a chunk id

Each query records the filename of the document that answers it and a short quoted
phrase from the answering passage. A hit counts as relevant when it is that
document and its returned span contains that phrase.

*Why:* chunk ids are minted fresh on every reingest. A judgement pinned to one
measures nothing on the second run — which is precisely when a measurement matters.

*Why not document-level only:* the window and rerank legs are both about which
part of a document is returned, and a document-level judgement is blind to them.

### The shipped query set is synthetic, trilingual, and written at run time

Invented material in the existing register — the fictional harbour lease — written
into the temp workspace by the script, with distractor documents that answer
nothing, and queries in English, Ukrainian and Russian. `--corpus` and
`--queries` let an operator measure their own material instead.

*Why:* the repository is public and permanent; `CLAUDE.md` forbids real case
material, and the precedent for a verification corpus is that it was written for
the test and never committed.

*Accepted weakness:* a synthetic set of this size measures the retrieval mechanism
and the direction of a change. It is not evidence about a real dump, and the spec
requires the figure to say so.

### Reranking is a profile setting that ships with no model named

Three new profile keys: `reranker_model` (empty, meaning off), `rerank_depth`
(50), `window_max_chars`. None enters the contract or corpus identity.

*Why off by default:* fastembed 0.8.0 registers six rerankers and exactly one is
multilingual — `jinaai/jina-reranker-v2-base-multilingual`, licensed
**CC-BY-NC-4.0**. This corpus is English, Ukrainian and Russian, so the
English-only models are not an answer, and a non-commercial licence does not sit
comfortably in an AGPL-3.0 repository that ships a container image. Shipping the
seam with no model named keeps the default build permissively licensed and lets an
operator name what suits their own use.

*Alternative rejected — default to the Jina model:* it would bake a non-commercial
weight into the shipped image and make the licence question everyone's rather than
the operator's.

*Alternative recorded, not taken:* `BAAI/bge-reranker-v2-m3` is Apache-2.0 and
genuinely multilingual, reachable through `TextCrossEncoder.add_custom_model`. Two
traps make it a decision for after measurement, not before: the ONNX export commonly
used holds its weights in a separate `model.onnx_data` file that must be named in
`additional_files` or the session fails to build, and that export repository
declares no licence of its own even though its upstream is Apache-2.0.

*Why not corpus identity:* a reranker writes nothing. No vector, no chunk, no
stored text — it reorders at query time. `embedder` is in corpus identity because
its output is stored and later compared against; there is nothing here to compare.

### A reranker that cannot be built is fatal; one that fails while scoring degrades

Constructing the reranker is attempted when it is first needed. Failure there
raises, naming the setting. Failure while scoring one response is logged, the
fused ordering stands, and the response reports that it was not reranked.

*Why the split:* `docs/handover.md:267` requires rerank to "degrade to unranked
`top_k` rather than blocking — never a hard dependency", while this codebase's
loudest rule is that a model which cannot load must stop rather than silently
produce worse output. Both survive if the two failures are separated:
misconfiguration is loud, transient fault is survivable. A fail-open path on the
first is exactly how a feature becomes inert without anyone noticing.

*Why not at load:* only the implementation can answer whether a model name is
usable, and answering costs seconds and possibly a download. `jackryan status`
should not pay that — the same reasoning that puts the recognition-engine check at
the start of an ingest run rather than at process start.

### The reranker scores the matched chunk, and windows are computed afterwards

Pipeline order: retrieve at depth → fuse → rerank the top `rerank_depth`
candidates on their chunk text → truncate to `limit` → expand the survivors into
windows → apply the response character budget.

*Why chunk text, not the window:* fastembed's cross-encoder truncates the
query-and-passage pair at the model's own `model_max_length` with no per-call
override. Handing it a widened window means a silent cut inside the library, and
the score would then describe a fragment nobody chose. A chunk is already bounded
by `chunk_max_chars`.

*Cost:* expansion runs only on results that survive, which is also the cheaper
order.

### The fusion score stays, and the rerank score is a second value

`SearchHit` gains `rerank_score: float | None` beside `score`, which keeps meaning
the RRF sum. The response says which stage ordered it.

*Why:* it keeps `hybrid-search`'s "scores are never blended" literally true, makes
degradation observable to the caller rather than invisible, and preserves the
existing REST, CLI and MCP renderings of `score`.

*Why it must be labelled:* the value is an unbounded logit — measured at `+6.04`
and `−11.45` on a two-document probe. It is not a probability and is not
comparable between queries. Shown unqualified beside a fusion score it reads as
confidence.

### A window is one slice of `extracted_text`, bounded by a budget and by headings

The window starts from the matched chunk's `char_start`/`char_end` and grows
outward over `document.extracted_text` until it hits `window_max_chars`, a heading
boundary where the document has headings, or the document's edge.

*Why a slice, not joined chunks:* chunks overlap by `chunk_overlap_chars`, so
joining them repeats text, and each chunk's stored text is stripped while its
offsets are not. The slice is exactly what a human would read at those offsets —
which is what makes the citation checkable by hand.

*Accepted weakness:* `heading_path` is derived from Markdown headings only
(`src/jackryan/ingestion/chunker.py:36-58`), so it is empty for every scanned and
plain-text document. There the budget alone bounds the window. This is a known
limit, not a hidden one, and the harness measures both cases.

### The matched chunk stays the citable unit, and windows never overlap in one response

Identifiers, `case_get_passage` and `case_cite` continue to address the chunk, and
a citation's span stays the chunk's span. Within one response, a result whose
window would overlap one already returned is narrowed until it does not.

*Why:* the chain search → passage → cite is a contract that saved prompts and the
analyst pack depend on, and `mcp-tool-surface` requires a passage body to appear
exactly once per payload. Overlapping windows would break the second and would let
one passage be counted twice as evidence.

### `case_get_passage` moves behind the same window rule

Today the MCP adapter calls `context.store.get_document_chunks_around` directly
with a hard-coded radius of one (`src/jackryan/interfaces/mcp/server.py:263-268`)
and returns neighbours the response's own provenance does not describe.

*Why in scope:* it is the same rule this change is defining, and it is the one
retrieval rule currently living in an adapter — the second definition of a domain
rule that `service-adapter-boundary` exists to prevent. Leaving it would ship two
different answers to "what surrounds this passage".

## Risks / Trade-offs

**A reranker may make results worse, particularly on Ukrainian and Russian, and
nobody would notice.** → It ships off; the harness measures per language before
any model is recommended; the response says whether it reranked.

**Windows multiply the text an agent pays for — worst case was `limit ×
chunk_max_chars` and is now wider.** → A response-level character budget, new in
this change, plus non-overlapping windows; both are specified, not incidental.

**A synthetic set can be gamed by construction: write the queries after seeing
what the retriever finds and every figure is 1.0.** → Distractor documents,
queries that share no content words with their answers, and the deterministic
embedder run as a control that must produce different figures — the analogue of
the forced-`en` recognition run that makes the real one able to fail.

**A tracked baseline invites being re-recorded whenever it is inconvenient.** →
`--record` is explicit, the baseline file carries its conditions, and the numbers
are quoted in `docs/handover.md` where a change of them is visible in review.

**`SearchHit` gains fields that three renderers publish at three roundings.** →
The additions are additive and defaulted; existing fields keep their meaning; the
`formatted`-line-count invariant asserted at `tests/test_regressions_m2.py:80-83`
stays one line per result.

**The reranker downloads weights on first use, mid-query.** → Only when a model is
named; the cache path is the one `JACKRYAN_MODEL_CACHE` already governs; the
Dockerfile prefetch gains a line for operators who name one.

## Migration Plan

No migration. No schema change, so no rung in `_STEPS`. No contract value changes,
so corpus identity is unchanged and every existing store opens exactly as before —
verified by the identity scenario in the `layered-configuration` delta.

The three new profile keys default to a configuration equivalent to today's
behaviour apart from windows: no reranker, and a window budget that an operator can
set to a chunk's width to switch expansion off entirely.

## Open Questions

None that change the specs, the approach or the tasks.

One decision was deliberately left to the measurement rather than to this
document: which reranker model, if any, this project should recommend. **The
measurement answered it: none of the ones available.** Both cross-encoders the
embedding library registers were run against the harness, and both made retrieval
worse — `Xenova/ms-marco-MiniLM-L-6-v2` took fused recall@1 from 0.882 to 0.176,
`jinaai/jina-reranker-v2-base-multilingual` to 0.529, and both took Ukrainian to
0.000, because for a Ukrainian query the cross-encoder ranks English passages
above the Ukrainian one that answers it. The wiring was verified before that
conclusion was drawn. So the licence question recorded under Decisions is moot
for now: the model that would have raised it does not earn its place.

The figures, their conditions and their limits are in `docs/handover.md`.
Anything else found while building went to `docs/implementation-notes.md`.
