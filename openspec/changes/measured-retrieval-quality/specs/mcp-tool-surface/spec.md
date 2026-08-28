## MODIFIED Requirements

### Requirement: A result separates its index from its bodies and carries chaining identifiers

A list-shaped result SHALL carry a compact `formatted` index for scanning and a
`results` array holding the entries. A passage body SHALL appear exactly once in
a payload, so that reading the index costs nothing beyond the index. Where result
bodies are widened beyond the matched passage, no part of one body SHALL be
repeated in another: the same text under two identifiers is the same cost paid
twice, and invites one passage to be counted as two pieces of evidence.

Every result entry SHALL carry `chunk_id` and `document_id`. An identifier a
tool returns SHALL be accepted by the tools that address that kind of object, so
one call chains into the next without the caller reconstructing references.
Widening a body SHALL NOT change what the entry's identifiers address: they name
the matched passage, which stays the unit that is read and cited.

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

#### Scenario: Widened bodies do not repeat each other's text

- **WHEN** two results are widened and their spans would overlap
- **THEN** the payload carries that text once, and the later entry is narrowed

#### Scenario: Identifiers chain between tools

- **WHEN** an identifier returned by a search is passed to the passage and citation tools
- **THEN** each resolves it to the same object

#### Scenario: A passage says how its text was obtained

- **WHEN** a passage or a citation is returned
- **THEN** it reports whether the text came from a text layer, recognition, a vision model, or direct parsing

#### Scenario: A search response says whether it was reranked

- **WHEN** a search returns results
- **THEN** the payload states whether the ordering was reranked

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

#### Scenario: A response that would exceed the text bound is narrowed and says so

- **WHEN** the results of one search would together carry more corpus text than permitted
- **THEN** the response stays within the bound and states that it was narrowed

#### Scenario: A passage returned with its surroundings declares the whole span

- **WHEN** a tool returns a passage together with the text around it
- **THEN** the payload's declared span covers all the text it returned, and separately identifies the matched passage within it
