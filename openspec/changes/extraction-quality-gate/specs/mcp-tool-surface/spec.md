## MODIFIED Requirements

### Requirement: A result separates its index from its bodies and carries chaining identifiers

A list-shaped result SHALL carry a compact `formatted` index for scanning and a
`results` array holding the entries. A passage body SHALL appear exactly once in
a payload, so that reading the index costs nothing beyond the index.

Every result entry SHALL carry `chunk_id` and `document_id`. An identifier a
tool returns SHALL be accepted by the tools that address that kind of object, so
one call chains into the next without the caller reconstructing references.

Identifiers SHALL be accepted as 8-character prefixes wherever they are taken.

An entry that carries corpus text SHALL also report how that text was obtained.
Recognition can render a word as a plausible different word, so a quotation
taken from a scan can be fluent and wrong in a way no later check catches. An
agent asked to cite what it claims cannot weigh that unless the surface tells
it, and the analyst reading the answer cannot either.

#### Scenario: The index is scannable and the body appears once

- **WHEN** a search returns results
- **THEN** a `formatted` index is present, and each passage body appears exactly once under `results`

#### Scenario: Identifiers chain between tools

- **WHEN** an identifier returned by a search is passed to the passage and citation tools
- **THEN** each resolves it to the same object

#### Scenario: A passage says how its text was obtained

- **WHEN** a passage or a citation is returned
- **THEN** it reports whether the text came from a text layer, recognition, a vision model, or direct parsing
