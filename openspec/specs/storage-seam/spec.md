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

Both halves SHALL be checkable rather than left to review. An adapter that holds
a store is not distinguishable by reading one call site — it looks like any other
delegation — and the composition root's own type declaration is what makes it
possible: a `Context` exposing the concrete store rather than the port permits
the reach without even a type error. The port therefore SHALL be what the
composition root declares, and the absence of such a reach SHALL be asserted.

A port method returning a value without its field names SHALL be treated as a
row rather than a domain object. One reason covers every shape this takes, and it
is the whole reason: a value offered without its field names is a value a caller
can misread, and a rename or a reordering of it is silent.

An untyped mapping is one such shape. The field names then live in strings at
every call site, where a rename is silent and a typo surfaces as a lookup failure
at whichever surface happens to read it first.

An unnamed tuple is the other, and SHALL be refused on the same ground rather
than tolerated as merely terse. It carries no field names at all, so each caller
supplies its own: a value that means one thing where it is returned acquires its
name only where it is unpacked, and two call sites are free to name it
differently. Reordering two fields of the same type then changes what every
caller reads while changing nothing a caller could be asked to update, and no
lookup fails to mark the moment it happened.

This SHALL be checkable too, rather than left to review, for the reason the two
halves above are: the port's own declared return types SHALL be asserted to name
their fields, so that the next method to return a nameless pair is refused when
it is written rather than when a caller misreads it.

#### Scenario: The service layer holds no SQL

- **WHEN** the service layer is inspected
- **THEN** it calls only port methods, and contains no SQL statements

#### Scenario: No adapter reaches a store

- **WHEN** the adapter modules are inspected
- **THEN** none of them accesses a store, whether directly or through a name bound to one

#### Scenario: The port hands back domain objects

- **WHEN** a port method reports counts or sizes describing stored data
- **THEN** it returns a typed domain object whose fields are named, rather than a mapping keyed by strings

#### Scenario: The port hands back no unnamed tuple

- **WHEN** the port's declared return types are inspected
- **THEN** none of them is a tuple, so no value the port returns is named for the first time at a call site

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

### Requirement: The store records what was derived from a document, and who derived it

Where the pipeline derives text from a document rather than recovering it — a
summary of a chunk, a summary of a document — the store SHALL record that text
beside the evidence it was derived from, and SHALL record it as derived rather
than as the document's own.

Derived text SHALL NOT enter the full-text index. The index answers the question
"which documents contain this term", and a model's words in it would answer that
question wrongly, with no way for a ranked result to say which of its hits
matched the evidence and which matched a summary of it.

Where the identity of whatever produced the derived text is not covered by the
corpus identity the store enforces, the store SHALL record that identity per row.
Corpus identity already carries the producer of anything folded into a vector,
because the store refuses to open under a different one; text that moves no
vector is outside that guarantee, and a surface reporting the currently
configured producer as the author of a stored value would be asserting something
it cannot know. This is the same rule that makes a document record which rung of
the quality gate produced its text: what the fingerprint does not guard, the
per-row record makes findable.

Derived text SHALL be overwritten when the evidence beside it is rewritten, never
preserved across a reingest. The value has to describe what is stored beside it
now, exactly as the record of how the text was recovered does.

#### Scenario: Derived text is stored beside the evidence and attributed

- **WHEN** the pipeline derives a summary from a document
- **THEN** it is stored beside that document, and carries the identity of what produced it unless corpus identity already does

#### Scenario: Derived text does not answer a keyword search

- **WHEN** a term appears in a stored summary and in no document's own text
- **THEN** a keyword search for that term returns no passage

#### Scenario: Reingest replaces derived text rather than keeping it

- **WHEN** a document is reingested
- **THEN** its stored derived text is replaced, so that no value describes text that is no longer there

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

### Requirement: A document is stored together with where it was observed

Storing a document SHALL write, in the same transaction and through the same
port call, the record of the location its bytes were observed at.

This is the rule already stated for data derived from a chunk, applied to the
one other place where a second write decides whether the first is honest.
Whether a document's location record may be read as whole is answered from that
record itself, so a document committed without its first observation asserts a
history it does not have. A later observation from somewhere else then supplies
the only row the record holds, and the document reads as though that one place
were the whole story — which is a false finding about the evidence, not a
missing one.

The port SHALL NOT offer a way to store a document without saying where it was
observed. Not a second method called next, and not an optional parameter: for
the reason the chunk rule gives, a seam that can be used in the wrong order
eventually is, and an optional one is used without eventually.

A failure while writing SHALL leave neither the document nor its observation, so
a document without the record that describes it is not a reachable state.

#### Scenario: A document and its observation are one write

- **WHEN** a document is stored
- **THEN** the location it was observed at is written in the same transaction, through the same call

#### Scenario: A failed write leaves no document without its record

- **WHEN** storing a document together with its observation fails partway
- **THEN** neither the document nor the observation remains

#### Scenario: The port offers no way to store a document without its observation

- **WHEN** the port's document-storing calls are inspected
- **THEN** every one of them requires the observed location, with no default
