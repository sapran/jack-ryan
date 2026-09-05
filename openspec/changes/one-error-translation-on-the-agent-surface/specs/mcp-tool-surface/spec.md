## MODIFIED Requirements

### Requirement: A failing tool returns a typed payload rather than raising

A tool SHALL return `{"error": <code>, "message": <text>}` on failure, using the
same codes the service layer raises. It SHALL NOT raise, because an agent can
act on a returned value and can only retry a transport failure.

This SHALL hold however far through its work a tool fails, not only while it is
resolving its arguments. A tool builds its payload after the calls it awaited,
and may reach the service layer again while doing so; a translation covering
only the opening calls leaves those later failures raising, which is the same
defect in the place it is hardest to notice.

#### Scenario: An unknown reference returns a typed error

- **WHEN** a tool is called with a reference that matches nothing
- **THEN** it returns an error payload carrying the `not_found` code, and does not raise

#### Scenario: A failure while building the payload is still a payload

- **WHEN** a service call made after a tool's opening calls raises a typed error
- **THEN** the tool returns an error payload carrying that code, and does not raise
