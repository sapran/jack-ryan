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

Current state: **M3 slice 1 built — containers and the hard formats.** The
prototype (M0–M2) is archived and eleven capabilities are published in
`openspec/specs/`. In flight: `hard-formats-and-containers` — mail,
spreadsheets, archives, document hierarchy, and the expansion budget. The
model-dependent M3 legs (OCR/VLM, rerank, summaries, statistical NER) follow
separately; the assistant writing back is M4.

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
