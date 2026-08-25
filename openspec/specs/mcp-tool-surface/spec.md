# mcp-tool-surface Specification

## Purpose

Defines the agent-facing surface: how the corpus is reached, what a result
looks like, how identifiers chain from one call into the next, and how a tool
reports failure to a caller that can only act on a returned value.

## Requirements

### Requirement: The corpus is reachable by an agent through a named tool surface

The instance SHALL expose an MCP surface whose tools are named with a common
`case_` prefix. It SHALL be reachable both in-process on the existing
application and over stdio, so an agent can attach to a running instance or
launch one.

The surface SHALL carry instructions describing the working method — establish
what exists, survey its size and shape, search, pivot, read last, cite — rather
than only enumerating tools. Tool names SHALL be treated as a contract, because
saved prompts and shipped skills name them.

#### Scenario: The surface advertises its tools

- **WHEN** an agent lists the available tools
- **THEN** every advertised tool's name begins with `case_`, and instructions describing the method are present

#### Scenario: The surface is reachable over stdio

- **WHEN** the stdio entry point is invoked
- **THEN** an agent can complete a tool listing over it

### Requirement: A result separates its index from its bodies and carries chaining identifiers

A list-shaped result SHALL carry a compact `formatted` index for scanning and a
`results` array holding the entries. A passage body SHALL appear exactly once in
a payload, so that reading the index costs nothing beyond the index.

Every result entry SHALL carry `chunk_id` and `document_id`. An identifier a
tool returns SHALL be accepted by the tools that address that kind of object, so
one call chains into the next without the caller reconstructing references.

Identifiers SHALL be accepted as 8-character prefixes wherever they are taken.

#### Scenario: The index is scannable and the body appears once

- **WHEN** a search returns results
- **THEN** a `formatted` index is present, and each passage body appears exactly once under `results`

#### Scenario: Identifiers chain between tools

- **WHEN** an identifier returned by a search is passed to the passage and citation tools
- **THEN** each resolves it to the same object

### Requirement: Reads are bounded, and truncation is explicit

A tool that reads document text SHALL bound what it returns. When a read is cut
short it SHALL say so in the payload and SHALL carry the position to continue
from, so that a document which ends and a read which stopped are distinguishable.

Result counts SHALL be bounded. An out-of-range argument SHALL be clamped rather
than refused, because this surface has no request-validation layer above it and
an over-large limit is a harmless mistake.

#### Scenario: A long document reports truncation and where to continue

- **WHEN** a document longer than the read bound is read
- **THEN** the payload marks itself truncated and carries the offset to continue from

#### Scenario: An over-large limit is clamped

- **WHEN** a search is asked for more results than the surface permits
- **THEN** it returns the permitted maximum rather than an error

### Requirement: A failing tool returns a typed payload rather than raising

A tool SHALL return `{"error": <code>, "message": <text>}` on failure, using the
same codes the service layer raises. It SHALL NOT raise, because an agent can
act on a returned value and can only retry a transport failure.

#### Scenario: An unknown reference returns a typed error

- **WHEN** a tool is called with a reference that matches nothing
- **THEN** it returns an error payload carrying the `not_found` code, and does not raise
