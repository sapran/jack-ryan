# Handover

Written for the next Claude Code session, on a machine that has the
infrastructure this project was built without. Updated 2026-08-26, on such a
machine: the model-dependent paths have now been run, and this records what
that did and did not settle.

Read `CLAUDE.md` first for the rules and pitfalls, and `docs/design.md` for the
staged plan. This document covers only what those two cannot know: what is
verified, what is not, and why.

---

## Where things stand

`main` is at the merge of M3 slice 2 plus a deadline-driven cleanup, and
`measured-retrieval-quality` is built on top of it. The prototype (M0–M2), both
earlier M3 slices and `corpus-identity-and-schema-migration` are archived,
sixteen capabilities are published in `openspec/specs/`, and 475 tests pass with
2 skipped behind `JACKRYAN_MODEL_TESTS=1`.

Built and merged, and — since 2026-08-26 — exercised against real model
infrastructure for the first time; see the verification sections below:

- **M0** foundations — layered config, the SQLite store and its contract guard,
  casefiles, REST and CLI adapters.
- **M1** ingest and search — extraction, chunking, embedding, FTS5 + sqlite-vec
  fused by reciprocal rank.
- **M2** the agent surface — seven `case_*` tools over MCP, per-response fencing,
  profile gating, and the harness-neutral analyst pack in `analyst/`.
- **M3 slice 1** — mail (EML/MBOX/MSG), spreadsheets (XLSX/CSV/TSV), archives
  (ZIP/TAR), document hierarchy, and the expansion budget.
- **M3 slice 2** — the extraction quality gate: recognition configured
  deliberately for English, Ukrainian and Russian, a three-rung escalation
  ladder, page images as documents, and `text_source` recorded per document and
  surfaced to the agent.
- **M3 slice 3** — retrieval quality, measured: an evaluation harness with a
  tracked baseline, section windows around a matched passage, and a rerank stage
  that ships disabled because measuring it said to. See the section below.
- **M3 slice 4** — legacy binary Office formats: `.doc`, `.xls`, `.ppt` and
  `.rtf` converted to their modern siblings and read by the extractor that
  already owns each, recovering 258 documents that a folder walk had been
  dropping without an outcome record. See the section below.

**Archived on 2026-08-26:** `hard-formats-and-containers`, all 32 tasks done,
now at `openspec/changes/archive/2026-08-26-hard-formats-and-containers`. It
published `container-extraction` and `document-hierarchy` and folded the
`document-ingestion` and `untrusted-content-boundary` deltas into the published
specs. All thirteen delta requirements landed byte-identical, and
`untrusted-content-boundary`'s second requirement survived the block
replacement. `openspec list` reports no active changes.

---

## The verification debt: paid on 2026-08-26

Every one of the 212 tests runs against a **deterministic stand-in embedder**,
and no test opens a **PDF**. That is still true of the suite, and it is why this
script exists: the environment the project was built in could not reach the
model host, so those paths were never exercised — not skipped by choice,
unreachable.

The base claim of the whole project — *documents go in, an agent works them and
answers with citations that resolve* — therefore rested entirely on a stand-in.
Every milestone since M0 stacks on top of it.

```bash
python scripts/verify_model_paths.py
```

**Result: 6 passed, 0 failed, exit 0.** Run on macOS on Apple silicon, Python
3.12.14, with `uv venv --python 3.12 && uv pip install -e ".[dev]"` — the setup
`CLAUDE.md` documents. Weights downloaded from the Hub on first use.

| Check | Result |
|---|---|
| PDF extraction (Docling layout models) | `docling` recovered 44 chars including the expected phrase |
| Real embedder loads | `intfloat/multilingual-e5-large` |
| Contract width matches the model | 1024 dimensions, as declared |
| Query and passage widths agree | both 1024 |
| End-to-end with real embeddings | 2 documents, 2 hits, 2 found by vector search |
| MCP surface answers with a citation | `note.md (chars 0–62, …)` |

What that settles, stated precisely, because a green run is only worth what it
actually covers:

- **Docling opens a PDF and returns its text.** The extractor ran, not merely
  imported. This path had never executed anywhere in the project.
- **The shipped `embed_dimensions` default of 1024 is correct.** Nothing had
  ever compared it to a real model, and it sizes the vector index and enters the
  corpus fingerprint. Had it been wrong, every corpus built on the default would
  have been mis-sized.
- **The vector path works end to end with real embeddings.** Real vectors were
  produced at ingest, stored in `sqlite-vec`, and nearest-neighbour search
  returned both documents — both hits carry a vector rank, not just an FTS one.
  Under the deterministic embedder the same assertion is vacuous, because those
  vectors carry no meaning.

  Read narrowly, though. The script's query — *"who was awarded the lease"* —
  shares the words *awarded* and *lease* with the stored text, so FTS would have
  matched it too. What this proves is that the vector leg **ran and returned**,
  not that retrieval succeeded where keywords would have failed. **Retrieval
  quality is still unmeasured**, and nothing here is evidence about it. (The script's comment
  used to claim the query "shares no content word with the text" and named a
  different query than the code sends. Both were wrong and are now corrected in
  place; the check itself is unchanged and still weaker than that comment
  advertised.)
- **The MCP surface answers with a citation that resolves**, driven in process
  against a corpus built with real vectors.

The script writes to a temporary directory and removes it — verified: the
workspace it named was gone after the run. It touched no corpus.

Re-run it after any change to the contract, the embedder, or the extractor. A
failure there is a real finding, not a flaky environment — these are the only
paths nothing else covers.

## The two-vendor agent test: done 2026-08-26 — M2 task 8.7 is closed

The thing the script could not do: point a live agent at the surface and confirm
the tool descriptions elicit the right calls, from **two different model
vendors**. This was M2's acceptance criterion and the prototype's headline
claim. It passed on both, over stdio (`jackryan serve-mcp`).

