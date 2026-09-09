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
| ~~The summarization layer~~ | Built. Per-chunk contextual summaries folded into embed input, then a per-document map-reduce summary. The per-chunk switch is **corpus-coupled but lives in the profile**: the summariser's identity is *composed* into corpus identity exactly as `embedder` is, not declared in the `contract` block, because it is partly a hash of the shipped prompt and sampling parameters that no operator could know. Turning it on refuses an existing corpus; leaving it off keeps the identity string byte-identical, which is what lets the real corpus survive this change. Off by default because it is the dominant ingest cost. The per-document summary folds nothing, so it moves no vector and is outside corpus identity. |
| ~~Mentions / NER~~ | Pattern identifiers built; the classical NER model is the seam, not shipped. Four extractors — email, phone, IBAN with a mod-97 check, and registration number anchored to a `ЄДРПОУ`/`ИНН`/`ІПН` keyword — run at ingest with no setting, and are written inside the transaction that writes the chunks. `case_mentions` inventories them; `case_search --mention` pivots on one. **A casefile ingested before this change has no mentions until it is reingested**, and an empty facet over an old casefile is indistinguishable from a corpus that genuinely contains none. That is not fixable by a migration — the mentions come from chunk text, so re-extracting them is a reingest. |

Recommended order: ~~fix the fingerprint gap~~ (done twice, the library version
then the embedder identity) → ~~OCR/VLM~~ (done) → ~~rerank and section-window
together as a retrieval-quality slice~~ (done, measured, see below) →
~~summaries~~ (done) → ~~mentions~~ (done, see below). **Only PST remains in
M3**, and `docs/design.md` § 10 still has its library choice open.

## What mentions ship, and the one thing that will mislead an analyst

Four pattern extractors behind a registry, run over every chunk at ingest with
no setting to enable, written inside the transaction that writes the chunks.
`case_mentions` inventories a casefile's identifiers with two counts —
how many mentions and in how many documents, because forty mentions in one
document is a different fact from one in each of forty. `case_search --mention`
narrows to passages carrying one.

**The filter is applied by the retrievers, not to their results**, and that is
the whole of the implementation worth knowing. Both legs fetch
`depth = limit * 5` candidates, so filtering their output would drop every
matching passage that ranked below that depth unfiltered — and on a corpus of
36,000 chunks the caller would be handed nothing while the store held exactly
what they asked for, which reads as "this casefile does not mention that
account". The predicate is inside the SQL of both legs, beside the casefile
constraint that is there for the same reason.

**Precision is the bar, and it cost a real false positive to find.** On a
realistic letterhead, `ЄДРПОУ 12345678, тел. +380441234567` filed the telephone
number as a second registration number, because the keyword sat 17 characters in
front of it. Two local rules close it: a digit run preceded by `+` is a telephone
number, and the keyword names the *next* number after it. The IBAN extractor
validates mod-97 rather than matching a shape, because a shape match turns every
product code into a bank account.

**The thing that will mislead an analyst**, stated plainly because nothing in the
tool can say it for us: a casefile ingested before this change has no mentions at
all until it is reingested. Its facet is empty and a filtered search over it
returns nothing, which is indistinguishable from a corpus that genuinely contains
none. A migration cannot fix it — the mentions come from chunk text, so
re-extracting them means re-chunking, which is a reingest. And even on a fresh
ingest the facet is an inventory of what was *found*: an identifier written
without its keyword, or with a transposed digit, is absent from it. The analyst
pack's own rule that absence of evidence is not evidence of absence applies to
this list exactly.

**Retrieval quality is now measured**, which closes what this document called
the single largest unaddressed gap in the project. What that measurement settles
and what it does not is the next section.

PST stays last, as `docs/design.md` § 10 has it.

## What the summarization layer ships, and what it deliberately does not

The `contextual-summaries` change built the summariser port, an
OpenAI-compatible implementation, the fold into embed input behind
`chunk_summaries`, and per-document summaries. Schema 6 adds `chunks.summary`,
`documents.summary` and `documents.summary_by`.

**The real corpus survived it.** With the fold off, `corpus_fingerprint`
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
a local Qwen3 endpoint, the first end-to-end run failed two documents: the
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


## One error translation on the agent surface — 2026-09-05

The first of five changes from an architecture review of the same date. The
review scoped itself to the hot spots of the last 25 commits and rated five
candidates Strong; this is the one with no dependencies, so it went first.

**What it settles.** `service-adapter-boundary` requires every adapter to
translate typed errors "in exactly one place rather than per route or per
command". REST did. The agent surface wrote the same three lines eight times, so
the rule was enforced eight times and a ninth tool would have inherited nothing.
There is now one decorator, `returns_error_payload`, and the eight blocks are
gone.

**What it fixes that was not the point.** In five of the eight tools the `try`
closed before the payload was built. `case_get_passage` asks the service for a
window *after* it closed, so a typed failure there left the tool raising — which
`mcp-tool-surface` forbids in as many words. Traced before claiming it: nothing
on `passage_window → _window_for → get_document_chunks_around` raises a
`JackRyanError` today, so **no live behaviour changed**. The hole was closed
before anything reached it.

**What was measured rather than argued.** Three mutations, each watched failing
and then reversed:

- `functools.wraps` removed → `case_list_casefiles advertises {'kwargs', 'args'}`.
  Without it a tool advertises the wrapper's own two parameters, both required,
  and every real call fails for missing arguments. Note what this is *not*: the
  degraded schema is not empty, and the structured output schema survives either
  way because the wrapper has its own return annotation. The first draft of this
  entry claimed both, and a review caught it — the corrected version is what the
  measurement actually shows.
- the wrapper made synchronous → 12 of 19 tests in `test_mcp_surface.py` fail
  with `UnexpectedToolError`. `inspect.iscoroutinefunction` does not follow
  `__wrapped__`, so the tool is run in a worker thread and hands back an
  un-awaited coroutine.
