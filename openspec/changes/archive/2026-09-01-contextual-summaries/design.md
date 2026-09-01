## Context

See `proposal.md` § Why for motivation. Five properties of the code as it stands shape everything
below, and each was read on `develop` at `6ef8f76`.

**One line decides what is embedded.** `IngestionService._rebuild_chunks`
(`src/jackryan/services/ingestion.py:381`) is `self._embedder.embed_documents([c.text for c in
chunks])`, and it is the only caller of `embed_documents` on the ingest path. Line 382 hands the same
`chunks` to `replace_chunks` with their `text` untouched.

**Corpus identity is composed at the composition root.** `Contract.fingerprint()` covers the five
contract values; `corpus_fingerprint` (`config.py:234`) joins it with the embedder's name in `app.py`,
where both are known. The stated reason is that two copies of one setting can disagree.

**Every contract field must be consumed and must appear in the fingerprint.**
`tests/test_config.py:137-152` asserts that `Contract`'s fields and `DEFAULT_CONTRACT`'s keys have not
drifted apart and that every field appears in `fingerprint()`. Any new `Contract` field therefore
rewrites the fingerprint string for every corpus, whether or not the feature is switched on.

**A real corpus exists.** 435 MB, schema version 5, identity as quoted in the proposal, read from
`store_meta` this session.

**The reranker is the nearest precedent, and is only partly the right one.**
`reranking/port.py` splits a fatal misconfiguration (`check` → `RerankerUnavailable`, a `ConfigError`)
from a transient per-response failure (`score` → `RerankError`, degraded and reported). The first half
transfers exactly. The second half must be inverted, for the reason given below.

## Goals / Non-Goals

**Goals.** A generation seam with one real implementation. Per-chunk contextual summaries folded into
embed input behind a switch that is off by default. Per-document summaries. Corpus identity that
refuses a mixed corpus and admits the existing one unchanged. A fold that is recorded rather than
invisible. A summary that reaches a reader marked as a model's words.

**Non-Goals.** Mentions, NER or the metadata cascade. Any new MCP tool. Measuring whether folding
improves retrieval. Re-recording `docs/retrieval-baseline.json`.

## Decisions

### The summariser's identity is composed into corpus identity, not declared in the contract

`openspec/specs/layered-configuration/spec.md` contains a genuine tension, and resolving it wrongly is
expensive. Lines 56-64 say enrich settings "SHALL live in the contract, together with the identity of
whatever produces that text". Lines 74-82 say the coverage claim is satisfied by entering corpus
identity — "declared in the contract, **or** composed into the identity as the embedder above is".

The resolution is to compose, and the argument is about derived identity rather than about cost.

The summariser's identity is not a value an operator holds. It is the model name joined with a hash of
the prompt text, the document-truncation limit and the sampling parameters — all of which live in
shipped code. An operator cannot know that hash, so a contract field for it would be a value they
copy from a test failure and never read again. Worse, it would be a *second* copy of something the code
already determines, which is precisely the hazard line 36 gives as the reason the embedder is composed
rather than duplicated into the contract: "two copies could disagree". A contract declaring
`summariser: qwen/9a3f1c...` while the shipped prompt says something else is a corpus recording a
recipe it was not built with — the same failure the `embed_library` check exists to prevent, one level
up.

So the rule becomes: a setting able to change a stored vector without changing any stored text SHALL
enter corpus identity, by declaration or by composition, and an identity partly derived from shipped
code SHALL be composed.

**The avoided reingest is a consequence of this, not the reason for it.** Because the `|summariser=`
component is appended only when it is non-empty, an instance with folding off produces a byte-identical
identity string and the 435 MB corpus continues to open. Had the honest answer been a contract field,
the correct action would have been to add it and invalidate that corpus. It is worth stating which way
the argument ran, because the two conclusions are indistinguishable from the outside.

### What is hashed is exactly what determines the embedded text

