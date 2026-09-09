# mcp-tool-surface Specification

## ADDED Requirements

### Requirement: A document reached by navigation is citable without a ranked search

The surface SHALL offer a bounded, paged enumeration of one document's stored
passages, selected by a reference to that document. Each entry SHALL address a
passage that the passage and citation tools accept, and SHALL carry that
passage's position within the document, so that an entry can be turned into a
citation and the citation checked against the source by hand.

A document reached only by listing SHALL therefore be citable with no ranked
search having run. This is the same guarantee the identifier enumeration already
gives a document reached by pivoting on an identifier, and it exists here for a
stronger reason: browsing is the path for evidence that no query and no
identifier names. A container is exactly where retrieval is least likely to
surface what is inside it — an attachment's text is short, its filename is
generic, and it competes against the whole corpus — so requiring a search to
close the journey puts the citation back behind the mechanism the navigation
exists to route around.

The enumeration SHALL be ordered by the passage's own position in its document,
so that it reads as an index of the document rather than as a ranking of it. It
carries no score and states no relevance: which passage matters is the caller's
judgement, made from the document's structure and from reading a candidate.

The enumeration SHALL be confined to the casefile the reference was resolved in,
and a reference naming a document in another casefile SHALL be refused without
reporting anything about its passages. A casefile is a compartment, and a
refusal that described what it declined to return would breach it while
appearing to respect it.

Where a document holds no stored passage the payload SHALL say so, and SHALL NOT
return an entry that addresses nothing. A document with nothing to cite is a
real state rather than an error: a container is stored for the entries it holds
rather than for the text it carries, so one holding no entries has no passage,
and a corpus filled before empty documents were refused may hold others. An
empty list read as "this document contains no evidence" is a different claim and
a false one, of the same kind as an empty result standing in for an unrecognised
identifier kind.

The enumeration SHALL carry no passage text. It is an index, and the passage's
own words are one call away through the tools that return a passage and a
citation. A payload whose stated reason for needing no fence is that it carries
no corpus prose SHALL NOT be the payload that carries prose.

An entry MAY carry the heading path of the section the passage came from, and
that is the only corpus-derived value an entry carries. It is metadata of the
same kind as the filename a document listing already carries, collapsed to one
line on the same terms, and it is what makes a structured document navigable by
its own divisions rather than by position alone. Stating the permission
explicitly is deliberate: without it, a reader holding this requirement alone
could either strip the heading path as a violation or admit a clipped opening of
the passage as "not the passage's text", and the second reading is the one the
requirement exists to forbid.

#### Scenario: A document reached by listing is cited with no search

- **WHEN** a document is reached only by listing a container's contents, its passages are enumerated, and one of them is cited
- **THEN** the citation resolves to a passage of that document, with no ranked search having run

#### Scenario: A document's passages are enumerated in reading order

- **WHEN** a document holding more passages than one page admits is enumerated to its end
- **THEN** the pages together carry each passage exactly once, in the document's own order, and each page reports both how many it returned and how many the document holds

#### Scenario: A document with no stored passages says so

- **WHEN** a document that holds no passage is enumerated
- **THEN** the payload states that it has nothing to cite, and carries no entry

#### Scenario: A document in another casefile is refused

- **WHEN** the passages of a document belonging to a different casefile are requested
- **THEN** it fails as not found, and reports nothing about that document's passages

#### Scenario: The enumeration carries no passage prose

- **WHEN** a document's passages are enumerated
- **THEN** every entry carries identifiers, a position, a size and at most the heading path of its section, and none carries the passage's text