- the old narrow `try` restored on `case_get_passage` alone → the new widening
  test fails with `UnexpectedToolError: Error executing tool case_get_passage`,
  i.e. the tool raised.

**The fourth mutation is the one worth remembering, and three reviewers had to
find it.** Applying the decorator *above* `@server.tool(...)` instead of below
registers the undecorated function: the translation is still written, still
reads correctly, and never runs. Done to `case_casefile_overview` — the one tool
no test calls — **the whole 691-test suite stayed green.** The change's own spec
delta says "WHEN the agent surface's tools are inspected", and nothing inspected.

`test_every_tool_inherits_the_one_translation` now does, over what the SDK
actually registered rather than over the call sites. Re-run against the same
mutation it fails with `case_casefile_overview was registered undecorated, so
its failures never reach the one translation`, and against a synchronous wrapper
with `case_list_casefiles was registered as a synchronous tool`. That second
assertion also closes a claim the first draft of the CLAUDE.md pitfall made and
could not back: the parameters test does *not* catch a sync wrapper, because the
signature survives `wraps` regardless of async-ness.

**What it did not check.** The suite went 689 → 691 passing, same 3 skips, and
the whole diff was read hunk by hunk afterwards to confirm no mutation survived.
Not checked: any live agent harness — this was exercised only through
`server.call_tool` in-process, as the rest of the surface tests are. The two
tools whose payloads are built entirely outside the old block were not given
their own failure tests; the widening is asserted once, on `case_get_passage`,
because that is the only one with a service call out there.

---


## The casefile overview crosses the service layer — 2026-09-05

Second of the five architecture-review changes, stacked on the first because
both edit `interfaces/mcp/server.py`.

**What it settles.** `storage-seam` says "no adapter SHALL reach a store
directly". One line did — `context.store.casefile_statistics(resolved.id)` in
`case_casefile_overview`, the only place in `src/` where an adapter held a store
and the only `StorePort` method with no service caller. There is now a
`CasefileService.statistics`, and `Context.store` is declared as the port.

**Why it was reachable at all.** Three things, and the third is the one worth
remembering. There was nowhere else to go: `case_casefile_overview` has no REST
or CLI counterpart, so nothing ever forced the service method into existence.
The type permitted it: the composition root declared the concrete `SqliteStore`.
And **the tool had no test of any kind** — the only occurrence of its name
outside `src/` asserted that the analyst pack mentions it. The one call the
surface makes about corpus size, which `CLAUDE.md` notes an agent repeats as
coverage, was unexercised.

**The trap this had waiting.** The store's SQL aliases those columns `ingested`
and `expanded`; the payload calls them `documents_ingested` and
`documents_expanded`. A dataclass field named after the alias — the natural
thing to write while reading the query — gives the agent a payload with
different keys, every value still truthy, and no existing test disturbed. So the
tool's first test was written *before* the change, asserts the key set exactly,
and was watched failing on exactly that rename.

**Two guards, both watched failing.** Restoring the old store reach fails
`test_no_adapter_reaches_the_store`. Renaming one payload key fails the overview
test with `'ingested'` extra and `'documents_ingested'` missing.

**Then two reviewers took the guards apart, and both were right.** What shipped
first was materially weaker than what the commit message claimed:

- **It scanned one adapter of three.** `interfaces/` only — so a store reach in
  `server.py` (REST) or `cli.py` (CLI) was invisible, and REST is the surface
  most likely to gain a "how big is this casefile" route next. Now scans the
  whole package minus `services/`, `storage/` and `app.py`, which is an
  exemption list and therefore self-maintaining.
- **`getattr(context, "store")` and `context.casefiles._store` both passed it.**
  The second is not exotic: every adapter holds a `CasefileService`, and its
  `_store` is one attribute away — which is what someone reaches for when the
  service method they need does not exist, the exact situation that produced the
  original breach. Both are now caught, and the residual gap is stated rather
  than papered over: constructing a `SqliteStore` directly still passes.
- **The stated reason for parsing was false.** The first draft argued a grep
  would be defeated by binding the store to a name first. It would not —
  `store = context.store` contains the very string being searched for. The two
  real advantages were sitting beside it: it matches `<any expr>.store`, not
  one spelling, and cannot be tripped by a comment.
- **The overview test could not tell `documents` from `documents_ingested`.**
  On the plain `corpus` fixture both are 3, so swapping them passed. The test
  now builds a casefile holding a loose file *and* an archive, making the three
  counts genuinely distinct. **The first attempt used a two-entry archive — 4, 2
  and 2 — and a later review measured that swapping *ingested* and *expanded*
  still passed it, because two of those three are equal.** A third entry makes
  them 5, 2 and 3, and that swap now fails with `assert 3 == 2`. The sentence
  claiming "three different numbers" was false for one commit, which is the same
  overstatement this entry exists to record. That also exercises the
  `expanded` composition branch, and **the claim that `test_containers.py`
  covered it was wrong**: a reviewer replaced that whole branch with a literal
  marker string and all 694 tests stayed green.
- **`documents_by_type` was asserted only by its sum**, so collapsing it to
  `{"unknown": n}` passed. It is now compared against the real media types.

**What it did not check.** No type checker exists, so `Context.store: StorePort`
is documentation; several tests reach `context.store._db` and a checker would
flag them. The two resolves per overview call were reasoned about, not measured.
`by_type` is a mutable dict inside a frozen dataclass — consistent with
`Extraction.metadata`, and freshly built per call so nothing shared can be
corrupted, but "frozen" is shallower than it reads and `hash()` raises on it.

---


## One renderer for the two human surfaces — 2026-09-05

Third of the architecture-review changes. The CLI and the REST route described
the same three domain objects twice, and the copies had drifted: identical for a
casefile, one rounding call apart for a search hit, and **five** fields apart for
a document — the review's own report said one, and counting properly is what
turned "extract a function" into "extract a core and leave the divergence where
it belongs".