```
_RECIPE = SUMMARY_PROMPT | document_chars=20000 | max_tokens=200 | temperature=0.0
RECIPE_FINGERPRINT = sha256(_RECIPE)[:12]
name = f"{model_name}/{RECIPE_FINGERPRINT}"
```

Editing the prompt, the truncation limit or the sampling parameters changes corpus identity with nobody
having to remember to bump a version. That is the whole point: a hand-maintained version number is a
second copy of the recipe, and the previous paragraph is about why second copies are the bug.

`DOCUMENT_PROMPT` is deliberately **outside** `_RECIPE`. The per-document summary is stored and never
embedded, so changing it moves no vector and must not refuse a corpus. If a later change ever embeds
the document summary, that prompt has to move inside `_RECIPE` in the same change.

Sampling is pinned at `temperature=0.0` rather than left to the endpoint's default. A default is not
part of the recipe an operator can see, and two endpoints disagreeing on it would produce two corpora
under one identity.

### Thinking is disabled in the request, and that is part of the recipe

The end-to-end check against a real endpoint found this, and it is the reason that check exists rather
than a stub.

The local Qwen3 endpoint used for this check serves a reasoning model. Asked for a chunk context at the recipe's
`max_tokens=200`, it spends the budget on a trace: `reasoning_content` fills, and `content` arrives
either empty or cut mid-word. Measured on one probe: 719 characters of reasoning, `finish_reason:
length`, and a summary truncated at "awarded to three b". Over the `sectioned_corpus` fixture, two
documents out of the set failed outright on an empty context.

The fail-closed policy worked exactly as designed — those two documents failed rather than being
embedded bare — but a feature that fails on random documents against the project's own inference boxes
is not shipped. So the request now carries `chat_template_kwargs: {"enable_thinking": false}`, which
llama.cpp, vLLM and SGLang accept. The same probe then returned a clean 24-token context with
`finish_reason: stop`, and the live ingest went from two failures at 178 seconds to none at 60.

**It is hashed into `_RECIPE`.** Thinking changes what the model produces, which is the stated criterion
for what belongs in the recipe. Left out, a corpus summarised with thinking on and one summarised with
it off would share an identity while holding vectors built from different text — the failure corpus
identity exists to prevent. `RECIPE_FINGERPRINT` moved from `59268425f582` to `7d4b31a0ed4b` as a
result, which costs nothing: no corpus has been built with folding on, and the two-argument identity
string is untouched.

**Raising `max_tokens` was considered and rejected.** It would reduce the frequency of the failure
without removing it — a reasoning model can consume any budget — leaving a fault randomly distributed
across documents, which is worse than a clear refusal. Reading `reasoning_content` as a fallback was
rejected outright: a reasoning trace is not a context, and folding one into an embedding is worse than
failing.

The three endpoint behaviours are all safe, which is what makes sending the key unconditionally
acceptable. An endpoint that honours it produces clean summaries. One that ignores it leaves a
reasoning model thinking, which surfaces as an empty context and fails the document loudly — and the
error names that cause specifically, because the remedy differs and an empty string does not
distinguish it. One that rejects the unknown key fails in `check()`, naming the setting, before any
document is read.

The requirement is only asserted of a real summary, not in `_content`, because `check()` probes with a
one-token budget and an endpoint stopped at one token may legitimately return nothing. Putting the
check in the shared parser would have failed a healthy summariser at startup.

### A summariser failure fails the document, and does not degrade

This inverts the reranker's transient-failure policy, and the inversion is the substance of the
decision rather than an oversight.

A reranker that fails while scoring has cost the caller a better ordering. The fused order is still a
real ranking, the response says it was not reranked, and nothing is stored. Refusing to answer would
make retrieval quality a condition of retrieval.

