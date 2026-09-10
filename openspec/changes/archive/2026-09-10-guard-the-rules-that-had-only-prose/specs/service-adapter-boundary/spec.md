## MODIFIED Requirements

### Requirement: Business logic lives in the service layer

All domain rules — validation, reference resolution, the shape of what may be
stored, and which of several grounds produced a decision — SHALL live in
`src/jackryan/services/`. An adapter SHALL NOT enforce, duplicate, relax, or
re-derive a rule or a decision the service layer has already made.

The agent-facing surface is why this is strict rather than tidy. That adapter
has no request-validation layer of its own and is driven by a model rather than
by a caller who read the documentation, so every rule it needs enforced has to
already be enforced beneath it — which is only true if no adapter is permitted
its own copy.

Re-derivation is the quiet form of the same fault. An adapter that recomputes
an answer it was handed is not translating a decision, it is making a second
one from the same inputs, and the two are only equal until one of them is
edited. Nothing fails when they diverge: each surface is internally consistent
and answers one question differently from the other, which is exactly what this
requirement exists to prevent. Where the service layer has decided something,
an adapter reads the decision and chooses only how to say it.

#### Scenario: Adapters carry no validation

- **WHEN** the REST, CLI, and agent adapters are inspected
- **THEN** none validates input or resolves references itself; all delegate to the service layer

#### Scenario: Every adapter inherits the same rule

- **WHEN** the same invalid input is submitted through each adapter
- **THEN** each reports the same typed failure, because one rule produced it

#### Scenario: Whether a page is empty because it began past the end is the page's own answer

- **WHEN** an adapter explains why a page it was handed carries no rows
- **THEN** it reads the answer the page itself carries rather than recomputing it from that page's offset and totals, so no two surfaces can answer one question differently

#### Scenario: Which ground produced an unknown verdict is decided once

- **WHEN** the service layer reports a coverage verdict it could not establish
- **THEN** it also names which of the grounds produced that verdict, and the adapter selects only the wording; an adapter applying a precedence of its own among those grounds is a second definition of the verdict

## ADDED Requirements

### Requirement: The human surfaces share one rendering of what they agree on

Where the CLI and the REST API present the same value, that value SHALL be
produced in exactly one place that both call, and each surface SHALL add only
what is its own on top of it. The agent-facing surface SHALL NOT be obliged to
use those renderings: its payloads are fenced, marked untrusted, and shaped for
a model rather than for a person, so it renders its own.

Two hand-written renderings of one value are two definitions of what that value
is called and what it contains. They agree on the day they are written and
diverge on the day one of them is extended, and the divergence shows up as a
field a person finds under one surface and not the other rather than as a
failure. That the agent surface is excluded is a decision, not an omission —
holding it to the human shape would make one of the two shapes wrong.

#### Scenario: A value shown by both human surfaces is built once

- **WHEN** the CLI and the REST API both present the same value
- **THEN** both obtain it from a single shared rendering, so neither can name or compose it differently from the other

#### Scenario: A surface-specific extra stays with that surface

- **WHEN** one human surface must present something the other does not
- **THEN** that extra is added by that surface alone and the shared rendering is left unchanged, rather than growing a field one surface never shows

#### Scenario: The agent surface renders its own payloads

- **WHEN** the agent-facing surface presents the same underlying value
- **THEN** it is free to render it in its own shape, and the shared rendering imposes no obligation on it
