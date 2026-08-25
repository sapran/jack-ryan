# service-adapter-boundary Specification

## Purpose

Defines where business logic lives and what an adapter may do. Every rule is
written once in the service layer; REST and CLI translate and nothing more, so
no surface can enforce a different version of the domain.

## Requirements

### Requirement: Business logic lives in the service layer

All domain rules — validation, reference resolution, and the shape of what may
be stored — SHALL live in `src/jackryan/services/`. An adapter SHALL NOT
enforce, duplicate, or relax a rule.

The rule is stricter than it looks. An agent-facing surface has no
request-validation layer of its own, so any rule it needs enforced has to be
enforced beneath it — which is only true if no surface is permitted its own
copy. `docs/design.md` § 5 records that surface; this requirement is what makes
adding it safe.

#### Scenario: Adapters carry no validation

- **WHEN** the REST and CLI adapters are inspected
- **THEN** neither validates input nor resolves references itself; both delegate to the service layer

### Requirement: The service layer raises typed errors that adapters translate

The service layer SHALL raise typed errors — validation, not-found, ambiguous
reference, conflict, and configuration — and SHALL NOT raise adapter-specific
exceptions. Every adapter SHALL translate them into its own idiom in exactly one
place rather than per route or per command, so a new route or command inherits
the mapping instead of restating it.

#### Scenario: REST maps each typed error to a status code

- **WHEN** the service layer raises a validation, not-found, or conflict error
- **THEN** the REST adapter responds 400, 404, or 409 respectively, with the error code in the body

#### Scenario: The CLI reports the typed code and exits non-zero

- **WHEN** a command fails with a typed error
- **THEN** the CLI prints the error code and message to stderr and exits non-zero

### Requirement: The CLI reaches services directly

The CLI SHALL call the service layer in-process rather than over HTTP, so it
works against an instance that is not serving. This is a deliberate divergence
from the REST adapter, which exists to serve remote callers.

#### Scenario: The CLI runs with no server process

- **WHEN** a CLI command runs and no server is listening
- **THEN** the command succeeds against the store directly

### Requirement: Composition happens in one place

Wiring configuration to a store to the service layer SHALL happen in a single
composition root. An adapter SHALL obtain a configured context from it rather
than assembling its own.

#### Scenario: Adapters share one wiring

- **WHEN** the REST and CLI adapters start
- **THEN** both obtain their services from the same composition root