A summariser that fails while folding is on has a different shape. Falling back to embedding the bare
chunk stores vectors built from one kind of input inside a corpus whose identity asserts the other.
Both are the declared width, both are well-formed, and no later check can separate them — which is the
exact failure corpus identity exists to prevent, arriving through the code rather than the config. One
document silently incomparable with the rest is worse than one document missing, because the missing
one is reported.

So `SummaryError` propagates out of `_rebuild_chunks` and joins the `(ValidationError,
ExtractionError)` tuple at `ingestion.py:351`, giving the document the existing first-class
`status="failed"` outcome carrying the summariser's message. Nothing new is invented for it.

`SummariserUnavailable` subclasses `ConfigError` and is deliberately **not** caught there: a
named-but-unbuildable model is a misconfiguration for the whole run, not a fact about one document.
The ordering is guarded by type rather than by call order — `except ConfigError: raise` placed before
the broader handler, the same shape `services/search.py:343` already uses — so a later reordering of
the `except` clauses cannot silently turn a fatal into a per-document failure.

`summarise_chunks` returning fewer summaries than it was given is a `SummaryError`, never a silent pad.
A padded list would embed some chunks folded and some bare *within one document*, which is the same
corruption at finer grain.

### Three stored columns, and why the producer is one of them

The migration adds `chunks.summary`, `documents.summary` and `documents.summary_by`.

`chunks.summary` records the context that was folded into what was embedded. Without it the fold is
invisible: the stored `text` is the chunk's own text by design, so nothing on disk would say what the
vector was actually built from. It also lets the extended tripwire assert the embedded text against the
store rather than against a recomputation.

`documents.summary_by` records which summariser wrote the document summary, and it is required rather
than decorative. The per-document summary does **not** enter corpus identity — correctly, since it
moves no vector — so nothing else records its producer, and a surface reporting the *currently
configured* summariser as the author of a stored summary would be stating something it does not know.
This is the codebase's own rule, not a new one: `layered-configuration:44-45` says "what the
fingerprint does not guard, the per-document record makes findable", which is exactly why
`documents.text_source` exists.

A per-chunk producer column would be redundant and is not added. `chunks.summary` is non-empty only
when folding was on, and when folding is on the summariser's name is in the corpus identity the store
records and refuses to open without. The store already holds that fact once.

**Neither column enters `chunks_fts`.** `_SIDECAR_TRIGGER` is untouched and
`test_the_fts_trigger_covers_every_fts_column` stays green. Keeping the summary out of the keyword
index is deliberate rather than incidental: a model's words answering a keyword search would return a
document as containing a term that appears nowhere in it, and the agent surface has no way to mark that
distinction inside a ranked list.

`upsert_document`'s `DO UPDATE SET` list gains both columns, overwritten on reingest for the reason
already commented at `sqlite.py:578-581` for `text_source`: the value has to describe the text stored
beside it.

### The document summary is written by a second `upsert_document`, not by reordering the flow

`_ingest_work` persists the document at line 339 and then calls `_rebuild_chunks` at 340. The document
summary is built from the chunk summaries when folding is on and from the chunk texts when it is not,
so it cannot be known before chunking.

Two options: compute chunks before the upsert, or upsert twice. The second is taken. Moving chunking
above the upsert would make `_rebuild_chunks` depend on a document that is not yet stored and would
reorder the extract/persist flow that document identity and reuse-on-reingest depend on. A second
upsert costs one statement per document and keeps `_rebuild_chunks` owning chunking.

### The summary reaches an agent through `case_read_document`, and never through a listing

`provenance()` gains `derived_by: str = ""`, emitted only when non-empty. A reader has to be able to
tell a document's own words from a model's, and `read_as` — which distinguishes a text layer from
recognition — cannot carry that: recognition is a transcription of what is on the page, a summary is
not.

