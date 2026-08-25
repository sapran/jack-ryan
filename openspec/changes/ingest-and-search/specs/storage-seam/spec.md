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

#### Scenario: A single file backs the instance

- **WHEN** an instance is initialised
- **THEN** exactly one database file is created under the configured data directory

#### Scenario: Chunk text and its vector share one key

- **WHEN** a chunk is stored
- **THEN** its text, its full-text entry, and its vector are addressed by the same key in the same file

#### Scenario: A failed write leaves no half-stored chunk

- **WHEN** storing a chunk fails partway
- **THEN** neither its text nor its vector remains
