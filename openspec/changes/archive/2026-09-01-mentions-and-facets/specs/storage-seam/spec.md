## ADDED Requirements

### Requirement: Everything derived from a chunk is written in the chunk's own transaction

Data derived from a chunk and addressed by it SHALL be written in the same
transaction that writes the chunk, through the same port call, rather than by a
later call the caller is trusted to make.

The reason is the shared key the store already accounts for. A chunk's identifier
is minted afresh on every reingest, so a second call after the chunks were
written would attach derived rows to identifiers that had just been replaced. A
half-written state of that kind is not detectable afterwards: the rows are
well-formed and reference identifiers that once existed.

The port SHALL therefore take that derived data as a parameter of the call that
replaces a document's chunks. It SHALL NOT be offered as a separate method that
happens to be called next, because a seam that can be used in the wrong order
eventually is.

A failure while writing SHALL leave neither the chunks nor anything derived from
them, so a partially rebuilt document is not a reachable state.

Removal SHALL be enforced where every deletion already passes, rather than by
each caller remembering: derived rows addressed by a chunk SHALL be removed when
that chunk is, including when its document or its casefile is deleted.

#### Scenario: Derived rows are written with the chunks they belong to

- **WHEN** a document's chunks are replaced
- **THEN** the data derived from them is written in the same transaction, and none of it references a chunk from the previous ingest

#### Scenario: A failed write leaves nothing derived behind

- **WHEN** replacing a document's chunks fails partway
- **THEN** neither the chunks nor anything derived from them remains

#### Scenario: Deleting a casefile removes what was derived from its chunks

- **WHEN** a casefile holding documents is deleted
- **THEN** nothing derived from its chunks remains, and a later ingest succeeds