**Vendor A — OpenAI, via Codex CLI** on a ChatGPT subscription sign-in (no API
key involved; Codex holds its own OAuth tokens). Call order: `case_list_casefiles`
→ `case_casefile_overview` → five `case_search` phrasings → three
`case_get_passage` → three `case_cite`.

**Vendor B — Anthropic, via a fresh `claude -p` process** with no prior context,
initialised only from `analyst/role.md`. Call order: `case_list_casefiles` →
`case_casefile_overview` → `case_list_documents` → `case_search` → four
`case_cite`.

Both called `case_casefile_overview` **before** searching, cited every factual
claim through `case_cite`, and reported coverage in terms of what was actually
searched. Both found a conflict of interest that required chaining three
documents — a board member who directs the company holding 60% of the winning
bidder — which no single document states.

The corpus was **synthetic and written for this test**: four short invented
documents about a fictional harbour lease, in the same register as the
`Northgate Holdings` fixture already used by `scripts/verify_model_paths.py`.
No real case material was ingested, and the corpus was not committed. Saying so
explicitly because the names below read like case notes and this repository is
public.

More telling than the pass: both **declined to overclaim**. The minutes name who
was present and record a 3–1 vote but never say how each member voted, and both
agents flagged "Vlasenko voted" as their own inference rather than a corpus
fact. The Anthropic run added the point that the minutes record no declaration
of interest *by anyone*, "so their silence is a gap, not evidence that no
declaration was made". That is the epistemic behaviour `analyst/role.md` asks
for, produced from the role and the tool descriptions alone.

**How the Anthropic run was made honest.** The first attempt ran with the corpus
files sitting in the process's working directory, so a correct answer proved
nothing — it could have come from reading the files. It was re-run from an
**empty directory** with `Read,Write,Edit,Glob,Grep,Bash,WebFetch,WebSearch,Task`
denied, leaving the MCP surface as the only possible source. The tool-call order
above is from that run.

**Read this narrowly in one respect.** The instance used the **deterministic
embedder**, selected explicitly in a test profile, because the model download
stalled. So search hits came from FTS5 and the vectors carried no meaning. That
does not weaken the criterion — it is about whether a model *chooses* the right
tools and cites correctly, not about retrieval quality — but it does mean this
run is not evidence about retrieval, and a rerun on the real embedder would be
worth having when convenient.

To repeat it:

```bash
jackryan serve-mcp     # stdio; or reach the mounted surface at /mcp
```

Initialise the agent with `analyst/role.md` and give it a question it must
search for. What you are watching for: does it call `case_casefile_overview`
before searching, does it cite through `case_cite` rather than asserting, does
it report coverage honestly. The `/mcp` HTTP mount is still undriven by a live
agent — and that is the transport whose lifespan bug made every in-process test
pass while real requests returned 500.

---

## A real defect — found, confirmed, and now fixed

**The contract fingerprint does not cover the embedding library version, and
it needs to.**

`Contract.fingerprint()` covers `chunk_max_chars`, `chunk_overlap_chars`,
`embed_model`, and `embed_dimensions`. It does not cover the `fastembed`
version. `pyproject.toml` pins `fastembed>=0.4`, which is not a pin.

Loading the model on `fastembed` 0.8.0 emits:

> The model intfloat/multilingual-e5-large now uses mean pooling instead of CLS
> embedding. In order to preserve the previous behaviour, consider either
> pinning fastembed version to 0.5.1 or using `add_custom_model`.

So a corpus ingested under 0.5.1 and later queried under 0.8.0 has **the same
fingerprint and incompatible vectors**. The guard passes; retrieval degrades
silently. That is precisely the failure the contract guard exists to prevent,
and it is invisible — no error, no refusal, just worse answers that look fine.

**Confirmed on 2026-08-26, no longer a prediction.** A clean
`uv pip install -e ".[dev]"` against the current pins resolved `fastembed` to
**0.8.0** and `docling` to **2.122.0**, and the run of
`scripts/verify_model_paths.py` above emitted that warning at every one of the
three points it loads the embedder. So the version a fresh install gets today is
the mean-pooling one, and the vectors the six passing checks were built on are
mean-pooled. Nothing records that fact anywhere a future run could read it —
which is the defect.

The same class of gap applies to `docling>=2.0`: extraction output is
corpus-coupled (it becomes the chunks) and the extractor version is not in the
fingerprint either. Lower severity, since a change there produces visibly
different text rather than quietly misaligned vectors.

**Fixed by the `contract-covers-embedding-library` change.** What landed, and
the three decisions behind it:

1. `fastembed` and `docling` are pinned exactly, with the reason written at the
   pins so a later cleanup does not loosen them back.
2. The contract gained an `embed_library` value — `fastembed==0.8.0` — and the
   fingerprint covers it. It is **declared, not read from the installed
   package**: reading the environment would make the fingerprint a property of
   whatever happens to be installed rather than a written fact, and would refuse
   a valid corpus after a patch bump that changed nothing.
3. What makes the declaration trustworthy is that it is verified. A declared
   version that is not the installed one is fatal at configuration load *and* at
   embedder construction, naming both versions and saying how to proceed. Two
   places because the CLI and the tests build embedders without a full boot —
   the same "enforced where it was written, not where every caller crosses"
   pattern this repository has now hit four times.

Pooling did **not** become its own contract field. A field implies the operator
can set it, and through `fastembed`'s default path they cannot; the library
version is the honest proxy. `docling` is pinned but deliberately kept out of
the fingerprint: its changes produce different *text*, which is visible and
internally consistent, where a pooling change produces invisible mismatched
vectors. `openspec/changes/.../design.md` carries the full argument.

**A sibling gap, found by review of that change and fixed straight after.** The
fingerprint recorded which *library* built the vectors but not which
*embedder*, so a corpus filled by the deterministic stand-in opened under a
real-model configuration and real query vectors were compared against hash
vectors of the same width. Closed by `corpus-identity-covers-the-embedder`:
corpus identity is now the contract plus the embedder actually constructed, and
`/health` reports the value the store enforces rather than the contract alone.
The lesson is the one this file keeps repeating — the first fix made the
fingerprint *assert* something it could not check, which is worse than saying
nothing.