`src/jackryan/rendering.py` now holds what they share. Each adapter keeps its own
named function, calling the shared one and adding its extras — partly because
three tests import those names directly and one reports `render.__module__` on
failure, but mostly because the surfaces really do differ and the difference
should be readable where the surface is.

**One observable change: REST's JSON key order.** `casefile_id` moves from third
to tenth and the summary fields to after `created_at`. Same thirteen keys, same
values, verified by construction. Nothing asserts key order, JSON objects are
unordered by specification, and no client contract here depends on it — but it is
a public API and it belongs in the record rather than in a diff.

**Two things worth carrying forward.**

A delta-free change does not simply validate. `openspec validate` refuses it —
*"Change must have at least one delta"* — and the escape is `.openspec.yaml` with
`skip_specs: true`, which is **ignored unless the file is otherwise valid
metadata**. The first attempt set only the marker and got a second error saying
so. This is the first change here to use it.

**A review then found the sharper problem: half of one new assertion could not
fail.** `assert from_cli["score"] == round(from_rest["score"], 6)` holds whether
or not REST rounded, because rounding an already-rounded value changes nothing.
Flipping `serialize_hit` to `round_scores=True` — destroying the one difference
the parameter exists for, and silently truncating the values a remote caller
asked for — left **55 tests green**. Both surfaces are now asserted against the
service's own `hit.score`, and the fixed test fails on that mutation.

`rerank_score`'s **rounding** is now pinned too, which it was not on either
human surface. The first draft of this paragraph said it was "covered for the
first time anywhere in the suite" — false, and caught by review: the field is
already asserted on the agent payload in `test_result_shape.py` and at the
service level in `test_reranking.py`. What was uncovered was narrower and is
what this actually delivers.

The same review established behaviour preservation by measurement rather than by
reading: a differential probe over 2 casefiles × 144 document variants × 2304
search-hit variants, comparing the parent's six renderers against the new ones.
Zero value differences, zero keys gained or lost, and the REST key order as the
sole divergence.

And a process failure worth not repeating: `git checkout <file>` to undo a
mutation-test also discards the uncommitted work in that file. It happened twice
in this session. The second time the suite stayed green at 697 afterwards — the
two new parity tests passed against the *original* duplicated code, because they
assert a property the two copies already satisfied. Caught by reading `git
status`, not by the tests. **Commit before mutating, and reverse a mutation by
reversing it.**

---


## One owner for a file signature — 2026-09-05

Last of the architecture-review changes, and the only one that touches no
adapter and no seam — it is entirely inside the ingestion pipeline.

**What it settles.** `sniffing.py` and `legacy_office.py` each declared
`_OLE2_MAGIC` and `_ZIP_MAGIC`, under identical names, with no import between
them; RTF's signature was a third case, named in one and a bare literal inside
the other's table. And `router.py:47` claimed the scratch copy's name was "the
same argument and **the same constant**" as `legacy_office._copy_as_target`,
which hardcoded its own. The comment described a shared module that did not
exist. Underneath it sat the real duplication: the scratch-and-delegate shape,
written twice, with the `mkdtemp` guard and both `except` clauses
character-identical.

**Two details that had to be got right rather than assumed.**

The **import form** for the signatures. `from .sniffing import _OLE2_MAGIC`
keeps the name bound in `legacy_office`, which sixteen tests read it from.
Referencing `sniffing._OLE2_MAGIC` inline instead turns all sixteen into
`AttributeError` — watched failing, because "import the constant" and "use the
constant through its module" look equivalent and are not.

The **dotted and undotted spellings** of the scratch name. Content routing built
`f"{SCRATCH_STEM}{suffix}"` with a dotted suffix; legacy Office built
`f"source.{target}"` with an undotted target. Both give `source.xlsx`, checked
directly rather than reasoned about — this is the one place a mismatch would be
quiet, because `router._resolve` builds the same name to ask an extractor
whether it `accepts` the file, so getting it wrong hands the file to a different
extractor than the one chosen.

**The consolidation earns its keep in the teardown.** `docs/handover.md` already
records two defects found in exactly that code — a `mkdtemp` outside every `try`,
and a converter still writing into the directory after the `finally` removed it.
There is now one implementation, and the two suites test it by **opposite**
strategies: content routing globs the temp root, legacy Office patches `mkdtemp`
and watches the actual directory. Removing the `finally` fails four tests across
both files.

**What it did not check.** No behaviour was expected to change and the test count
did not move (697, 3 skipped), which is weaker evidence than it sounds: a
refactor that changes nothing observable is also a refactor no test can confirm
happened. What was confirmed is the diff and the mutations. The LibreOffice
conversion path is still only exercised out of suite by
`scripts/verify_legacy_office.py`, which does not run in CI, so the converter
branch of the new helper is covered by stubs alone.

One thing was recorded rather than fixed: the two paths still rebuild their
`Extraction` differently, and `legacy_office` drops `is_container` by omission.
Unifying that would be a behaviour change inside a change claiming none.

---

## One owner for the window rule — 2026-09-06

First of the second architecture-review batch — candidates 6 to 8, the three the
review rated *worth exploring* rather than *strong*.

**What it settles.** `services/search.py` was 671 lines answering three unrelated
questions, and marked two of the boundaries with its own section comments. The
window rule was 245 of those lines and had exactly two dependencies on everything
around it: one store call (`get_document_chunks_around`) and one setting
(`_window_max_chars`). `_slice` was a method that never said `self`.

That is now `services/windowing.py`, holding a `Windower` built from a **lookup
function rather than the store**. `StorePort` declares nineteen methods; the
window rule uses one, and depending on all nineteen meant a test of the rule had
to build a corpus to answer it. `tests/test_windowing.py` now drives the rule
against four paragraphs written out in the test — ten tests in 0.07 seconds, no
store, no ingest, no fixture.

