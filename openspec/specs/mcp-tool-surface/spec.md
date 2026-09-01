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
a payload, so that reading the index costs nothing beyond the index. Where a body
is widened beyond the matched passage, the widening SHALL NOT repeat text another
body already carries: the same text under two identifiers is the same cost paid
twice, and invites one passage to be counted as two pieces of evidence. Two
matched passages may still share the overlap the corpus contract gives adjacent
chunks, which is a property of how the corpus was divided rather than of this
payload.

An entry that addresses a passage SHALL carry `chunk_id` and `document_id`. An
identifier a tool returns SHALL be accepted by the tools that address that kind
of object, so one call chains into the next without the caller reconstructing
references. Widening a body SHALL NOT change what the entry's identifiers
address: they name the matched passage, which stays the unit that is read and
cited.

Not every entry addresses a passage, and the requirement is stated that way
deliberately. An inventory entry — a casefile in a listing, an identifier in a
facet with its counts — is an aggregate over the corpus rather than a reference
into it, and has no passage to name. Such an entry SHALL instead carry whatever
addresses what it describes, and SHALL carry the values a caller needs to turn it
into a search: a facet entry names an identifier that can be filtered on, which
is how an inventory becomes a pivot.

Identifiers SHALL be accepted as 8-character prefixes wherever they are taken.

An entry that carries corpus text SHALL also report how that text was obtained.
Recognition can render a word as a plausible different word, so a quotation
taken from a scan can be fluent and wrong in a way no later check catches. An
agent asked to cite what it claims cannot weigh that unless the surface tells
it, and the analyst reading the answer cannot either.

A response whose ordering could have been reranked SHALL report whether it was.
An agent cannot otherwise tell a ranking it was promised from one it was not
given, and the difference decides how much weight the order deserves. Where a
rerank score is reported it SHALL be reported as its own value beside the fusion
score, and described as comparable only within that response.

#### Scenario: The index is scannable and the body appears once

- **WHEN** a search returns results
- **THEN** a `formatted` index is present, and each passage body appears exactly once under `results`

#### Scenario: Widening does not repeat another body's text

- **WHEN** widening one result would reach into the span another result carries
- **THEN** the later entry is narrowed, and the payload repeats no text beyond the overlap the contract gives adjacent chunks

#### Scenario: Identifiers chain between tools

- **WHEN** an identifier returned by a search is passed to the passage and citation tools
- **THEN** each resolves it to the same object

#### Scenario: A passage says how its text was obtained

- **WHEN** a passage or a citation is returned
- **THEN** it reports whether the text came from a text layer, recognition, a vision model, or direct parsing

#### Scenario: A search response says whether it was reranked

- **WHEN** a search returns results
- **THEN** the payload states whether the ordering was reranked

#### Scenario: An inventory entry carries what turns it into a search

- **WHEN** a tool returns an inventory of identifiers rather than passages
- **THEN** each entry carries the value a search can be filtered by, and no entry claims a passage it does not address

### Requirement: Reads are bounded, and truncation is explicit

A tool that reads document text SHALL bound what it returns. When a read is cut
short it SHALL say so in the payload and SHALL carry the position to continue
from, so that a document which ends and a read which stopped are distinguishable.

Result counts SHALL be bounded, and the context added to them SHALL be bounded
across the response as a whole. A count bound alone was sufficient only while a
result was one chunk; once a result may be widened, a permitted number of results
no longer implies a permitted quantity of text. When that bound stops a result
being widened, the payload SHALL say so. No result SHALL be dropped to meet it:
a caller told it received ten passages must have received ten.

An out-of-range argument SHALL be clamped rather than refused, because this
surface has no request-validation layer above it and an over-large limit is a
harmless mistake.

A tool that returns a passage together with its surroundings SHALL describe the
span it actually returned, not the span of the passage alone. A payload whose
declared position covers less than the text it carries cannot be checked against
the source by hand.

#### Scenario: A long document reports truncation and where to continue

- **WHEN** a document longer than the read bound is read
- **THEN** the payload marks itself truncated and carries the offset to continue from

#### Scenario: An over-large limit is clamped

- **WHEN** a search is asked for more results than the surface permits
- **THEN** it returns the permitted maximum rather than an error

#### Scenario: Widening stops when the response bound is reached

- **WHEN** widening the results of one search would take the response past its text bound
- **THEN** later results carry their matched passage alone and state that they were narrowed, and no result is dropped

#### Scenario: A passage returned with its surroundings declares the whole span

- **WHEN** a tool returns a passage together with the text around it
- **THEN** the payload's declared span covers all the text it returned, and separately identifies the matched passage within it

### Requirement: A failing tool returns a typed payload rather than raising

A tool SHALL return `{"error": <code>, "message": <text>}` on failure, using the
same codes the service layer raises. It SHALL NOT raise, because an agent can
act on a returned value and can only retry a transport failure.

#### Scenario: An unknown reference returns a typed error

- **WHEN** a tool is called with a reference that matches nothing
- **THEN** it returns an error payload carrying the `not_found` code, and does not raise