**Both of those changes are breaking, and each bumped the fingerprint
separately** — so if a corpus is refused, read the two identity strings to see
which component differs before assuming which one refused you. The paragraph
below is about the *library* change specifically.

**This is a breaking change, by design.** The fingerprint string changed, so any
corpus built before it — including the one built during the 6/6 run recorded
above, whose vectors are mean-pooled — is refused until reingested. That is the
correct outcome and the reason for doing it now: no corpus outside development
exists. Afterwards it would have cost a forced reingest of real evidence.

---

## What is left in M3

Slice 1 took the leg that needed no model. Slice 2 — the extraction quality gate
— took OCR and the VLM path. What remains:

| Leg | Notes |
|---|---|
| ~~Cross-encoder rerank~~ | Built. The seam ships; no model does. Measured below. |
| ~~Section-window expansion~~ | Built. A result's text is a window around the matched passage; the passage stays what is cited. |
| ~~The summarization layer~~ | Built. Per-chunk contextual summaries folded into embed input, then a per-document map-reduce summary. The per-chunk switch is **corpus-coupled but lives in the profile**: the summariser's identity is *composed* into corpus identity exactly as `embedder` is, not declared in the `contract` block, because it is partly a hash of the shipped prompt and sampling parameters that no operator could know. Turning it on refuses an existing corpus; leaving it off keeps the identity string byte-identical, which is what lets the `bauman4` corpus survive this change. Off by default because it is the dominant ingest cost. The per-document summary folds nothing, so it moves no vector and is outside corpus identity. |
| Mentions / NER | Classical NER plus pattern identifiers, as facets and pivots. Pattern extraction needs no model and could ship first. |

Recommended order: ~~fix the fingerprint gap~~ (done twice, the library version
then the embedder identity) → ~~OCR/VLM~~ (done) → ~~rerank and section-window
together as a retrieval-quality slice~~ (done, measured, see below) →
~~summaries~~ (done, see below), then mentions.

**Retrieval quality is now measured**, which closes what this document called
the single largest unaddressed gap in the project. What that measurement settles
and what it does not is the next section.

PST stays last, as `docs/design.md` § 10 has it.

## What the summarization layer ships, and what it deliberately does not

The `contextual-summaries` change built the summariser port, an
OpenAI-compatible implementation, the fold into embed input behind
`chunk_summaries`, and per-document summaries. Schema 6 adds `chunks.summary`,
`documents.summary` and `documents.summary_by`.

**The `bauman4` corpus survived it.** With the fold off, `corpus_fingerprint`
produces the identity string that store already recorded, byte for byte, because
the `|summariser=` component is appended only when folding is on. Verified
against a copy of the real 435 MB file: it migrated 5 → 6, opened, kept all
36,305 chunks, and reported the unchanged identity. Turn the fold on and the same
store is refused with both strings named — which is correct, and costs a reingest
of 1,760 documents through roughly 36,000 LLM calls.

This is the first thing in the project that sends corpus text off the instance.
It is opt-in and the read stack still runs offline with zero configured
endpoints.

**A reasoning model needs thinking off, and the request now says so.** Against
the gdx boxes' Qwen3.8-27B, the first end-to-end run failed two documents: the
model spent the recipe's whole 200-token budget on `reasoning_content` and
returned an empty context. The fail-closed policy caught it — those documents
failed rather than being embedded bare — but the fix is
`chat_template_kwargs: {"enable_thinking": false}`, hashed into the recipe
because it changes what the model produces. Same ingest afterwards: no failures,
and 60 seconds instead of 178. An endpoint that ignores the key leaves a
reasoning model thinking, and the error now names that cause specifically.

**What is deliberately not done: whether folding actually improves retrieval.**
That needs a summarised corpus and a re-recorded baseline annotated with the new
identity, and `openspec/specs/retrieval-evaluation` requires recording a baseline
to be a deliberate act. `scripts/evaluate_retrieval.py` was run and is at or
above the baseline on every metric — which proves only that the default really is
off, since a moved figure would have meant something was folded that should not
have been. The measurement is the next reported piece of work on this leg, and
the baseline must not be quietly overwritten to get it.

**Mentions / NER is what remains in M3**, plus PST.

## Retrieval quality is measured now — and what it says about reranking

`scripts/evaluate_retrieval.py` builds a synthetic trilingual corpus in a
temporary directory, runs seventeen queries with recorded judgements through the
shipped `SearchService`, and reports recall@1/@5/@10 and MRR@10 for the keyword
leg, the vector leg and the fused ranking, with a per-language breakdown. It
compares against `docs/retrieval-baseline.json` and exits non-zero below it, with
a tolerance of 0.005 — kernels differ between machines and one query is 0.059 of
recall@1, so a gate that fires on arithmetic noise is one a reader learns to
ignore.

Comparability is established over corpus identity, which the run reads from the
context and the baseline records alongside its figures — two corpora built from
different text handed to the embedder are not comparable however well the named
settings agree. A baseline that states no corpus identity is reported as not
comparable rather than compared on the settings it does state: a key the
baseline does not record is otherwise skipped, which would have compared a run
clean against a corpus it was never measured over.

Judgements are keyed to a filename and a phrase, never to a chunk id — ids are
minted afresh on every reingest — and a judgement may name alternatives, because
near-duplicate documents legitimately carry the same answer.

**The baseline, recorded 2026-08-28 on Darwin arm64, python 3.12.14**, with
`intfloat/multilingual-e5-large` and no reranker:

| leg | recall@1 | recall@5 | recall@10 | MRR@10 |
|---|---|---|---|---|
| keyword | 0.647 | 0.941 | 0.941 | 0.784 |
| vector | 0.765 | 1.000 | 1.000 | 0.868 |
| **fused** | **0.882** | **1.000** | **1.000** | **0.926** |