That matters because of a failure this project already had. `CLAUDE.md` records
that three window tests once passed while proving nothing, because the corpus
they ran against had one passage per document and a window over a single passage
is the whole document. The repair at the time was a better fixture. The shape
that allowed it — inputs implied by a corpus rather than written down — is what
this change removes.

**The decision that needed measuring, not reasoning.** `MAX_RESPONSE_CHARS` moved
to the new module and is deliberately **not** re-exported from `search.py`, so a
stale reference is an `ImportError`. The reason is that
`tests/test_section_windows.py` monkeypatches it, and the widening loop reads it
off its own module at call time; an alias would let the patch bind to a name
nothing consults.

The plan claimed that test's own guard —
`assert narrowed, "the bound was never reached, so this test says nothing"` —
would catch it. **It does not**, and the only way to know was to build the
mutant. With the re-export in place and the patch repointed, the guard *passed*
and the test failed three assertions later on
`all(h.text == h.chunk.text for h in narrowed)`. `narrowed` is also set when a
neighbouring result cuts a window back, so the guard is satisfied by results the
bound never touched. The protection is real but incidental — it depends on the
fixture and reports a symptom naming neither the bound nor the patch. Recorded in
`docs/implementation-notes.md`, not fixed here.

Note also that this is the **opposite** call from `one-owner-for-a-file-signature`
a day earlier, which required `legacy_office` to import `_OLE2_MAGIC` by name so
sixteen tests could keep reading it off that module. The rule underneath both is
the same: a name that survives a move must still mean what its reader thinks. In
the signature case the readers only read, so an alias is honest; here a reader
writes, and an alias swallows the write.

**What was actually confirmed.** The 125 moved lines were diffed against their
originals and are byte-identical — checked with `difflib`, not by eye. Four
mutations were watched failing and reverted by inverse edit, never by
`git checkout`: neighbours forced empty (7 of 10 new tests red, three of them on
their own guards), the forward heading clip removed (2 red across old and new),
`narrowed` forced `False` (2 red), and the re-export described above.

One assertion in the new tests was wrong when first written — it claimed every
narrowed result falls back to its passage text — and went red immediately. That
is the same conflation the parked finding above describes, met from the other
direction.

**What three reviewers caught that ten new tests had not.** The first version of
this change was wrong in a way the whole suite was blind to, and two reviewers
found it independently.

`SearchService._window_max_chars` was kept as a field beside the `Windower` that
now holds the budget. Before the move that field *was* the live value, read on
every call; after it, nothing in `src/` read it. Measured, not argued: building
the `Windower` with a hardcoded `DEFAULT_WINDOW_MAX_CHARS`, or with the
operator's setting silently doubled, **each passed all 707 tests** — because
`tests/test_app.py:170`, the composition-root wiring test, asserted on the dead
copy. An operator setting `window_max_chars: 8000` would have got 3,000-character
windows while `jackryan status` reported 8,000. That is "stored is not effective"
in miniature, introduced by a change whose own design document reasons about the
identical hazard for `MAX_RESPONSE_CHARS` one file over.

It is fixed by making `_window_max_chars` a property reading `Windower.budget`,
so there is one value. Both mutations now fail that wiring test — `assert 3000 ==
1234` and `assert 2468 == 1234`.

The review also showed **three branches of the moved rule surviving all ten new
tests**, two of them surviving the whole suite:

- the **backward** half of `_clip_to_headings` was uncovered anywhere in the
  repository. A window could reach back across a section heading and pull the
  section above into a fenced, cited result. Now covered, with a positive
  control, both halves asserted.
- `for_results`' `kept is None` branch — the one place a result loses its window
  entirely to an earlier result, which is the single case the `narrowed` flag
  exists to disclose. Now covered, using two deliberately overlapping passages
  as a real chunker produces.
- `around`'s budget guard. Now covered by asserting the store is asked *nothing*
  when the budget cannot widen, which is a real property rather than a
  restatement of the observable.

And it caught the sharpest one: **the new bound test carried the same weak guard
this change had just parked as a finding.** `assert any(hit.narrowed ...)` reads
as proof the bound fired and is not, for the reason the parked entry gives. It
now counts how many results carry a window with and without the bound, which
only the bound can change; with the bound disabled it fails naming the bound.

Two findings were recorded rather than fixed: `test_widening_is_switched_off_by_a_budget_at_the_chunk_size`
passes at any budget, and the store lookup is captured at construction.

**What it did not check.** 697 tests passed before and 710 after, which is the
weak kind of evidence a pure move can offer: a refactor that changes nothing
observable is also one no existing test can confirm happened. The stronger
evidence is the byte-identity diff and the mutations. Nothing about window
behaviour was re-measured, because none changed — retrieval quality was not
re-run, and `scripts/evaluate_retrieval.py` does not read windows at all
(`measure()` scores `hit.chunk.text`). Pyright reported diagnostics in the editor
but resolves imports against the main checkout rather than the worktree, so its
import errors were noise; CI still runs no type checker.

---

## Three owners in the store — 2026-09-06

Second of the second architecture-review batch. `storage/sqlite.py` was 1,155
lines holding five concerns; it is now 650, with `migrations.py` (434) and
`retrieval.py` (195) beside it.

**What it settles.** Two of the extracted concerns have a published spec of their
own and one has a hazard file, `storage/CLAUDE.md`, whose opening sentence
justified its own existence by where the code sat: *"`_SCHEMA` and `_STEPS` are
defined in one file, `sqlite.py`, and adding a column or a step means editing it
— which is what loads this file."* That mechanism is exactly why the ladder went
to a new module **inside `storage/`** rather than anywhere else; editing it still
loads the rules. The sentence now says so.

The same file names three artefacts as one frozen shape — the baseline script,
the `chunk_vectors` table, and `_SIDECAR_TRIGGER` — and warns that leaving any
out is how the ladder and the create path drift apart. They were three statements
in `initialize` held together by a comment. They are now one function,
`create_baseline`.

