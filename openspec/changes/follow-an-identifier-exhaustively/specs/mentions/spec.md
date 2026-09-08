## ADDED Requirements

### Requirement: The documents carrying an identifier can be enumerated exhaustively

An instance SHALL be able to list every document in a casefile that carries one normalised
identifier, a bounded page at a time, so that a caller reaches the whole set rather than the
part a ranked retrieval surfaced.

This is a separate path from ranked search, deliberately. Search answers "which passages
best match this", bounded by a candidate depth and a result limit; this answers "which
documents carry this", bounded only by how many pages the caller reads. Conflating them
gives an analyst a ranking they read as a census.

The enumeration SHALL accept the identifier in the same form the search filter accepts — a
kind and a value together, or a value alone matching any kind — and SHALL match the
normalised form by the same normalisation the filter applies, so that a value copied out of
the inventory or out of a passage resolves. An identifier kind no extractor produces SHALL
be refused naming the kinds that exist. An empty identifier SHALL be refused rather than
answered: an enumeration that matched nothing in particular would report an empty carrier
set, which reads as "this casefile carries no such identifier".

Each entry SHALL carry the document it names, how many textual occurrences that document
holds, and a passage identifier addressing the earliest of them. The occurrence count SHALL
be counted the way the inventory counts — distinct positions in the document, never stored
rows — so that the entries' counts sum to the inventory's count for that identifier and the
number of entries equals the inventory's document count. Two figures the same instance
reports about the same identifier must agree, or one of them is silently wrong.

The passage identifier is what makes the enumeration usable as evidence rather than as a
list: a document reached this way SHALL be readable and citable without a ranked search
first. The passage stays the unit that is cited, as it is everywhere else.

The enumeration SHALL report how many entries it returned and how many the carrier set
holds, separately named, and SHALL carry the position to continue from while entries remain.
Its ordering SHALL be total, so that a page boundary cannot fall inside a tie and repeat or
skip an entry, and SHALL lead with the occurrence count so that the most heavily carrying
document is reached first. Bounds SHALL be clamped rather than refused.

The enumeration SHALL be confined to one casefile, as every read is, and SHALL be answerable
without embedding anything: it is a question about what was extracted, not about similarity.
It SHALL NOT be implemented by asking the retrievers for a greater depth, because a fused
rank is not a stable page boundary.

#### Scenario: Every carrier is returned exactly once across the pages

- **WHEN** an identifier carried by more documents than one page holds is enumerated to its end, on an unchanged corpus
- **THEN** the pages together name each carrying document exactly once, and no document that does not carry it

#### Scenario: The enumeration and the inventory agree about one identifier

- **WHEN** an identifier's carriers are enumerated and the same identifier is inventoried as a facet
- **THEN** the number of carriers equals the inventory's document count, and the carriers' occurrence counts sum to the inventory's mention count

#### Scenario: One occurrence seen by two overlapping chunks is counted once by its carrier

- **WHEN** a carrier holds an occurrence lying wholly inside the overlap between two of its chunks
- **THEN** that carrier reports one occurrence, not two

#### Scenario: A carrier is cited without a ranked search

- **WHEN** a document is reached only through the enumeration and its entry's passage identifier is cited
- **THEN** the citation resolves to a passage of that document, with no search having run

#### Scenario: The caller's spelling is normalised before matching

- **WHEN** an identifier is enumerated in a spelling a document used rather than in its normalised form
- **THEN** the same carriers are returned, and the response reports the normalised form it matched

#### Scenario: An unknown kind is refused and an absent identifier is not

- **WHEN** an enumeration is asked for a kind no extractor produces
- **THEN** it fails naming the kinds that exist

#### Scenario: An identifier the casefile does not carry is an empty page

- **WHEN** an enumeration is asked for a well-formed identifier no document carries
- **THEN** it returns no entries and reports a carrier set of nothing, saying that the inventory records only what the extractors found

#### Scenario: An empty identifier is refused

- **WHEN** an enumeration is asked with no identifier
- **THEN** it fails rather than returning an empty carrier set

#### Scenario: The enumeration is confined to its casefile

- **WHEN** two casefiles carry the same identifier and one is enumerated
- **THEN** only that casefile's documents are returned