Fusion beats both legs, which is the first evidence this project has that
reciprocal rank fusion earns its place. Per language, fused recall@1 is 0.714 for
English and 1.000 for Ukrainian and Russian; English is hardest because that is
where the three near-duplicate lease documents are.

**The measurement was shown to move and to fail.** The same run under the
deterministic embedder reports fused MRR 0.767 against 0.926, which is what makes
it a measurement rather than a formality — a figure that cannot move cannot
report a regression. Dropping one answering document from the corpus produced
nine metrics below baseline and exit code 1.

### Both available rerankers made retrieval worse

Measured on the same set, same embedder, same day:

| reranker | licence | fused recall@1 | MRR@10 | en | uk | ru |
|---|---|---|---|---|---|---|
| none | — | 0.882 | 0.926 | 0.714 | 1.000 | 1.000 |
| `Xenova/ms-marco-MiniLM-L-6-v2` | apache-2.0 | 0.176 | 0.454 | 0.429 | 0.000 | 0.000 |
| `jinaai/jina-reranker-v2-base-multilingual` | cc-by-nc-4.0 | 0.529 | 0.685 | 0.714 | 0.000 | 0.800 |

The per-language columns are recall@1.

**The cause was traced, not assumed.** For a Ukrainian query the cross-encoder
ranks English passages above the Ukrainian passage that answers it — for
"Хто отримав право користуватися причалом?" it returns two English documents
ahead of `akt-orendy-2021.md`, which fusion had first. The English-only model is
worse still, as expected of an English-only model on a trilingual corpus.

**The wiring was checked before the conclusion**, because "the new feature makes
things worse" is exactly the shape of an integration bug. The model orders
unambiguous relevant/irrelevant pairs correctly in all three languages; the
service returns results in descending rerank order; and scores recomputed
directly from the library match what the service recorded, to four decimals.

**Read this narrowly.** Fifteen synthetic documents and seventeen queries, where
one query is 0.059 of recall@1. It is not evidence that cross-encoder reranking
is useless in general — the usual claim for it is made on large, noisy corpora
where fusion's top ten holds many plausible passages, which is not this set. It
is evidence that reranking is not free, that this corpus's languages are where it
fails, and that adopting one needs a figure rather than a reputation. That is the
whole reason the harness was built before the leg it measures.

Two explanations were tried and did not hold: reranking at 500-character
passages, in case the cross-encoder's context was truncating a 2000-character one
(still worse — 0.529 against 0.294 fused recall@1 at that size); and a stricter
reading of one judgement, in case the set was penalising a legitimately different
answer (it was, for one query, and that judgement now names both).

### Running it

    python scripts/evaluate_retrieval.py                          # against the baseline
    python scripts/evaluate_retrieval.py --embedder deterministic # offline control
    python scripts/evaluate_retrieval.py --reranker MODEL         # measure a candidate
    python scripts/evaluate_retrieval.py --record                 # move the baseline

`--corpus` and `--queries` measure an operator's own material, which may never be
committed. Weights come from the cache `JACKRYAN_MODEL_CACHE` names.

---

## The store can now be carried forward, and identity cannot be impersonated

Four findings were paid down on 2026-08-28 because each stopped being cheap once
a real corpus exists, and none does yet. What matters for anyone touching the
store afterwards:

**`_SCHEMA` is frozen at schema version 4 and must not be edited.** Adding a
column there instead of to `_STEPS` is silently wrong in the worst way: every
statement is `IF NOT EXISTS`, so a store already on disk never receives it while
every store created afterwards has it, and both report the same version. A test
pins the baseline's column list literally, because the parity test cannot catch
this — its fixture executes the same live `_SCHEMA`.

**The baseline is deliberately one version behind what the code produces**, so a
brand-new store climbs the ladder's first rung. A migration runner exercised only
by a fixture rots between the day it is written and the day it is first needed.
The cost is that `_SCHEMA` no longer shows the schema you get.

**A schema is migrated; corpus identity is compared and never migrated.** The
ladder runs first, so a store that is carried forward and then refused on
identity is left improved rather than damaged.

