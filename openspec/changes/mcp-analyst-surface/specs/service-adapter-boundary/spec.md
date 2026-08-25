## MODIFIED Requirements

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
