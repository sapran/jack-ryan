## MODIFIED Requirements

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
