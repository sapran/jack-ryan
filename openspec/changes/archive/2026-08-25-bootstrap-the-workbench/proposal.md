## Why

`docs/design.md` describes a system; the repository holds only that document.
Nothing runs, nothing is testable, and every later milestone would otherwise
begin by inventing the same scaffolding.

M0 is the milestone that makes the repository real. It is deliberately the
least interesting one: no documents, no search, no MCP surface, no assistant.
What it produces is a running instance with the load-bearing seams in place
and a green CI gate, so M1 can add ingestion without also having to settle how
configuration is layered, where business logic lives, or how persistence is
reached.

Casefile CRUD is the vehicle. It is the smallest slice of the domain that
exercises the whole vertical — config, store, service layer, and two adapters
— and it is needed by everything that follows, since a casefile is the scope
every document, tag, and report belongs to.

## What Changes

**Current behavior.** The repository contains `README.md` and
`docs/design.md`. There is no package, no test suite, no CI, and no way to run
anything.

**Desired behavior.** `docker compose up` yields a healthy instance;
`jackryan casefile create` works; `pytest` passes; three CI gates run on every
push.

- Add the `jackryan` Python package under `src/`, installable and importable.
- Add **layered configuration**: a corpus-coupled `contract` block and
  swappable infrastructure `profiles`, with precedence real environment
  variable > `config.yaml` > built-in default, failing loudly on an unknown
  profile, an unknown contract key, or an unresolvable secret placeholder.
- Add **`StorePort`** and its SQLite implementation, including the store-meta
  guard that refuses to open a store built under a different contract.
- Add the **casefile service**: create, list, resolve, update, delete, with
  slug rules and reference resolution by full id, 8-character id prefix, or
  slug.
- Add two **thin adapters** over that service: a FastAPI REST surface and an
  `argparse` CLI, neither holding a rule of its own.
- Add the **test suite** (47 tests) and three **CI workflows**: pytest,
  gitleaks, and a Docker build that proves the image actually builds.
- Add **Docker packaging**: a Dockerfile and a compose file with a long-lived
  service plus a scaled-to-zero `cli` service for on-demand invocations.

Deliberately absent, because M0 is not the milestone for them: documents,
chunking, embeddings, search, the MCP surface, the analyst pack, attributed
writes, the operating picture, and reports.

## Capabilities

### New Capabilities

- `layered-configuration` — the contract/profile split, precedence, and
  fail-loud behavior.
- `storage-seam` — `StorePort` as the single persistence boundary, and the
  corpus-identity guard the store enforces.
- `casefile-lifecycle` — what a casefile is, how it is named, and how a
  reference to one resolves.
- `service-adapter-boundary` — business logic lives in the service layer;
  adapters translate and nothing more.

### Modified Capabilities

None. This is the first change in the repository.

## Impact

- **New**: `src/jackryan/` (9 modules), `tests/` (6 files, 47 tests),
  `pyproject.toml`, `Dockerfile`, `.dockerignore`, `docker-compose.yml`,
  `.gitignore`, `.env.example`, `config.yaml.example`, three workflows under
  `.github/workflows/`, and `openspec/` scaffolding.
- **Modified**: none.
- **Risk**: low. Nothing depends on this repository yet, and the surface it
  introduces is the one every later milestone was already going to need.

## Still deferred

**The `contract` block declares values M0 does not consume.** `chunk_size`,
`chunk_overlap`, `embed_model_family`, and `embed_dimensions` are validated
and fingerprinted, but nothing chunks or embeds until M1. They are declared
now rather than later because the fingerprint guard has to exist *before* a
corpus does — retrofitting it after documents are stored means the first
corpus was built with no identity recorded, and no way to prove what rules
produced it.
