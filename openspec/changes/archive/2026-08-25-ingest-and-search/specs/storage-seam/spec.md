## MODIFIED Requirements

### Requirement: One file holds everything an instance persists

Persistence SHALL be a single SQLite file under the configured data directory.
Everything an instance persists SHALL live in that file, so backing an instance
up is copying one file.

`StorePort` exists as the seam for a later heavier engine, and SHALL remain the
only abstraction introduced for that purpose.

Retrieval data SHALL live in that same file: a chunk's text, its entry in the
full-text index, and its vector SHALL be addressed by one key and written in one
transaction. A chunk whose text is stored without its vector SHALL therefore not
be a reachable state, which is what removes any need to reconcile separate
stores.

That single shared key is also a hazard, and the store SHALL account for it.
The full-text and vector indexes are virtual tables, which never observe
`ON DELETE CASCADE`, and SQLite reuses a freed rowid. A deletion path that
removed chunk rows without removing their index entries would therefore leave
orphans that collide with the next insert. Removal of the sidecar rows SHALL
therefore be enforced at the point every deletion passes through — a trigger on
the chunk table — rather than by each caller remembering to do it.

#### Scenario: A single file backs the instance

- **WHEN** an instance is initialised
- **THEN** exactly one database file is created under the configured data directory

#### Scenario: Chunk text and its vector share one key

- **WHEN** a chunk is stored
- **THEN** its text, its full-text entry, and its vector are addressed by the same key in the same file

#### Scenario: A failed write leaves no half-stored chunk

- **WHEN** storing a chunk fails partway
- **THEN** neither its text nor its vector remains

#### Scenario: Deleting a casefile leaves no orphaned index entries

- **WHEN** a casefile holding documents is deleted
- **THEN** no full-text entry and no vector belonging to its chunks remains, and a later ingest succeeds
