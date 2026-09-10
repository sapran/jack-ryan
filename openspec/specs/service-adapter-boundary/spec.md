# service-adapter-boundary Specification

## Purpose

Defines where business logic lives and what an adapter may do. Every rule is
written once in the service layer; REST, CLI, and the agent surface translate
and nothing more, so no surface can enforce a different version of the domain.
Where the two human surfaces present the same value they also share one
rendering of it; the agent surface renders its own, because its payloads are
fenced and shaped for a model rather than for a person.

## Requirements

### Requirement: Business logic lives in the service layer

All domain rules — validation, reference resolution, and the shape of what may
be stored — SHALL live in `src/jackryan/services/`. An adapter SHALL NOT
enforce, duplicate, or relax a rule.

The agent-facing surface is why this is strict rather than tidy. That adapter
has no request-validation layer of its own and is driven by a model rather than
by a caller who read the documentation, so every rule it needs enforced has to
already be enforced beneath it — which is only true if no adapter is permitted
its own copy.

#### Scenario: Adapters carry no validation

- **WHEN** the REST, CLI, and agent adapters are inspected
- **THEN** none validates input or resolves references itself; all delegate to the service layer

#### Scenario: Every adapter inherits the same rule

- **WHEN** the same invalid input is submitted through each adapter
- **THEN** each reports the same typed failure, because one rule produced it

### Requirement: The service layer raises typed errors that adapters translate

The service layer SHALL raise typed errors — validation, not-found, ambiguous
reference, conflict, and configuration — and SHALL NOT raise adapter-specific
exceptions. Every adapter SHALL translate them into its own idiom in exactly one
place rather than per route or per command, so a new route or command inherits
the mapping instead of restating it.

One place means one, and it is checkable. An adapter that repeats the same
translation once per entry point satisfies the letter of "every failure is
translated" while failing this requirement: the rule is then enforced as many
times as there are entry points, and a new one inherits nothing. The agent
surface is where this matters most, because it has no request-validation layer
above it and its entry points are added one tool at a time.

#### Scenario: REST maps each typed error to a status code

- **WHEN** the service layer raises a validation, not-found, or conflict error
- **THEN** the REST adapter responds 400, 404, or 409 respectively, with the error code in the body

#### Scenario: The CLI reports the typed code and exits non-zero

- **WHEN** a command fails with a typed error
- **THEN** the CLI prints the error code and message to stderr and exits non-zero

#### Scenario: The agent surface translates through one place, not one per tool

- **WHEN** the agent surface's tools are inspected
- **THEN** every tool translates a typed error through the same single translation, so a tool added without restating it still returns a typed payload

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
