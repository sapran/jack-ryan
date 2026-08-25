# CLAUDE.md

Guidance for Claude Code when working in **Jack Ryan**.

Human-facing design and the staged plan: `docs/design.md`. Read it before
proposing anything — it carries the nine design principles, the ten locked
decisions, and which milestone each capability belongs to.

## What this is

A self-hosted investigation workbench. An analyst drops document dumps into
casefiles and works them beside an agentic AI assistant that reaches the corpus
over MCP. Runs local-first: one container, one SQLite file.

**Delivery is prototype-first.** The prototype is M0–M2 and proves one loop:
ingest documents, then have the assistant work the corpus over MCP and answer
with resolvable citations. Depth (OCR, hard formats, retrieval quality,
summaries, mentions) is M3. Analysis (attributed writes, the operating picture,
the roster split, reports) is M4. Everything else is beyond.

Current state: **M1 built** — documents are ingested, chunked, embedded, and
searchable. M0's foundations (config, storage seam, casefile service, REST and
CLI) are archived and published in `openspec/specs/`. No MCP surface yet: that
is M2, and it completes the prototype.

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

The `contract:` block (chunk size, overlap, embedder family, dimensions) is
corpus-coupled. Changing any value changes the fingerprint, and the store
refuses to open a corpus built under a different one. Never weaken that guard
to make a test pass — it is the only thing standing between a config typo and a
silently corrupted corpus.

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
- **Docling PDF extraction needs models on first use.** Markdown, HTML, DOCX and
  PPTX parse offline. Build the image with `--build-arg PREFETCH_MODELS=true`
  for a container that is offline from its first run.

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
jackryan document list <casefile>

# Docker
docker compose up -d --build
docker compose run --rm cli casefile list
```

## Layout

- `src/jackryan/config.py` — layered config: corpus `contract` + infra `profiles`
- `src/jackryan/app.py` — composition root; the only place wiring happens
- `src/jackryan/storage/port.py` — `StorePort`, the one deliberate abstraction
- `src/jackryan/storage/sqlite.py` — the single-file store and its contract guard
- `src/jackryan/ingestion/` — format router, extractors, chunker
- `src/jackryan/embedding/` — embedder port, the real model, and the test double
- `src/jackryan/services/` — all business logic
- `src/jackryan/server.py`, `cli.py` — thin adapters
- `src/jackryan/interfaces/` — reserved for the MCP surface (M2)