**What was actually confirmed.** The extracted modules were built by a script
that slices the original file, not retyped. The frozen block — `_SCHEMA`,
`_Step`, `_STEPS`, `SCHEMA_VERSION` and their docstrings — diffed **196 lines
byte-identical** against `origin/develop` with `difflib`, checked before the
original was deleted. `_mention_filter` diffed **37 lines identical**. Every SQL
string literal present before the split is present after it. 710 passed, 3
skipped, unchanged from the branch point.

**Nothing is re-exported from `sqlite.py`**, the same call the window change made
for `MAX_RESPONSE_CHARS` and for the same reason. Watched: pointing
`tests/test_migrations.py`'s ladder monkeypatch back at `jackryan.storage.sqlite`
raises `AttributeError: module 'jackryan.storage.sqlite' has no attribute
'_Step'` at the line that patches it, rather than binding to a name `migrate`
does not read.

**The one thing the move broke, and it was not subtle.**
`test_the_version_is_re_read_under_the_write_lock` stages a race by replacing the
backup step with a double that finishes a whole competing migration underneath.
It used to patch **one instance** (`store._backup_before_migrating = …`), so the
competing store used the real function. Patching
`migrations.backup_before_migrating` reaches every store in the process, and the
competitor re-entered the double — `RecursionError`, on the first run. The double
now restores the original before spawning the competitor and says why.

Worth generalising: **moving a method to a module function widens the blast
radius of every test double that targets it.** Loud here; it would not have to be.

**The lock stays with the store.** The extracted functions take an open
connection and hold no lock; `SqliteStore` takes `self._lock` around each call.
`verify_meta` is the one function that used to take it itself and no longer does.
A mixin was rejected for a reason rather than a preference: `CLAUDE.md` has one
rule about locking here, and it stays legible because every acquisition is
visible in one class — where a mixin would let a later method inherit the lock
without taking it.

**What two reviewers found.** Both worked from throwaway `git archive` copies
rather than the worktree, after a previous round where a reviewer died
mid-mutation; the worktree came back byte-identical both times.

The equivalence review checked what a claim of "pure move" actually needs, by
AST extraction rather than by reading: `initialize`'s statement order, commit
point and attribute assignment all match; **14 raise-sites and 13 unique error
messages on each side**, none added, removed, or changed in interpolation, so
every rendered message is byte-identical; **26 lock sites on develop and 26
now**, with one name change.

It also falsified this change's own claim. "No behaviour changes" was too
strong: three guard clauses that ran *before* the lock now run inside it —
`search_vector`'s width check, `search_keyword`'s empty-query return,
`mention_facets`' clause building — because the whole extracted function is
inside the delegate's `with`. An `RLock` holding a length comparison, a regex and
some formatting; harmless, and now written down as "no *observable* behaviour
changes" instead of hidden behind the stronger phrase.

And it found the change had made a comment stale **in the freeze notice itself**:
`migrations.py` still said `_SIDECAR_TRIGGER` and the `chunk_vectors` statement
were "in `initialize`", when they had moved to `create_baseline` 200 lines below
the comment. Precisely the drift that notice exists to prevent. Fixed.

The silent-failure review mutated the four new seams. **All four die**: dropping
the sidecar trigger fails 7 tests with the exact symptom its own comment predicts
(`UNIQUE constraint failed on chunk_vectors`, from rowid reuse after a delete);
dropping the `chunk_vectors` create fails 125 and errors 92; a wrong `dimensions`
in the delegate fails dozens with the typed `ConfigError` reaching REST.

One is worth knowing about. Deleting **the re-read under the write lock** leaves
709 passing and fails exactly one test. That single test is the whole guard
against a re-applied `ADD COLUMN` on a concurrently-migrated store — a race the
code itself documents as real, since `docker compose up` and `docker compose run
cli` share a data directory. Recorded, not fixed.

It also confirmed something that was right by construction rather than by intent:
`initialize` reads `migrations.SCHEMA_VERSION` **by attribute**, so the ladder
test's monkeypatch reaches the store. A `from`-import there would have left that
patch half-dead. Now written into `design.md`, so a later import tidy-up has to
re-point the patch in the same change.

**What it did not check.** The test count is identical before and after, which is
the weak evidence a pure move can offer; the byte-identity diffs and the
mutations are the real evidence. `replace_chunks` was not touched and not
re-verified — it stays whole in `sqlite.py` because its single transaction across
text, FTS and vectors is the guarantee the seam exists to make. The parked bm25
finding moved file and stays parked: `search_keyword` still orders by a score
FTS5 computes over the whole index rather than the casefile.

---

## One value for corpus identity — 2026-09-07

Last of the second architecture-review batch, and the one where the review was
**wrong about the size of the problem**.

**What the review claimed, and what is actually true.** It said corpus identity
is "spread across four files, owned by nothing". Three of the four own their part
correctly: `app.py` composes from runtime-chosen values, which
`layered-configuration` *requires* happen where those values are known;
`summarising/model.py` owns the summariser's name and recipe hash, which is that
module's business; `storage/` owns the comparison and the refusal, because it
holds the recorded value. Only `config.py` had genuine duplication — the
rendering split between `Contract.fingerprint()` and `corpus_fingerprint()`, two
functions that had to agree on a separator.

**What was real.** `Context` carried two fields, `corpus_fingerprint: str` and
`summariser_name: str`, computed from the same three lines and stored apart with
nothing making them agree — and `summariser_name` had **no production reader at
all**. A grep across `src/` and `scripts/` returned only its own assignment. That
is the same shape the `casefile-statistics` change fixed: a value on a seam that
is written and never read.