**Identity escapes `\`, `|` and control characters, and deliberately not `=`.**
`embed_library` contains `==`. Every reachable identity is byte-identical to
what was recorded before the escaping, which is what let it ship without
refusing every existing store.

Verified end to end through `build_context`, the path every adapter crosses: a
v4 store opened, migrated to 5, kept its `.v4.bak`, and its pre-existing
document still read and reported `unrecorded`.

**What the second adversarial review caught, worth repeating.** The shipped code
was correct; three of its proofs were not. Dropping the migration's `commit()`
survived the entire suite, because on a fresh store `_verify_meta` commits
straight afterwards and flushes the pending migration — so only a store that
already carries a fingerprint depends on the migration's own commit, and no test
reopened one. Swapping SQLite's backup API for `shutil.copyfile` also survived,
losing a committed row that was still living in the WAL. And the width guard
does less than its spec claimed: `build_embedder` builds both embedders from the
contract, so configuration cannot make the widths disagree. All three are now
either fixed or stated honestly.

## The extraction quality gate: what it fixed, and what it proves

**The defect it closed was not a missing feature. Recognition was already
running, and had never been configured.** `DoclingExtractor` built a bare
`DocumentConverter()`, which under the pinned `docling==2.122.0` means
`do_ocr=True` with `ocr_options=OcrAutoOptions()`. Measured against an image-only
PDF: English recovered perfectly, Ukrainian and Russian recovered as **nine
characters of punctuation** — `'.\n\n:    .'` — which is not empty, so the
"refuse a document with no usable text" guard passed it and it stored, chunked
and embedded as a document an analyst could list and never find.

Three causes, each read out of the installed package rather than inferred:
`OcrAutoModel` picks the engine by host operating system (so extracted text, and
therefore the corpus, depended on the machine that ingested it); it forwards only
`mode` to the engine it picks, dropping the configured language entirely; and
finding no engine at all it logs a warning and yields the pages unchanged.

**The UK/RU extraction spike, settled on measurement.** An image-only PDF with
one pure-Ukrainian, one pure-Russian and one pure-Latin line, scored by
similarity to the ground truth:

| OCR language | Ukrainian | Russian | English |
|---|---|---|---|
| `auto` — what shipped before | 0.11 | 0.11 | 1.00 |
| `eslav` — the new default | 0.86 | **0.87** | 1.00 |
| `cyrillic` | **0.88** | 0.74 | 1.00 |

One model covers all three languages, so there is no per-language routing.
`eslav` wins Russian by a wide margin — `cyrillic` substituted Latin homoglyphs,
producing "pеreдana" — and loses Ukrainian by 0.02. RapidOCR was chosen over
EasyOCR (which `docs/design.md` § 5 named as the intended default) because it is
already installed by the `docling` pin, so the change adds no dependency.

**Read this narrowly.** One synthetic fixture, one font, a clean render, drawn
by PIL rather than photographed. It settles which model can read which script
and gives a directional quality signal. **It is not a benchmark on real scans,
and recognition quality on real scans remains unmeasured.** `eslav` visibly
confuses Ukrainian і with и — "Правління" comes back as "Правлиння" — which is
why the check scores similarity rather than exact match.

**What the automated verification covers, and what it deliberately does not.**
`scripts/verify_model_paths.py --only ocr` runs the ladder twice: once on the
shipped default, which must recover all three languages, and once forced to
`en`, which must lose the Cyrillic. The second run is the point — without it the
first could pass on an engine that ignored the language setting entirely. In the
suite itself, the gate's escalation policy is tested with injected rung readers
and never loads a model; the two checks that build a real pipeline are behind
`JACKRYAN_MODEL_TESTS=1`, so `pytest` still runs offline.

**Run on 2026-08-27: 8 passed, 0 failed, exit 0**, and the recognition checks
re-run on 2026-08-28 after the review fixes: **4 passed** for `--only pdf --only
ocr`, now including a third recognition check that the review asked for. macOS
on Apple silicon, Python 3.12, weights fetched on first use. The six earlier
checks still pass unchanged.

| Check | Result |
|---|---|
| PDF extraction (Docling layout models) | `docling` recovered 44 chars including the expected phrase |
| **Recognition of a scan** | escalated to `ocr` from a page with no text layer — uk=0.86 ru=0.87 en=1.00 |
| **Recognition language matters** | forced to `en`, the same page scores uk=0.11 ru=0.11 |
| **A misconfigured engine is refused** | constructing the converter *succeeded* for a nonsense language and initialising the pipeline refused it — the fail-open the check exists to close, demonstrated rather than asserted |
| Real embedder loads | `intfloat/multilingual-e5-large` |
| Contract width matches the model | 1024 dimensions, as declared |
| Query and passage widths agree | both 1024 |
| End-to-end with real embeddings | 2 documents, 2 hits, 2 found by vector search |
| MCP surface answers with a citation | `note.md (chars 0–62, …)` |

**The vision rung, run once on 2026-08-27 — `--only vlm`, 2 passed.**
`GRANITEDOCLING_TRANSFORMERS` loaded and read the same scan, returning 136
characters. It reads Ukrainian **better** than the recognition model does:
"Правління" came back correct, where `eslav` gives "Правлиння". That is one page
and not a basis for changing the default, but it is the first directional
evidence about where the vision rung earns its cost, and it points at
Ukrainian diacritics rather than at complex layout.

*The first version of this check was vacuous and passed anyway.* It asserted
`VLM in gate.rungs()` — true from configuration alone, whether or not a model
ever ran — and read the ladder's result, which was the OCR reading, because with
a floor nothing clears the richest attempt wins and OCR's output was longer. It
now reads at the vision rung directly and asserts on the text that came back.
Worth recording as the fourth instance of this project's recurring lesson: an
assertion that cannot fail certifies nothing.

Also checked by hand through the shipped CLI, because the script drives the
service layer rather than the binary: `jackryan status` returns immediately and
loads no engine, `jackryan ingest` logs RapidOCR building
`eslav_PP-OCRv5_rec_mobile.onnx` **before** reading any document, and the stored
row carries `text_source='native'` under `schema_version=5`. That is the
distinction the design turns on — verification belongs to an ingest run, not to
process startup — and reading it out of the database is the only way to see it.

**Weaker guarantees, stated rather than glossed:**

- **At startup the vision rung is verified by name only.** `QualityGate.verify()`
  builds the recognition engine — really builds it, via `initialize_pipeline`,
  because a `DocumentConverter` constructed with a nonsense language returns
  quite happily and fails on the first scan. It only *resolves* the vision
  model's spec name, because its weights are gigabytes and the rung is reached
  rarely. A vision model that resolves but cannot run therefore fails on the
  first document that needs it, not at the start of the run.
- **`text_source` is a disclosure, not a guarantee.** It reaches the agent as
  `read_as` on every payload carrying corpus text. It says a quotation came from
  recognition; it does not make that quotation right. Recognition renders a word
  as a plausible different word and nothing downstream detects it.
- **Recognition weights come from `modelscope.cn`**, a different host from the
  Hugging Face one the embedder and docling's layout models use. An air-gapped
  deployment has to allow or mirror it. The image's `PREFETCH_MODELS=true` path
  now builds the engine so a prefetched image carries them.

**A defect found by building the image, which had never been built.** The
container could not do OCR at all, and nothing said so.

`opencv-python` arrives with the RapidOCR engine and `python:3.12-slim` carries
neither `libgl1` nor `libglib2.0-0`, so `import cv2` fails with
`ImportError: libxcb.so.1`. Three consequences, all pre-dating this change:

- **`docker build --build-arg PREFETCH_MODELS=true` failed outright**, in
  docling's own `download_models()`, before reaching anything this change added.
  That is the documented way to build a released, offline-capable image. The
  previous handover recorded that this build mode had never been run — this is
  what it was hiding.
- **Recognition in the shipped container silently did nothing.** Before this
  change, an ingest there hit `auto`, which tries rapidocr, catches the
  `ImportError`, tries easyocr, finds it absent, and then logs a warning and
  yields the pages unchanged. Every scanned page in a container ingested as an
  empty document, with no error anywhere.
- **After this change it fails loudly instead** — which is correct, and which
  also means the container cannot ingest at all until the libraries are present.

Fixed by installing both packages in the base layer, not under the prefetch
branch, because `import cv2` happens whenever recognition runs and not only when
weights are fetched. The set was determined by installing candidates into the
built image and importing `cv2`: `libgl1` alone still leaves
`libgthread-2.0.so.0` missing.

**With that fixed, the offline image was built and driven.** `docker build
--build-arg PREFETCH_MODELS=true` completed, and the image read the same
three-language scan under `--network none`, scoring uk=0.86 ru=0.87 en=1.00 —
identical to the host. The RapidOCR log lines name the weights it loaded from
inside the image (`File exists and is valid: …/eslav_PP-OCRv5_rec_mobile.onnx`),
which with no network it could not have fetched. That is the first time an
offline-from-first-run image has been built *or* exercised in this project.

Sizes, measured rather than assumed: **5.81GB without the prefetch, 10.2GB with**
— so the weights add about 4.4GB, where the Dockerfile comment used to claim
2.5GB. It is corrected in place. Most of the 5.81GB base is the CUDA stack that
`docling` pulls in through torch and that an arm64 container cannot use.

## The adversarial review of this change, and what it caught

Before merge, the diff was reviewed by six independent lenses — gate
correctness, configuration, storage, the security surface, test quality, and
spec-versus-code fidelity — each finding then handed to a separate agent
instructed to *refute* it and to default to rejection when unsure. It produced
24 findings; the ones that survived were real, and two were serious.

**The tests certified nothing about the change's headline feature.** Replacing
all five `text_source` seam sites with the literal `"native"` left the suite
green at 292 passed. Every test in the suite produced `native`, so the
extractor → service → store → payload wiring could be removed entirely and
nothing would notice. Closed by an ingest that goes through the real service
with a stubbed gate returning `ocr`, asserting the stored row and all four
agent payloads. Both halves were then shown to fail under the reviewer's own
mutations.

**A photograph with no text stored as `<!-- image -->`, labelled `text-layer`.**
Docling marks a picture region it read no text from with that comment. It clears
no floor, but it carries letters, so the usable-text refusal passed it — and the
document then stored, chunked, embedded, and told the agent its text came off
the page. That is the nine-characters-of-punctuation failure again, in docling's
clothes rather than an OCR engine's, and it was reproduced end to end on a real
PNG. Closed by `content_of`, which both the floor and the refusal now measure
through.

Also closed: images were bounded only by *file* bytes, which is the one quantity
a decompression bomb makes meaningless — a few-kilobyte PNG can declare any
number of pixels — so there is now an explicit pixel ceiling read from the
header before any decode; `min_chars_per_page: 0` was accepted and silently
switched the whole ladder off, since `>=` means a floor of zero is cleared by an
empty reading; the router now owns the gate outright, because the service's own
copy could be verified while the extractors read through a different one; and
the `gate` fixture's alarm did not sound, because the `AssertionError` it raised
was caught twice on the way out and surfaced as an ordinary per-document
failure.

**Two findings recorded rather than fixed**, both real:

- **`read_as: text-layer` is the strongest provenance value the surface offers,
  and rung one never checks the page.** It reads the PDF's content stream, so
  text an adversary rendered invisibly — white on white, behind an image, zero
  size — is reported as having come off the page. Fixing it means comparing the
  stream against the rendered page, which is a different capability.
- **The floor is a whole-document average.** Whether a scanned page is
  recognised depends on how much text sits on the *other* pages, and the party
  supplying the document chooses that. A per-page gate is the fix and is a
  larger design; `design.md` already lists per-page rung selection as a non-goal.

Both are in `docs/implementation-notes.md`.

**A caution about the method itself.** The refuting agents proved their claims by
mutating the source — and left the mutants in the working tree: `read_as`
deleted from `provenance()`, `text_source = ''` in the upsert, `.strip()` dropped
from `chars_per_page`, `initialize_pipeline` removed from `check_engine`, and a
bare `except Exception: continue` inserted into the escalation loop. Nothing was
committed, because the diff was read before committing rather than trusted. If
you run this kind of review again, `git diff` against the branch head before you
stage anything.

**CI could not have caught it, and still cannot.** `.github/workflows/docker.yml`
builds with `PREFETCH_MODELS=false` and then runs `jackryan --version`. That
proves the image builds and the binary starts; it touches no document, so no
extractor and no recognition engine is ever constructed. Worth knowing before
reading a green Docker gate as "the container works".

The lesson is the one this file keeps repeating, in its container form: **a build
argument nobody has run is not a supported path.** `PREFETCH_MODELS=true` was
documented, referenced in `docs/implementation-notes.md`, and broken.
- **This is a breaking schema change.** `documents` gained `text_source` and
  `SCHEMA_VERSION` went 4 → 5. This store has no migration mechanism at all —
  no `ALTER TABLE` anywhere — so an existing store is refused until recreated.
  Free only because no corpus exists outside development; see
  `docs/implementation-notes.md`, because the next schema change will not be.

---

## Legacy binary Office formats: what ran, and what it settles — 2026-09-01

`.doc`, `.xls`, `.ppt` and `.rtf` are registered formats. Each is converted to
its modern sibling by shelling out to LibreOffice and handed to the extractor
that already owns that suffix, so the corpus holds one rendering per kind of
document rather than two.

**Why it mattered more than it looked.** The 259 legacy files in the first real
dump were not failing. A folder walk marks a file it found itself as not named
directly, and the pre-filter in `services/ingestion.py` drops such a file with
**no outcome record at all** — so the report read 1502 ingested, 0 failed, while
a sixth of the material had never been offered to an extractor. A silent drop is
worse than a failure for exactly the reason the punctuation-only guard exists:
nothing tells you to look.

### The four checks that needed the binary

`scripts/verify_legacy_office.py` — **5 passed, 0 failed.** Fully synthetic and
needs no model. It asks LibreOffice to convert HTML and a hand-written flat-ODF
deck *into* genuine OLE2 and RTF files, then runs the real `FormatRouter` over
each product and asserts a Cyrillic and a Latin sentinel both survive,
`text_source` is `native`, the media type is the legacy one, and the extractor
names the conversion. This is the only thing that exercises a real conversion:
the suite cannot write a Word 97 file and no real corpus material may be
committed as a fixture.

Notably the `.ppt` case passes. The plan expected it to be uncorroborated,
because `textutil` had returned implausible character counts for the dump's
`.ppt` samples. That was `textutil`, not the format.

**The legacy tail of the real dump — 258 of 259 ingested, 34m56s, 3316 chunks,
5,716,813 characters that were previously unreachable.** Media types came back
`application/msword` 168, `application/vnd.ms-excel` 81,
`application/vnd.ms-powerpoint` 8, `application/rtf` 1 — every one the type the
file on disk is, none the type it was read as. Extractor lineage came back
`legacy-office+docling` 177, `legacy-office+spreadsheet` 79 and
`legacy-office-passthrough+spreadsheet` 2, with no third literal; those two are
the OOXML workbooks misnamed `.xls`, read directly with no conversion. The single
failure is the one HTML file misnamed `.xls`, refused with `is named .xls but is
neither an OLE2 nor an OOXML container` — the predicted file and the predicted
message. A search over that casefile returns cited passages out of converted
`.doc` files, so the loop closes end to end.

**The container converts, offline.** `docker run --rm --network none` built a
genuine `.xls` inside the image and read it back through the real router, both
sentinels intact. Debian resolves `/usr/bin/libreoffice`, which is why
`find_converter` tries `libreoffice` before `soffice` — the order was read out of
docling's own source rather than guessed, and it matters.

**Image size, re-measured rather than adjusted:** 6.49 GB without weights,
10.7 GB with, from `docker images --format '{{.Size}}'`. LibreOffice costs about
0.68 GB against the 5.81/10.2 GB measured on 2026-08-27.

**The converter absent, through the shipped CLI.** LibreOffice was genuinely
removed from the host — not monkeypatched — and `jackryan status` read
`"legacy_office": "unavailable"` while a `.md` ingest still reported 1 ingested,
0 failed. That is the claim that an absent converter fails documents rather than
runs.

### What it does not settle

- **The full 1922-file dump was not re-ingested.** Two attempts were abandoned.
  That run is dominated by a cost this change does not touch: one 6.8 MB workbook
  in the dump extracts to 8.9 MB of text — about a sixth of the whole corpus —
  and spends over twenty minutes being chunked and embedded. Re-establishing the
  1502 baseline measures the embedder, not this. The legacy tail was ingested on
  its own instead, which isolates the variable. **What is therefore unmeasured is
  the interaction**: nothing has re-run the other 1663 files alongside these, and
  the argument that they are unaffected rests on no existing extractor's suffix
  map changing and on 475 passing tests, not on a run.
- **Conversion fidelity is unmeasured.** A converted `.doc` reads as whatever
  LibreOffice's DOCX writer made of it, which is not necessarily what Word 97
  showed. `text_source` says `native` — truthfully, since no recognition ran — so
  the `legacy-office+` prefix on `documents.extractor` is the only signal an
  analyst has that a converter stood between the file and the text. See the note
  in `docs/implementation-notes.md`.
- **Concurrency is unexercised.** Conversions run one at a time. Each gets its
  own `-env:UserInstallation` profile, which is what makes concurrency *possible*
  — LibreOffice takes an exclusive lock on that directory — but nothing has run
  two at once.
- **`.dot`, `.xlt`, `.pot` and `.pps` are deliberately unregistered.** They
  convert through the same path and would be one line each. None appears in this
  dump, so none could be demonstrated.

### Two things the plan got wrong, found only by building it

Both are worth knowing because both would have passed review as written.

**The passthrough could not delegate on the original path.** The plan said an
OOXML file misnamed `.xls` should skip conversion and be handed to
`SpreadsheetExtractor` directly. That extractor keys its media type off
`path.suffix`, and `.xls` is not in its map — so `sheets.py` raises `KeyError`,
which is not an `ExtractionError`, which means a whole-run abort in exactly the
case the change adds. The file is copied into the scratch directory under its
true suffix first.

**A `.doc` that is really RTF was refused.** Ordinary Word and mail-merge output.
LibreOffice converts it without complaint; the magic gate refused it as "neither
an OLE2 nor an OOXML container" — the same class of silently-unread legacy file
the change exists to eliminate. Caught by review, not by the plan or the tests.

### What two reviewers caught that nine tests had not

The change's central claim is that every failure path raises `ExtractionError`,
because `_ingest_work` catches only that and anything else ends the run. Both
reviewers independently reproduced holes in it:

- A **delegate** can raise something else. `SpreadsheetExtractor` guards
  `load_workbook` but not the lazy row iteration beneath it, so a workbook
  truncated mid-sheet surfaces a bare `ParseError`. Reproduced end to end.
- `tempfile.mkdtemp` sat outside every `try`, and the two `mkdir` calls under
  none — so an `OSError` on a full scratch filesystem ended the run. Reachable
  precisely because this change starts writing hundreds of LibreOffice profiles
  into that filesystem.
- **The conversion timeout killed one pid, and that pid is not the worker.**
  `soffice` execs a launcher; Debian's `libreoffice` goes through `oosplash`. The
  surviving `soffice.bin` could write into the scratch directory *after* the
  `finally` had removed it, leaving converted evidence on disk. Now
  `start_new_session` plus a process-group kill, with a test that backgrounds a
  grandchild and asserts it never finishes its work.
- **Nothing bounded the converted artefact.** Every other ceiling here measures
  input the caller supplied; the converted file is what a delegate loads whole,
  and a bounded `.xls` can expand without bound.

Nine reintroduced defects each turned the matching test red with the reported
symptom. Two of those tests did not exist before review: the scratch-directory
test globbed a guessed temp root, where a disagreement with
`tempfile.gettempdir()` would leave both sets empty and the assertion vacuous;
and **no in-suite test asserted a successful conversion at all** — every one
ended in a raise, so the `legacy-office+` lineage and the media-type override
were pinned only by the out-of-suite script, which needs LibreOffice and does not
run in CI.

### One residual risk, stated plainly

LibreOffice is a large, historically CVE-rich parser for OLE2, BIFF and RTF, and
it is now handed files from untrusted dumps. In the container it runs as root
with full network access; `--headless` is a UI switch, not a sandbox. This is
widened, not opened — docling and the OCR stack already parse untrusted PDFs as
root in the same image — and excluding the JRE via `--no-install-recommends` is a
genuine reduction. Recorded in `docs/implementation-notes.md` rather than fixed,
because giving the image a non-root user is its own change.

---


## What this environment could not do, so you should not trust it was checked

- **~~No model weights.~~ Settled 2026-08-26.** PDF extraction and the real
  embedder are now exercised — see the verification section above. Recognition
  joined them on 2026-08-27 with the extraction quality gate, and the vision
  rung was driven once by `--only vlm`. **Rerank has now been exercised against
  two real cross-encoders** — see the measurement section above. **Statistical
  NER remains unexercised**, because no code for it exists yet. The vision rung is not
  part of a default verification run and has been driven on exactly one page.
- **No LLM endpoint.** Nothing that calls one has ever been run.
- **~~No Docker.~~ Compose settled 2026-08-26 — M0 task 7.4 is done.** The image
  was built and `docker compose up -d` run for the first time. Evidence, in the
  order it was taken: the container reported `Up (healthy)` and
  `docker inspect` returned health status `healthy`, so the `HEALTHCHECK` fires
  and passes; `GET /health` answered from the *host* over the published port
  (not from inside the container) with the profile and contract fingerprint;
  `docker compose run --rm cli casefile create ...` started the scaled-to-zero
  `cli` service and created a casefile; and `GET /api/casefiles` on the
  long-lived service then returned that same casefile, which is the proof that
  the `/data` volume is genuinely shared between the two services rather than
  each holding its own. The stack was then torn down.

  **~~Still unused: `--build-arg PREFETCH_MODELS=true`.~~ Built 2026-09-01**, in
  the course of re-measuring the image for LibreOffice: 10.7 GB against 6.49 GB
  without. So an offline-from-first-run image has now been built at least once.
  What that does *not* settle is that it runs offline: nothing has started the
  weights-bearing image with networking disabled and ingested a scan through it.
  The note in `docs/implementation-notes.md` about `check_real_embedder` still
  stands, and would still fail spuriously in exactly that image. A real
  conversion *was* run offline in the weightless image with `--network none`, so
  the LibreOffice half of the offline promise is checked and the model half is
  not.
- **~~No live agent.~~ Settled 2026-08-26 for stdio — see above.** Two vendors
  drove the surface and chose correctly. **The `/mcp` HTTP mount is still
  undriven by a live agent**, which is the transport that once returned 500 on
  every real request while all sixteen in-process tests passed. Old text, kept
  for the record: the MCP surface is driven by tests through `call_tool`, by
  one real HTTP `initialize`, and now by `verify_model_paths.py` in process
  against real vectors. **No model has ever chosen to call it** — that is still
  the open acceptance criterion, and the script cannot close it.

Anything else in the repository that reads as verified, was.

---

## Three failures worth not repeating

Each of these shipped, was caught by adversarial review rather than by the
tests, and had the same shape.

**M1 — deleting a casefile orphaned FTS and vector rows.** SQLite reuses
rowids, so the next ingest *anywhere in the corpus* failed permanently. The
test suite checked cleanup on the path that was written, not on the path a user
crosses. The fix was one trigger every delete goes through, and
`documents.parent_id ON DELETE CASCADE` now extends it to hierarchy. **When
testing deletion, assert by re-ingesting afterwards and confirming it
succeeds** — inspecting the tables passes even when rows are orphaned.

**M2 — `/mcp` returned 500 on every HTTP request.** Starlette does not run a
mounted sub-app's lifespan, and that lifespan is what starts the MCP session
manager. All sixteen surface tests passed because every one called `call_tool`
in process: the mount was verified to *exist* and never verified to *work*.

**M3 slice 1 — twice in one change.** Expansions could be excluded from a
listing only at the store, not at the service seam every adapter crosses; and
`case_cite` emitted `found_at` unsanitised while every sibling value was
collapsed.

The pattern, stated once: **a rule gets enforced where it was built, not where
every caller crosses.** When you add one, find the single point all paths go
through and put it there. And a passing test is not evidence until you have
seen it fail — several of the above passed against broken code, and at least
one assertion turned out to be vacuous by construction.

---

## Conventions worth knowing before your first commit

- **OpenSpec governs every substantive change.** Explore → propose → apply →
  sync/archive. No substantive code without a change directory.
- **The repository is public.** No secrets, no real hostnames or paths, no real
  corpus contents — in code, docs, commit messages, or sample output. Grep
  before committing; `CLAUDE.md` lists the patterns.
- **Work on a branch, open a PR.** CI is three gates: pytest, gitleaks, and
  Docker — the last builds the image and then runs the CLI inside it. Nothing
  else runs — no linter, no formatter.
- **Say what is unverified.** Every PR in this repository states what it did not
  check. That habit is the reason this document can be trusted, and it is worth
  more than a clean-looking history.