The placement needs stating because the obvious one is wrong. MCP's `_render_document` feeds only
`case_list_documents`, which returns `listing_payload` — whose docstring says it "carries no corpus
prose, so it needs no fence". Putting a summary there would either ship model-written prose through an
unfenced payload or force a fence into a listing built on the promise of not needing one. So the
document summary goes to `case_read_document`, which already fences a document's text and already
carries a provenance block, as a separate fenced `summary` field with its own provenance carrying
`derived_by`. Separate rather than inside the document's own fence, because one fence around both would
lose exactly the distinction `derived_by` exists to make.

`search_payload` and `listing_payload` are unchanged. The chunk summary is an audit artifact — the
context that was folded into a vector — not analytic content, and putting model-written text beside
ranked evidence invites it being quoted as evidence. It is surfaced on the CLI and REST document and
hit shapes, which is where an operator auditing the fold looks.

### `httpx` moves from dev to runtime

One call per chunk means roughly 36,000 requests for the corpus that exists. Without connection pooling
that is 36,000 TCP and TLS handshakes. `httpx` already arrives with a runtime install — `uv.lock` has
both `docling` (line 655) and `huggingface-hub` (line 953) depending on it directly — so promoting it
adds no package to resolve. What it changes is the declaration: this code depends on `httpx` itself
rather than inheriting it from a library that may drop it.

The alternative considered and rejected: `urllib.request` with an explicit timeout and a hand-written
retry, which adds no runtime dependency to a public AGPL tool and costs the pooling. Rejected on the
36,000-handshake figure. Both are not added.

One `httpx.Client` per summariser instance, built in `check()` rather than `__init__` so construction
stays cheap — the same split `CrossEncoderReranker` uses, and the reason `jackryan status` does not pay
for a model it will not use. A document's chunks are summarised through a
`ThreadPoolExecutor(max_workers=profile.summary_concurrency)` and reassembled in input order.

### `chunk_summaries` is validated as a real boolean

`bool("false")` is `True`. A YAML-quoted `"false"` silently enabling folding would produce a corpus
whose vectors are built from summary-prefixed text under an identity that says so — technically
consistent, and not what the operator wrote. `_validated_bool` accepts only a real `bool` and rejects a
string, copying the guard shape `_validated_floor` and `_validated_positive` open with. `true` with an
empty `summary_model` is fatal and names both settings, because it is a request the instance cannot
honour.

## Risks / Trade-offs

**Turning folding on refuses the existing 435 MB corpus.** That is the designed behaviour and the whole
point of the identity component, but it should be said plainly: an operator who sets
`chunk_summaries: true` on the instance holding that corpus will be refused at startup and must reingest
1,760 documents through roughly 36,000 LLM calls. The refusal names both identity strings and how to
proceed, which is existing behaviour. Nothing here makes that cheaper, and pretending otherwise by
admitting a mixed corpus is the failure this change exists to prevent.

**The tripwire now has a conditional branch, which is weaker than an unconditional one.** With folding
off it asserts exactly what it asserts today. With folding on it asserts that every embedded text is
`f"{summary}\n\n{text}"` for the stored chunk. Both vacuity guards are kept. The residual risk is a
future change that folds something in *and* records it in `chunks.summary`, which both branches would
accept — the guard against that is the recipe fingerprint, since any such change alters the recipe and
therefore corpus identity.

**New network egress carrying corpus text.** `llm_url` has existed as a declared setting since M1 and
nothing read it; this is the first code that sends document text off the instance. It is off by
default (`summary_model` empty), the endpoint is operator-named, and the read stack still runs with
zero configured endpoints. It is nonetheless a genuine change in the tool's posture and is recorded as
such in `CLAUDE.md` rather than left to be discovered from the profile settings.

**A summary is model-written text entering the corpus.** It is fenced, marked `derived_by`, and kept
out of the full-text index. What remains is that a document now stores prose no human wrote, and a
future reader of `documents.summary` who ignores `summary_by` will read it as the document's own.
`documents.text_source` has the same shape of risk and the same mitigation.