`Context.identity` is now one `CorpusIdentity`, and both old names are read-only
properties over it. **The whole suite passed with zero test edits** before the new
tests were added — which is the evidence that these are views rather than a
rename, since about thirteen test sites and three production call sites read them.

**The test that could not be written before.** The rule that the `|summariser=`
component appears exactly when a summariser is folded in was a coincidence of two
functions agreeing; there was no single thing to state it about. Now:
`("|summariser=" in str(identity)) == bool(identity.summariser)`. Watched failing
by appending the component unconditionally — three tests go red, including the
golden oracle read from a real `store_meta` table.

A second test asserts the two views cannot disagree with the value they read
from. Watched failing by making `summariser_name` return `""`. Worth knowing:
`tests/test_summarising.py`'s equivalent assertion is **skipped** without an LLM
endpoint, so this is real new coverage rather than a duplicate. It also asserts
the *field* is gone rather than merely shadowed, because a re-added field would
satisfy the property test while restoring the hazard.

**What was refused.** `CorpusIdentity` gets no `parse`. `tests/test_config.py`
splits an identity with a parser of its own to prove a crafted summariser name
containing `|embedder=` cannot impersonate a component; routing that through the
class would make the check and the thing checked the same code — the same reason
the escaping oracle is a literal rather than a recomputation. Written into the
class docstring and `CLAUDE.md` so a later tidy-up does not add it.

**What review found: one guard that was never there.** Dropping `_escaped()`
around the embedder component left **all 712 tests green**. Of the three composed
values, `embed_model` and the summariser each had an impersonation test; the
embedder had none. Worse,
`test_two_different_configurations_cannot_share_one_identity` looks like it
covers this and does not — it passes with the escaping removed, because one
escaped end is enough to break that particular collision, and its own docstring
warns about exactly that shape of false coverage.

What an unescaped embedder makes reachable is the worst collision available here:
a name ending `|summariser=q` renders the identity of a corpus folded by
summariser `q`. A folded corpus would open under an unfolded configuration — bare
chunks embedded against summary-plus-chunk vectors — with `/health` reporting a
match. Reachability today is nil, since both shipped embedders name themselves
with class literals, but `EmbedderPort.name` is a bare `str` on the protocol and
the argument for escaping it is written in the code. A defence with no test is
one a later refactor deletes for free.
`test_an_embedder_name_cannot_impersonate_another_component` now closes it,
through the reader-side parser so the check and the thing checked stay different
code. The surviving mutation now fails exactly that test.

The rest held: the two new tests were each watched failing, the golden oracle is
unchanged and still fires, `docs/retrieval-baseline.json` is not in the diff, and
removing the `str()` at the store boundary is loud — `sqlite3.ProgrammingError:
Error binding parameter 2: type 'CorpusIdentity'`.

**One finding recorded, not fixed, and it is the sharper of the two.** "The fold
is on" and "the identity says the fold is on" are computed from different things:
`app.py` decides `folding` from the summariser **object**, while `__str__`
decides the `|summariser=` component from its **name** being truthy. A summariser
that exists but reports `name = ""` folds summaries into what is embedded while
recording an unfolded identity — the direction that must never happen, since that
corpus then opens under a plain configuration undetectably. Not reachable through
shipped configuration (`build_summariser` rejects an empty `summary_model`), only
through the `summariser=` injection seam that test doubles use. The repair is a
refusal at the composition root when folding is on and the name is empty, which
is a new startup refusal and belongs in a change that can argue for it.

**What it did not check.** Both golden literals are unchanged and neither file is
in the diff, but the retrieval baseline was not re-measured —
`scripts/evaluate_retrieval.py` needs model weights and does not run in CI, so
the corpus field's continuity rests on the byte-comparison alone. The parked
naming drift is untouched: `initialize(contract_fingerprint=…)`, the `store_meta`
key, and the `"contract"` field in `/health` and `jackryan status` all still say
*contract* while holding corpus identity. Renaming the stored key needs a
migration rung and the JSON field is published.

---

## A chunk begins where its text does — 2026-09-08

**What was wrong.** A chunk's stored text was `piece.strip()` while its recorded
`char_start` was the untrimmed window's start. `replace_chunks` derives a
mention's document position as `parent.char_start + mention.char_start`, so
every such position was short by the whitespace trimmed off the front of its
chunk. The identifier inventory distinguishes occurrences by `(document_id,
document_offset)` — correctly — so when two overlapping windows trimmed unequal
whitespace, one textual occurrence acquired two positions and was counted twice.

**Why it survived.** The guard that looks like it covers this states its own
offsets: `test_one_occurrence_across_two_overlapping_chunks_counts_once` builds
two `Chunk` objects by hand, so it proves the counting SQL and nothing about the
offsets the SQL counts. The chunker's own guard compared
`TEXT[char_start:char_end].strip()` with the chunk's text — trimming before
comparing, which is exactly the difference at issue — and whether any of `TEXT`'s
windows opened on whitespace was incidental anyway.

**What changed.** The chunker records the trimmed span, so
`source[char_start:char_end] == text` exactly. `replace_chunks` is untouched: the
derivation was right and the fix is to make its input true. `Windower._slice`
still trims before comparing, deliberately — every chunk row written before this
change carries the wide offsets, and an exact comparison there would return
`None` for all of them, switching windowing off for every existing corpus.

**The repair, and what it does not do.** Code alone changes no stored row.
`jackryan repair mention-offsets <casefile>` recomputes each mention's position
from the stored text — one document at a time, one write per document, only
`mentions.document_offset`, and only where it differs. It is idempotent by
construction rather than by bookkeeping, because it recomputes rather than
adjusts. A chunk whose stored text is not inside the span its own offsets name is
counted as unlocatable and skipped: a position guessed for it would resolve and
be wrong. Not a migration step, for two reasons — locating a stored text inside
its window needs Python (SQLite's `ltrim` takes an explicit character set and
would diverge from `str.strip()` on the Unicode whitespace a Ukrainian or Russian
scan is full of), and a step runs when a store is opened, which would rewrite an
operator's corpus with nobody asking.

