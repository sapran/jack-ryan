## ADDED Requirements

### Requirement: Ranked search is bounded and is not an enumeration

A search SHALL be bounded by a result limit and by the candidate depth its retrievers are
asked for, and the count it reports SHALL be a count of the passages it returned. It SHALL
NOT be presented, on any surface, as how many passages or documents the casefile holds for
that query or that identifier.

The candidate depth SHALL NOT be reported as a quantity of evidence. It is how deep each
retriever was asked to look, which is a property of the request rather than of the corpus,
and a caller cannot tell the two apart from a bare number.

Completeness SHALL be reachable by a separate path rather than by raising the depth. A fused
rank is not a stable page boundary: reciprocal rank fusion ties routinely, so two requests
at different depths do not agree about which candidate sits at any given position, and pages
cut out of such an ordering repeat and omit entries without saying so.

The surface SHALL point a caller from ranked search to that separate path, so that an agent
needing the whole carrier set for an identifier is not left inferring it from a bounded
ranking.

#### Scenario: A search's count is of the passages it returned

- **WHEN** a search is filtered to an identifier carried by more documents than the result limit admits
- **THEN** the count it reports is of the passages returned, and no field of the response states how many documents carry the identifier

#### Scenario: Ranked search points at the exhaustive path

- **WHEN** the search tool's description is read
- **THEN** it names the tool that enumerates every document carrying an identifier, and says that its own count is of returned passages
