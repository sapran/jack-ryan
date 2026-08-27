# CLAUDE.md

Guidance for Claude Code when working in **Jack Ryan**.

Human-facing design and the staged plan: `docs/design.md`. Read it before
proposing anything — it carries the nine design principles, the ten locked
decisions, and which milestone each capability belongs to.

**`docs/handover.md` records what is verified and what is not.** Read it before
trusting that anything here has been run: every test still uses a stand-in
embedder and none opens a PDF, so `scripts/verify_model_paths.py` is the only
thing covering the model-dependent paths — it passed 6/6 on 2026-08-26, and the
handover says exactly what that does and does not settle. What is known but
deliberately unfixed lives in `docs/implementation-notes.md`.

## What this is

A self-hosted investigation workbench. An analyst drops document dumps into
casefiles and works them beside an agentic AI assistant that reaches the corpus
over MCP. Runs local-first: one container, one SQLite file.

**Delivery is prototype-first.** The prototype is M0–M2 and proves one loop:
ingest documents, then have the assistant work the corpus over MCP and answer
with resolvable citations. Depth (OCR, hard formats, retrieval quality,
summaries, mentions) is M3. Analysis (attributed writes, the operating picture,
the roster split, reports) is M4. Everything else is beyond.

Current state: **M3 slice 1 shipped, and the prototype's verification debt is
cleared.** Six changes are archived — M0, M1 and M2, then
`hard-formats-and-containers`, `contract-covers-embedding-library` and
`corpus-identity-covers-the-embedder` — and thirteen capabilities are published
in `openspec/specs/`. No change is in flight and no archived task is left
unticked: compose wiring and the two-vendor agent test both ran, and corpus
identity now covers the embedding library, the module actually imported, and
which embedder produced the vectors.

The model-dependent M3 legs (OCR/VLM, rerank, summaries, statistical NER) are
next; the assistant writing back is M4. Retrieval quality has never been
measured, which matters most for the rerank leg — see `docs/handover.md`.

What remains unverified is recorded in `docs/handover.md`, and what is known
but deliberately unfixed is in `docs/implementation-notes.md` — read both before
trusting that something works.

## Rules

### OpenSpec governs every substantive change

Explore → propose → apply → sync/archive. Config at `openspec/config.yaml`,
active proposals in `openspec/changes/<slug>/`, published specs in
`openspec/specs/<capability>/spec.md`. Do not plan substantive code changes
without a corresponding OpenSpec change.

A proposal that pulls deferred work forward must say why the prototype cannot
be proven without it.

### Public-repo safety

This repository is **public**. Every tracked file and commit message is
world-readable and permanent.

- **No secrets in tracked files, ever.** Real values live only in the
  gitignored `.env` and `config.yaml`. The tracked templates carry placeholders
  only.
- **No infrastructure fingerprints.** No real hostnames, private IPs, tailnet
  names, or personal paths (`/Users/<name>`, `/home/<name>`) — in code, docs,
  examples, commit messages, or sample output. Scrub before committing.
- **No real corpus contents.** No actual document titles, filenames, document
  ids, or case material. Test fixtures use synthetic data only.
- **Before committing, grep for leaks:** `sk-`, `hf_`, `AKIA`, `ghp_`,
  `-----BEGIN`, `.ts.net`, `/Users/`, `/home/`.

### Business logic belongs in the service layer

`src/jackryan/services/` owns every rule. REST (`server.py`), CLI (`cli.py`),
and later MCP are **thin adapters** that translate and nothing more. A rule
enforced in an adapter is a second, divergent definition of the domain — and
the MCP surface has no request-validation layer of its own to fall back on.

Adapters translate typed errors from `errors.py`; the service layer never
raises adapter-specific exceptions.

### Evidence is immutable

Originals and extracted text are read-only inputs. Derived work — tags, notes,
judgements, the operating picture, reports — lives beside the evidence and
never overwrites it. This holds for code as much as for the assistant.

### Corpus identity is guarded, not assumed

The `contract:` block (chunk size, overlap, embedder family, dimensions, and the
embedding library version) is corpus-coupled. Changing any value changes the
fingerprint, and the store refuses to open a corpus built under a different one.
Never weaken that guard to make a test pass — it is the only thing standing
between a config typo and a silently corrupted corpus.

**Corpus identity is the contract plus `profiles.<name>.embedder`, not the
contract alone.** That one profile field is the exception to profiles being safe
to change: it selects which implementation produces the vectors. It is composed
into the recorded identity at the composition root rather than copied into the
contract, because two copies of one setting can disagree. Treating identity as a
contract-only property is what let a deterministic corpus open under a
real-model configuration — real vectors compared against hash vectors of the
same width, which nothing downstream can detect.

## Pitfalls

- **Never remove the `cli` service from `docker-compose.yml`.** It exists with
  `replicas: 0` on purpose, for `docker compose run --rm cli ...`. A refactor
  that "cleans it up" breaks the CLI workflow.