**No real corpus has been repaired.** The 435 MB corpus still holds stale
positions, and will until an operator runs the pass and authorises it. Old
`chunks.char_start` values stay wide for ever and that is safe: windowing trims
before comparing, `case_cite`'s span reads a little wide exactly as it did, and
the repair reads the stored text rather than assuming a convention, so it
corrects a pre-fix corpus and a post-fix one identically.

**Verified, on synthetic data only.** 721 passed, 3 skipped;
`openspec validate --all --strict` 18/18; `gitleaks detect` no leaks. End to end
against a disposable store on the deterministic embedder: ingest 0 failures,
inventory `(1, 1)`, two chunks carrying the identifier, positions staled to the
pre-fix values → `(2, 1)`, repair →
`documents_examined=1, chunks_examined=2, chunks_unlocatable=0,
mentions_corrected=1` → `(1, 1)`, second run `mentions_corrected=0` and still
`(1, 1)`.

**The mutation table: nine mutations, all RED, each control GREEN.** Run through
the uv-safe harness — a copied tree keeps importing the original worktree
through the editable `.pth`, which reports GREEN for everything.

| Mutation | Verdict |
|---|---|
| chunker records `char_start=position, char_end=window_end` again | RED |
| facet counts `COUNT(DISTINCT document_offset)` | RED |
| repair uses `chunk.char_start` instead of `+ within` | RED |
| repair does `within = max(within, 0)` instead of skipping | RED |
| `recompute_mention_offsets` drops its `<>` predicate | RED |
| `_slice` refuses by span instead of by text | RED |
| `list_document_ids` gains `AND parent_id IS NULL` | RED |
| the repair iterates `for chunk in []` | RED |
| the CLI payload drops `chunks_examined` | RED |

**Two things the harness itself got wrong, worth knowing before reusing it.**
One node cannot run in a copied tree at all:
`test_repair_reports_a_corpus_that_needs_nothing` ingests the shared `corpus`
fixture, whose `.md` files go to docling, and a copied venv re-initialises that
native stack — 67 seconds and then **exit -11 after the test had passed**. The
same node in the worktree takes 2.9 seconds at exit 0, and the worktree runs all
721 tests in one process at exit 0, so it is an artefact of the harness. The
last two mutations above are therefore applied to the worktree itself, with the
original bytes held in memory and their sha256 re-checked after restore —
`git checkout` would have discarded the uncommitted work. The other seven still
run in copies, but **one pytest process per node**: nine store-opening tests in
one copied-venv process crashed at shutdown, while each alone was clean.

**One fixture defect the table caught and reading did not.** The third mutation
was GREEN on the first run. `_stale_positions` staled only the *mention* rows and
left `chunks.char_start` tight, so the repair's search found every stored text at
position zero and `chunk.char_start + within` coincided with `chunk.char_start`.
That is not a pre-fix corpus: a real one has wide chunk offsets *and* the
positions derived from them. The helper now writes both, and `_stale_corpus`
asserts that at least one chunk's offsets no longer select its own text, so the
fixture cannot silently stop being pre-fix.

**What review caught that fifteen tests had not: a whitespace-only window.** A
chunk's span no longer covers the paragraph break after it, so
`_clip_to_headings` — which cuts at the next heading's line start, two
characters later — produced a span differing from the chunk's while selecting the
same words plus `\n\n`. `_slice` asked whether the span differed, so that was
reported as a window: `is_widened` true, two spans in provenance, nothing
between them to read. Reproduced before it was believed, on one document with
one variable: pre-fix offsets → no window; post-fix → `window=(15,85)` adding
`'\n\n'`. `_slice` now compares `text[start:end].strip()` with the chunk's text,
which subsumes the span test and holds for rows of either convention.

Two consequences worth knowing. `hybrid-search`'s window requirement asserted
that "a chunk's stored text has been stripped of the whitespace its offsets
still describe" — false for new rows, so it moved in the same change; the
corrected clause says offsets select the stored text *up to surrounding
whitespace* and that every comparison of the two trims, which is the property
that lets one rule serve a store holding both conventions. And
`test_the_response_bound_drops_context_and_never_a_result` was resting on the
old behaviour: with all four of its passages as results, `_keep_clear` left each
window nothing to grow into but those blank lines, so it counted four windows
carrying no context. It now makes three of the four results and asserts that
something was widened before the bound is applied.

**What the test review caught: five assertions that could not fail, or could
not be reached.** All are now falsifiable, and each mutation is in the table
above.

- **The CLI guard did not pin `chunks_examined`.** With the repair iterating
  `for chunk in []` — never looking at a chunk — the whole suite stayed green,
  because the test asserted the three fields that are zero or unchanged and not
  the one that says whether it looked. The `corpus` fixture holds **no mention
  rows at all**, so `mentions_corrected == 0` was vacuous there. That field is
  also the spec's own requirement: a run that corrected nothing must be
  distinguishable from one that did not look.
- **The repair's walk over expansions was unguarded.** Adding
  `AND parent_id IS NULL` to `list_document_ids` — one clause, and the default
  `list_documents` right beside it *does* exclude expansions — left every test
  green while the pass silently skipped every archived document. Now covered by
  a zip of one `.txt`.
- **"No position was guessed" could not fail.** In the unlocatable test the
  stale offset is by construction `chunk.char_start + mention.char_start`, which
  is exactly what a guess clamped to zero recomputes — so the rows came out
  identical and only the counter noticed. The pass now runs once *before* the
  text is replaced, so the positions are tight and a clamped guess writes 358
  where 361 is stored. The row comparison is also placed *before* the counters,
  because pytest stops at the first failure: an assertion that never executes
  guards nothing, which is the same defect one line further on.
