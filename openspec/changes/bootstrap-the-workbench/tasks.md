## 1. Package and configuration

- [x] 1.1 Add `pyproject.toml` with the `jackryan` package, a `jackryan` console script, and pytest configuration.
- [x] 1.2 Implement the layered loader: `contract` + `profiles`, precedence env > file > default.
- [x] 1.3 Fail loudly on an unknown profile, naming both the requested name and the defined ones.
- [x] 1.4 Fail loudly on an unknown `contract` key, since a typo there would silently change corpus identity.
- [x] 1.5 Resolve `${VAR}` secret placeholders from the environment; treat an unset variable as fatal.
- [x] 1.6 Give the contract a stable fingerprint that changes when any value changes.
- [x] 1.7 Ship `.env.example` and `config.yaml.example` with placeholders only.

## 2. Storage seam

- [x] 2.1 Define `StorePort` as a Protocol over domain objects, with no SQL and no validation.
- [x] 2.2 Implement `SqliteStore` against it: WAL, foreign keys, schema at version 1.
- [x] 2.3 Record `schema_version` and `contract_fingerprint` in `store_meta` on first boot.
- [x] 2.4 Refuse to open a store whose recorded contract differs from the configured one.
- [x] 2.5 Guard shared state with a `threading` lock, not an asyncio one, for the M1 thread pool.
- [x] 2.6 Escape LIKE wildcards in prefix lookups so a caller cannot turn one into a scan.

## 3. Casefile service

- [x] 3.1 Create with a validated title, optional description, and a slug derived or supplied.
- [x] 3.2 Enforce slug shape; normalise case rather than rejecting it.
- [x] 3.3 Resolve a reference by full id, 8-character prefix, or slug.
- [x] 3.4 Raise on an ambiguous prefix instead of returning the first match.
- [x] 3.5 Update fields individually, preserving `created_at` and bumping `updated_at`.
- [x] 3.6 List newest first; delete by any accepted reference.

## 4. Adapters

- [x] 4.1 REST: health, and casefile create/list/get/update/delete.
- [x] 4.2 Map typed service errors onto status codes in one handler, not per route.
- [x] 4.3 CLI: `status` and `casefile create|list|show|update|delete`, with `--json`.
- [x] 4.4 Exit non-zero with the typed error code on failure.
- [x] 4.5 Keep both adapters free of domain rules.

## 5. Tests

- [x] 5.1 Config: precedence, fail-loud paths, secret resolution, fingerprint sensitivity.
- [x] 5.2 Store: contract guard in both directions, directory creation, use-before-init.
- [x] 5.3 Service: slug rules, resolution paths, ambiguity, update and delete semantics.
- [x] 5.4 REST: status-code mapping for each typed error, and a full round trip.
- [x] 5.5 CLI: output shapes, the empty-list message, and the non-zero error path.
- [x] 5.6 Whole suite green — 47 passing.

## 6. Packaging and CI

- [x] 6.1 Dockerfile with a dependency layer, a `/data` volume, and a health check.
- [x] 6.2 Compose: a long-lived service plus a scaled-to-zero `cli` service for on-demand runs.
- [x] 6.3 CI: pytest on every push and pull request.
- [x] 6.4 CI: gitleaks, because the repository is public and a leak there is permanent.
- [x] 6.5 CI: a Docker build, because a green test run does not prove the image builds.
- [x] 6.6 `.gitignore` covering `.env`, `config.yaml`, `data/`, and local agent state.

## 7. Verification

- [x] 7.1 `pytest -q` green.
- [x] 7.2 CLI smoke test: status, create, list, show by slug, and the not-found path.
- [ ] 7.3 `docker compose up -d` verified against a built image on a machine with Docker.
- [ ] 7.4 CI observed green on the pull request.
