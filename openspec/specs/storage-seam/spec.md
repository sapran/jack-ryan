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

Keeping retrieval data in this same file — so that text and its vectors are
written in one transaction and cannot drift apart — is the reason the seam is
shaped this way, but no retrieval data exists yet. That commitment is recorded
in `docs/design.md` § 5 and becomes normative when the capability that stores
text and vectors is specified.

#### Scenario: A single file backs the instance

- **WHEN** an instance is initialised
- **THEN** exactly one database file is created under the configured data directory

### Requirement: The store records and enforces corpus identity

On first initialisation the store SHALL record its schema version and the
configured contract fingerprint. On every later initialisation it SHALL compare
the recorded values against the configured ones and SHALL refuse to open on a
mismatch, because a corpus is only appendable under the rules that created it.

The refusal SHALL name both the recorded value and the configured one.

#### Scenario: Reopening under the same contract succeeds

- **WHEN** a store is reopened with the contract that created it
- **THEN** it opens normally

#### Scenario: Reopening under a different contract is refused

- **WHEN** a store is reopened with a different contract fingerprint
- **THEN** initialisation fails, naming the recorded and the configured values

### Requirement: Shared state is guarded for threads, not just coroutines

Store access SHALL be guarded by a `threading` primitive rather than an asyncio
one. The server is async, so an asyncio lock would appear sufficient; it would
not hold once work runs in a thread pool, and choosing correctly here is far
cheaper than diagnosing interleaved writes later.

#### Scenario: The guard holds across threads

- **WHEN** the store's concurrency guard is inspected
- **THEN** it is a `threading` primitive
