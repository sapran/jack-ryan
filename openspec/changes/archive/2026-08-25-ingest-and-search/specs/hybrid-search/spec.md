## ADDED Requirements

### Requirement: Search combines keyword and semantic retrieval over one store

Search SHALL run two retrievers over the same store — keyword ranking over the
full-text index, and nearest-neighbour search over the vector index — and SHALL
combine their results into a single ranking.

Both SHALL be available with no endpoint configured, so an instance can search
its corpus offline.

#### Scenario: Both retrievers contribute to one ranking

- **WHEN** a search runs
- **THEN** results found by keyword and by vector similarity appear in one ranked list

### Requirement: Results are fused by rank, not by blended score

Fusion SHALL use reciprocal rank fusion, consuming only each retriever's
ordering. Scores SHALL NOT be normalised and blended: keyword scores and vector
distances are not comparable, and blending them would introduce a weighting to
tune per corpus.

A chunk returned by both retrievers SHALL rank above one returned by only a
single retriever at the same position.

#### Scenario: Agreement outranks a single retriever

- **WHEN** one chunk is returned by both retrievers and another by only one, at the same rank
- **THEN** the chunk both retrievers returned ranks higher

### Requirement: Every search is scoped to one casefile

A search SHALL name exactly one casefile and SHALL return only that casefile's
chunks. There SHALL be no cross-casefile search, because a casefile is the
compartment.

#### Scenario: Another casefile's content is never returned

- **WHEN** two casefiles hold documents with the same words and one is searched
- **THEN** only that casefile's chunks are returned

### Requirement: A result carries what is needed to use and to verify it

Each result SHALL carry the chunk's text, the document it came from, the
chunk's position within that document, and identifiers that address both the
chunk and the document for follow-up.

Result counts SHALL be bounded.

#### Scenario: A result resolves to its source

- **WHEN** a search returns a hit
- **THEN** it carries the chunk text, its document, its offsets, and identifiers for both