- **"Two documents count as two" rested on an unstated coincidence.** Its guard
  against a position-only collapse works only while both documents place the
  identifier at the same character. That was in the docstring alone; the helper
  is shared by four tests, and prefixing one file with a covering note makes the
  test pass under the collapse it exists to catch. Now asserted.
- **The vector check was replaced rather than kept.** "A search still returns
  something" cannot fail for any plausible variant of this pass. It is now a
  before-and-after comparison of `chunk_vectors` itself — which `_chunk_rows`
  cannot see, because the vectors are a virtual table rather than a column of
  `chunks`.

One claim in the plan was wrong and is worth correcting: it said `TEXT` in
`tests/test_chunking.py` could not catch the offset revert. It can, through
`char_end` — a window ending on a paragraph break carries the trailing blank
line — and it is the only test that catches a wide `char_end` beside a tight
`char_start`. Both chunking tests are load-bearing and neither is redundant.

**What it did not check.** No real corpus, no reingest, no retrieval baseline
re-measurement — the tightened offsets change no chunk boundary and no stored
text, so nothing embedded moved, but that is an argument rather than a
measurement and `scripts/evaluate_retrieval.py` needs model weights. The CLI
repair path is exercised through `cli.main` against the deterministic context;
the shipped `jackryan` entry point with no config file opens under the default
profile's real embedder and is refused on corpus identity, which is the correct
outcome rather than a working invocation.

---

## Citing a document reached by browsing — 2026-09-09

`expose-container-contents` let an agent enter an archive and read an
attachment. It could not cite one. `case_cite` takes a passage identifier, and
no tool handed one back for a document reached through `case_list_documents` —
`case_read_document` returns text, spans and provenance and no passage — so the
journey fell back to `case_search` to recover an id, behind the very mechanism
container navigation exists to route around. A child carrying no distinctive
phrase and no extracted identifier was reachable, readable and uncitable.

`cite-a-document-reached-by-listing` adds **`case_list_passages`**: a bounded,
paged, deterministically ordered index of one document's stored passages, owned
by `IngestionService.list_document_passage_page` and reachable identically from
the agent surface and from
`GET /api/casefiles/{ref}/documents/{doc}/passages`. Each row carries the
`chunk_id` that `case_get_passage` and `case_cite` already accept.

**Three things about it are decisions rather than details**, and the change's
`design.md` argues each at length.

- **It is a listing, not passage ids on the read payload** — which is what
  `docs/implementation-notes.md` had guessed the fix would be. The read bound
  lives in the agent adapter, so computing a passage index against the returned
  window means either moving that bound into the service or feeding a service
  rule with an adapter's arithmetic; citing one paragraph of a large document
  would cost a read of the region it sits in; and the payload would carry two
  independent continuations, which are ambiguous to follow — nothing in such a
  payload says which of them a bare "call again with the offset" advances, and
  the two advance different things at different rates. That objection is this
  change's own: an earlier draft attributed it to `mcp-tool-surface`, which
  actually asks for one continuation *vocabulary* across the surface rather
  than forbidding two continuations in one payload. The citation was broader
  than the text and is corrected here.
- **It carries no passage text.** `listing_payload` is unfenced on the promise
  that it holds no corpus prose, and `untrusted-content-boundary` says such a
  payload is not the one to carry prose. The cost is accepted: in a document
  with no headings the rows distinguish themselves only by position, and
  relevance is established by reading a candidate through `case_get_passage` or
  by matching an offset seen in a read against a row's span. That is asserted,
  not assumed — the journey test picks its passage exactly that way.
- **A document with no passages is answered in words.** It is reachable rather
  than theoretical: `router.extract` exempts a container from the empty-text
  refusal, so an archive holding no entries is stored with no text and no
  passages. The fixture is a real empty archive, not a deleted chunk row.

**What was verified.** `uv run --no-sync pytest -q` → **830 passed, 3 skipped**
at `733f456`, against **817 passed, 3 skipped** on `develop` at `1b4413c`.
Attributed independently of the totals, which is the figure to trust:
`git diff 1b4413c 733f456 -- tests/ | grep -cE '^\+(async )?def test_'` reports
**13 added, 0 removed**. `openspec validate --all --strict` → **18 passed, 0
failed**, one fewer than before the archive because the change is no longer an
item. `gitleaks detect --no-banner` → no leaks.

**These figures were wrong twice, and how they went wrong is the point.** They
first read 824 and "eleven new tests", measured before the twelfth test
existed. Corrected to 825 at `9f85d9f` — and then `develop` moved under the
change, gaining PR #36 (`migration-safe-location-identity`, schema rung 11) and
PR #37, which reset the baseline from 813 to 817 and the tip to 830, while a
thirteenth test arrived with the review round. The archived record and the PM
record were updated and this paragraph was not, so `develop` briefly shipped two
permanent records disagreeing about one change — in the file this document is
the one a reader is told to trust. A suite total is the wrong unit for a
permanent record: it decays on every concurrent merge, which is why the test
delta above is stated beside it and named with the commits it spans.

`docker compose build` → `jackryan:latest` built, both services, its exit code
read directly rather than through a pipe. The journey was then driven through a
real `jackryan serve-mcp`-shaped stdio process, in a separate process with the
writer closed first so the store was genuinely reopened, with `case_search`
removed from the served catalogue: 37 checks, all passing, and the citation's
span checked character-for-character against the text the harness authored.
Re-run after the `develop` merge with the same result.

**What it does not settle.** No real corpus was read or written; the change
writes nothing, embeds nothing and reads no setting that decides what a vector
means, so no existing store is refused for it and no corpus needs reingesting to
gain the capability — but that is an argument, and the only corpora exercised
are synthetic. Retrieval quality is untouched and was not re-measured: this path
ranks nothing. `characters` is read from the stored text rather than derived
from the span, which matters only on a corpus written before the chunker
recorded the trimmed span; no such corpus was constructed, so that branch is
argued rather than measured.

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
