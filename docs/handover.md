# Handover

Written for the next Claude Code session, on a machine that has the
infrastructure this project has so far been built without.

Read `CLAUDE.md` first for the rules and pitfalls, and `docs/design.md` for the
staged plan. This document covers only what those two cannot know: what is
verified, what is not, and why.

---

## Where things stand

`main` is at the merge of M3 slice 1. The prototype (M0–M2) is archived, eleven
capabilities are published in `openspec/specs/`, and 212 tests pass.

Built and merged, never yet run against real infrastructure:

- **M0** foundations — layered config, the SQLite store and its contract guard,
  casefiles, REST and CLI adapters.
- **M1** ingest and search — extraction, chunking, embedding, FTS5 + sqlite-vec
  fused by reciprocal rank.
- **M2** the agent surface — seven `case_*` tools over MCP, per-response fencing,
  profile gating, and the harness-neutral analyst pack in `analyst/`.
- **M3 slice 1** — mail (EML/MBOX/MSG), spreadsheets (XLSX/CSV/TSV), archives
  (ZIP/TAR), document hierarchy, and the expansion budget.

One change is complete but **not archived**: `hard-formats-and-containers`, all
32 tasks done. Archiving it publishes `container-extraction` and
`document-hierarchy` and folds the `document-ingestion` and
`untrusted-content-boundary` deltas into the published specs. That is the
smallest useful first task, and `/opsx:archive hard-formats-and-containers`
does it.

---

## Start here: the verification debt

Every one of the 212 tests runs against a **deterministic stand-in embedder**,
and no test has ever opened a **PDF**. The environment this was built in cannot
reach the model host, so those paths were never exercised — not skipped by
choice, unreachable.

That means the base claim of the whole project — *documents go in, an agent
works them and answers with citations that resolve* — currently rests on a
stand-in. Every milestone since M0 stacks on top of that.

```bash
python scripts/verify_model_paths.py
```

Four checks: PDF extraction through Docling's layout models, the real embedder
loading, the contract's declared width matching what the model actually
produces, and a full ingest → search → cite with real vectors. It writes to a
temporary directory and removes it; it touches no corpus of yours.

Run it before building anything else. A failure there is a real finding, not a
flaky environment — these are the only paths nothing else covers. Record the
result here, in this file, so the next session does not have to wonder.

**Then the one thing the script cannot do:** point a live agent at the surface
and confirm the tool descriptions elicit the right calls — from **two different
model vendors**, which is the acceptance criterion M2 was signed off with and
the last task in its archived `tasks.md` that never got ticked. The script
proves the surface *answers*. It cannot prove a model *chooses* correctly, and
that is the part the design actually bets on.

```bash
jackryan serve-mcp     # stdio; or reach the mounted surface at /mcp
```

Initialise the agent with `analyst/role.md` and give it a question it must
search for. What you are watching for: does it call `case_casefile_overview`
before searching, does it cite through `case_cite` rather than asserting, does
it report coverage honestly.

---

## A real defect found while writing this, not yet fixed

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

The same class of gap applies to `docling>=2.0`: extraction output is
corpus-coupled (it becomes the chunks) and the extractor version is not in the
fingerprint either. Lower severity, since a change there produces visibly
different text rather than quietly misaligned vectors.

Suggested fix, as an OpenSpec change before any further M3 work:

1. Pin `fastembed` to an exact version, and `docling` too.
2. Add the embedding library version to the fingerprint — either as an explicit
   `embed_library` contract field, or read from the installed distribution at
   fingerprint time.
3. Decide deliberately whether pooling strategy belongs in the contract as its
   own field, since it is the thing that actually changed.

Doing this **before** the first real corpus exists is nearly free. Afterwards it
forces a reingest. Right now no corpus outside development exists, which will
not be true for long.

---

## What is left in M3

Slice 1 took the leg that needed no model. The rest all do, which is why they
were deferred and why they are now unblocked:

| Leg | Notes |
|---|---|
| OCR + the VLM escalation path | Docling's quality gate: standard → OCR (eng+ukr+rus, EasyOCR default) → VLM for complex layouts and Latin-script scans. The UK/RU extraction spike belongs here. |
| Cross-encoder rerank | After RRF, before the answer. Must degrade to unranked `top_k` rather than blocking — never a hard dependency. |
| Section-window expansion | Expand a matched chunk to a coherent section for the agent to read. Needs no model; small; could be folded into any slice. |
| The summarization layer | Per-chunk contextual summaries at ingest (a config switch, off by default — it is the dominant ingest cost), then per-document map-reduce. |
| Mentions / NER | Classical NER plus pattern identifiers, as facets and pivots. Pattern extraction needs no model and could ship first. |

Recommended order: **fix the fingerprint gap**, then OCR/VLM (the biggest and
most-blocked), then rerank and section-window together as a retrieval-quality
slice, then summaries, then mentions.

PST stays last, as `docs/design.md` § 10 has it.

---

## What this environment could not do, so you should not trust it was checked

- **No model weights.** `huggingface.co` was unreachable. PDF extraction, the
  real embedder, rerank, VLM, and statistical NER were all unexercised.
- **No LLM endpoint.** Nothing that calls one has ever been run.
- **No Docker.** `docker compose up` has never been executed. CI builds the
  image, so it compiles — but no one has watched a container start, and
  `--build-arg PREFETCH_MODELS=true` has never been used.
- **No live agent.** The MCP surface is driven by tests through `call_tool` and
  by one real HTTP `initialize`. No model has ever chosen to call it.

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
- **Work on a branch, open a PR.** CI is three gates: pytest, gitleaks, and a
  Docker build. Nothing else runs — no linter, no formatter.
- **Say what is unverified.** Every PR in this repository states what it did not
  check. That habit is the reason this document can be trusted, and it is worth
  more than a clean-looking history.