- **Locks are `threading`, not `asyncio`.** The server is async but ingestion
  runs in a thread pool from M1; an asyncio lock would not hold across worker
  threads.
- **CI runs three gates and no more**: pytest, gitleaks, and a Docker build.
  There is no linter or formatter gate — a green PR means those three passed.
- **The CLI calls services directly, not HTTP.** That is deliberate, so it
  works against a stopped instance.
- **Never let the deterministic embedder become a fallback.** It produces
  vectors with no meaning. It is selected only by `embedder: deterministic`, and
  a real embedder that fails to load must stop ingestion rather than degrade to
  it — silently storing meaningless vectors is unrecoverable without a reingest.
- **Fencing is a convention, not a sandbox.** Corpus text returned to an agent
  is nonce-fenced and marked untrusted, and a model that ignores it is not
  prevented from anything. The controls that do not depend on the model are the
  read-only profile and the service layer's authority. Never describe the fence
  as enforcement.
- **Tool names are a contract.** Saved prompts and the shipped analyst pack name
  the `case_*` tools; renaming one breaks them.
- **Docling PDF extraction needs models on first use.** Markdown, HTML, DOCX and
  PPTX parse offline. Build the image with `--build-arg PREFETCH_MODELS=true`
  for a container that is offline from its first run.
- **Never set `ocr_engine: auto`, and never re-admit it.** docling's `auto`
  picks the engine by host operating system, forwards only `mode` to what it
  picked — dropping the configured language — and, finding no engine, logs a
  warning and yields the pages unchanged. It is refused at configuration load.
  Extracted text becomes the corpus, so an engine chosen by the host makes the
  corpus a property of the machine that ingested it.
- **A recognition engine that cannot be built stops the ingest.** It never falls
  back to another engine and never falls back to reading pages without
  recognition: a scan read without recognition is an empty document, which looks
  ingested. The check runs once at the start of an ingest run — not at process
  start, which would charge every `jackryan status` seconds and a model download.
- **Constructing a `DocumentConverter` verifies nothing.** It builds its
  pipelines lazily, so one made with a nonsense recognition language returns
  quite happily and fails on the first scan. `check_engine` calls
  `initialize_pipeline`, which builds the model. Do not "simplify" it back.
- **`text_source` is a disclosure, not a guarantee.** It says which rung produced
  a document's text so an analyst can weigh an OCR'd quotation differently. It
  does not make that text correct — recognition renders a word as a plausible
  different word, and nothing downstream detects it.
- **Extraction settings are profile, not contract, and that is a deliberate
  trade.** Changing the recognition engine or language does not invalidate a
  corpus, so nothing refuses a corpus built under different settings. The
  per-document `text_source` is what makes a later re-extraction targetable, and
  it is the whole compensation for that gap.
- **A container extractor never routes what it holds.** It yields entries and
  stops; the pipeline routes them. That is what makes a format supported inside
  an archive exactly when it is supported outside one.
- **Container entries are yielded one at a time, never returned together.** All
  at once puts a whole archive in memory before the expansion budget can refuse
  any of it — which makes the byte ceiling unreachable in the case it exists for.
- **`containment_path` is display; `identity_path` is identity.** A folder walk
  records a path but keeps content-only identity, so two copies in one folder
  are one document. An expansion's path *is* part of its identity, so the same
  attachment on two messages is two documents — which message carried it is
  itself evidence.
- **A descendant never outlives its container.** `documents.parent_id` carries
  `ON DELETE CASCADE`, verified to recurse through nesting and to fire the chunk
  trigger at every level. Never replace it with code that has to remember.

## Commands

```bash
# Setup
uv venv --python 3.12 && uv pip install -e ".[dev]"

# Tests — the same gate CI runs
pytest -q

# Run the API
uvicorn jackryan.server:create_app --factory --reload --port 8500

# CLI
jackryan status
jackryan casefile create "Some Investigation" --description "..."
jackryan casefile list
jackryan casefile show <id|short-id|slug>
jackryan ingest <casefile> <file-or-folder>
jackryan search <casefile> "a question"
jackryan document list <casefile> [--expanded]
jackryan serve-mcp                      # the agent surface over stdio

# Docker
docker compose up -d --build
docker compose run --rm cli casefile list
```

## Layout

- `src/jackryan/config.py` — layered config: corpus `contract` + infra `profiles`
- `src/jackryan/app.py` — composition root; the only place wiring happens
- `src/jackryan/storage/port.py` — `StorePort`, the one deliberate abstraction
- `src/jackryan/storage/sqlite.py` — the single-file store and its contract guard
- `src/jackryan/ingestion/` — format router, extractors, chunker, container and
  mail and spreadsheet readers, the expansion budget
- `src/jackryan/embedding/` — embedder port, the real model, and the test double
- `src/jackryan/services/` — all business logic
- `src/jackryan/server.py`, `cli.py` — thin adapters
- `src/jackryan/interfaces/mcp/` — the agent surface: tools, shapes, fencing,
  profiles, the annotations table
- `analyst/` — the harness-neutral analyst role and the analytic spine
