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

`main` is at the merge of M3 slice 1. The prototype (M0–M2) and M3 slice 1 are
both archived, thirteen capabilities are published in `openspec/specs/`, and 212
tests pass.

Built and merged, and — since 2026-08-26 — exercised against real model
infrastructure for the first time; see the verification section below:

- **M0** foundations — layered config, the SQLite store and its contract guard,
  casefiles, REST and CLI adapters.
- **M1** ingest and search — extraction, chunking, embedding, FTS5 + sqlite-vec
  fused by reciprocal rank.
- **M2** the agent surface — seven `case_*` tools over MCP, per-response fencing,
  profile gating, and the harness-neutral analyst pack in `analyst/`.
- **M3 slice 1** — mail (EML/MBOX/MSG), spreadsheets (XLSX/CSV/TSV), archives
  (ZIP/TAR), document hierarchy, and the expansion budget.

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

**This is a breaking change, by design.** The fingerprint string changed, so any
corpus built before it — including the one built during the 6/6 run recorded
above, whose vectors are mean-pooled — is refused until reingested. That is the
correct outcome and the reason for doing it now: no corpus outside development
exists. Afterwards it would have cost a forced reingest of real evidence.

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

- **~~No model weights.~~ Settled 2026-08-26.** PDF extraction and the real
  embedder are now exercised — see the verification section above. **Rerank,
  VLM, and statistical NER remain unexercised**, because no code for them
  exists yet.
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

  Still unused: `--build-arg PREFETCH_MODELS=true`, so no offline-from-first-run
  image has ever been built — see the note in `docs/implementation-notes.md`
  about `check_real_embedder`, which would fail spuriously in exactly that image.
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
