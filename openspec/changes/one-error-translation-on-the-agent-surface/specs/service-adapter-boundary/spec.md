## MODIFIED Requirements

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
