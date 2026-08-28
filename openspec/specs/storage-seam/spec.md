# storage-seam Specification

## Purpose

Defines the single persistence boundary — `StorePort` — and the guarantees the
store behind it makes: one file per instance, and a recorded corpus identity it
refuses to violate.

## Requirements

### Requirement: All persistence goes through the storage port

`StorePort` SHALL be the single persistence boundary. It SHALL speak in domain
objects rather than rows, and SHALL contain no validation — rules belong in the
service layer so that every adapter inherits them.

The service layer SHALL NOT contain SQL, and no adapter SHALL reach a store
directly.

#### Scenario: The service layer holds no SQL

- **WHEN** the service layer is inspected
- **THEN** it calls only port methods, and contains no SQL statements

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

### Requirement: The store records and enforces corpus identity

On first initialisation the store SHALL record its schema version and the
configured corpus identity. On every later initialisation it SHALL compare the
recorded values against the configured ones and SHALL refuse to open on a
mismatch, because a corpus is only appendable under the rules that created it.

The two recorded values SHALL be treated differently, because they fail for
different reasons. A schema version below the running one SHALL be carried
forward rather than refused; corpus identity SHALL always be compared and never
migrated. A schema describes how the same evidence is stored, and can be changed
without changing what the evidence means; corpus identity describes what the
stored vectors mean, and nothing can reconcile two answers to that.

The schema SHALL be carried forward before corpus identity is compared. A store
that is migrated and then refused on identity is left improved and undamaged,
whereas comparing identity first would refuse a store the running code could have
read.

Corpus identity SHALL include which embedder produced the vectors, not only the
contract they were configured by. A store filled by the deterministic embedder
SHALL be refused by a real-model configuration, and the reverse. Both produce
vectors of the declared width, so nothing downstream can distinguish them: the
refusal at open is the only point where the difference is still visible.

The refusal SHALL name both the recorded value and the configured one, and SHALL
state how to proceed: restore the configuration the recorded value names, or
reingest under the current one. Two long identity strings differing in one
component tell an operator what happened but not what to do about it, and this
refusal is expected during ordinary work — every fingerprint change produces it
for every existing corpus.

A refusal for the schema version SHALL NOT use the corpus-identity remedy.
"Restore the configuration the recorded value names" cannot be acted on for a
schema the running code no longer contains.

#### Scenario: Reopening under the same contract succeeds

- **WHEN** a store is reopened with the contract that created it
- **THEN** it opens normally

#### Scenario: Reopening under a different contract is refused

- **WHEN** a store is reopened with a different contract fingerprint
- **THEN** initialisation fails, naming the recorded and the configured values

#### Scenario: Reopening under a different embedder is refused

- **WHEN** a store filled by one embedder is reopened by a configuration selecting another
- **THEN** initialisation fails, naming the recorded and the configured values

#### Scenario: The refusal says how to proceed

- **WHEN** a store refuses to open under a different corpus identity
- **THEN** the message states that the configuration can be restored or the casefiles reingested

#### Scenario: An older schema is migrated where an older identity is refused

- **WHEN** a store recorded at an older schema version but a matching corpus identity is opened
- **THEN** it is carried forward and opens, rather than being refused

#### Scenario: The schema is carried forward before identity is compared

- **WHEN** a store has both an older schema version and a different corpus identity
- **THEN** the schema is migrated and the store is then refused on identity

### Requirement: Shared state is guarded for threads, not just coroutines

Store access SHALL be guarded by a `threading` primitive rather than an asyncio
one. The server is async, so an asyncio lock would appear sufficient; it would
not hold once work runs in a thread pool, and choosing correctly here is far
cheaper than diagnosing interleaved writes later.

#### Scenario: The guard holds across threads

- **WHEN** the store's concurrency guard is inspected
- **THEN** it is a `threading` primitive
