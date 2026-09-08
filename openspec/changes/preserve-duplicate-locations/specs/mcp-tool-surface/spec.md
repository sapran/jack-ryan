## MODIFIED Requirements

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

A listing SHALL be bounded like a read, and SHALL carry both how many entries it
returned and how many the selection holds. The two SHALL be separately named: a
caller that cannot tell the whole set from the first page of it reports the first
page as coverage, which is the failure this surface's epistemics exist to
prevent. An entry carries metadata rather than prose, but a listing that
materialises every matching document to return the first few pays for the whole
corpus's text to answer a question about its shape.

Where entries remain, the payload SHALL say so and SHALL carry the position to
continue from, in the same vocabulary a truncated read uses. One continuation
contract across the surface rather than two: an agent that has learned to follow
a truncated read should not have to learn a second spelling to follow a truncated
listing.

Paging an unchanged selection SHALL return each entry exactly once across the
pages. The ordering SHALL therefore be total, so that a page boundary cannot fall
inside a tie and repeat or skip an entry. An ordering that leaves two entries
interchangeable is not wrong within one page and is silently wrong across two,
and the caller cannot detect it: every page is individually well-formed.

A document's recorded source locations SHALL be a bounded disclosure rather than
a paged listing. The payload SHALL carry how many locations the record holds and
SHALL say when the disclosure was cut, and it SHALL NOT offer a position to
continue from. This is the deliberate exception to the one continuation contract
above, and the reason it is not a listing: a document observed at more locations
than the bound is characterised by the count, which the payload already carries,
and not by its next path. Offering a continuation no caller has a use for would
teach an agent to page toward an answer it already has.

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

#### Scenario: A listing reports the size of the selection it paged

- **WHEN** a listing returns fewer entries than the selection holds
- **THEN** it reports both counts, marks itself truncated, and carries the offset to continue from

#### Scenario: Paging an unchanged selection omits and repeats nothing

- **WHEN** a selection is paged to its end and the corpus has not changed
- **THEN** the pages together carry each matching entry exactly once

#### Scenario: A document's locations are bounded and say when they were cut

- **WHEN** a document's recorded source locations exceed the disclosure bound
- **THEN** the payload carries how many the record holds and marks the disclosure cut, and offers no position to continue from
