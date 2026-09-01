# chunking-and-embedding Specification

## Purpose

Defines how a document's text becomes retrievable units, and the boundary
behind which embedding happens — including the rule that an embedder which
cannot load stops ingestion rather than quietly substituting another.

## Requirements

### Requirement: Chunking follows the corpus contract and stays locatable

Extracted text SHALL be divided into chunks using the size and overlap declared
in the corpus contract, preferring paragraph boundaries where they fall within
range. Chunking SHALL be deterministic: the same text and contract SHALL always
produce the same chunks.

Every chunk SHALL record its ordinal and its character offsets into the
extracted text, so a passage can always be located in the document it came from.

#### Scenario: Chunking is reproducible

- **WHEN** the same text is chunked twice under one contract
- **THEN** the chunks are identical

#### Scenario: A chunk can be located in its source

- **WHEN** a chunk is produced
- **THEN** its recorded offsets select that chunk's text from the extracted text

### Requirement: Embedding happens behind a port with distinct document and query operations

Embedding SHALL be reached through a port exposing its dimensionality, a
document operation, and a query operation. The two SHALL be separate because
some models require asymmetric prefixes and applying them is the embedder's
responsibility, not the caller's.

At least two implementations SHALL exist: one backed by a real model, and a
deterministic one for tests so that the suite never downloads a model. The
deterministic implementation SHALL be a genuine embedder — identical text
yielding identical vectors, and shared vocabulary yielding greater similarity —
and SHALL be selected only by explicit configuration.

#### Scenario: The deterministic embedder is stable and discriminating

- **WHEN** the deterministic embedder embeds the same text twice
- **THEN** the vectors are identical, and texts sharing vocabulary are more similar than texts sharing none

#### Scenario: Tests need no model download

- **WHEN** the test suite runs
- **THEN** no model is downloaded

### Requirement: An embedder that cannot load fails loudly

When the configured embedder cannot be loaded, ingestion SHALL fail with a typed
error. It SHALL NOT fall back to another implementation, because vectors that
silently mean something different would corrupt the corpus in a way no later
check could detect.

An embedding whose width disagrees with the contract SHALL be refused.

The embedder's declared width SHALL be compared with the contract's before the
store is opened, and a disagreement SHALL be refused naming both widths and
saying which side to change.

The reach of this check SHALL be stated rather than assumed. An embedder built
from configuration takes its width *from* the contract, so the two cannot
disagree by that route; the comparison guards the seam where an embedder is
supplied directly, and it becomes the guard it reads like on the day an embedder
reports a width it was not given — one that learns its width from the model it
loaded. A contract declaring a width the configured model does not actually
produce is a different failure, caught by the embedder when it loads, part-way
through an ingest rather than before the store is opened.

The check SHALL be made before the store is constructed and not after, because
once the store is initialised the vector index has been created at the contract's
width and a valid corpus identity recorded — leaving a wrongly sized store on
disk that opens cleanly.

The embedder SHALL additionally refuse to load when the installed embedding
library is not the version the contract declares. This is the same failure in a
subtler form: the library loads, the model loads, and the vectors are the right
width, but they are not comparable with the ones already stored. Width and
model name are not sufficient evidence that two vectors mean the same thing.

#### Scenario: A failed embedder stops ingestion

- **WHEN** the configured embedder cannot be loaded
- **THEN** ingestion fails with a typed error and no fallback is used

#### Scenario: A mis-sized embedding is refused

- **WHEN** an embedding's width disagrees with the contract
- **THEN** it is refused rather than stored

#### Scenario: An embedder built on the wrong library version refuses to load

- **WHEN** the installed embedding library differs from the version the contract declares
- **THEN** the embedder fails with a typed error naming both versions, rather than producing vectors

#### Scenario: A mis-sized embedder is refused before a store is created

- **WHEN** an instance is assembled with a supplied embedder whose declared width differs from the contract's
- **THEN** it fails naming both widths, and no store file is created

### Requirement: What is embedded for a chunk is exactly the chunk's text

The text the ingestion pipeline hands to the embedder for a chunk SHALL be that
chunk's own text and nothing else. No heading path, no summary, and no other
context SHALL be folded in.

The asymmetric prefix an embedder applies inside the port is not an exception.
It is applied by the implementation rather than the caller, it is identical for
every passage, and it is covered by the embedder's own identity in the corpus
fingerprint.

This is stated rather than left implicit because it is the thing a later change
is most likely to alter without noticing the cost. Contextual retrieval —
prepending a per-chunk summary before embedding — is deferred to M3, and on the
day it arrives the vectors it produces are not comparable with the ones already
stored. Corpus identity is what refuses that mixture, and the setting that turns
it on therefore belongs in the contract. Until then the present behaviour is
itself the guard, and a test asserts it rather than a comment describing it.

A chunk's heading path SHALL continue to be recorded and SHALL NOT be embedded.
It is available, it is context, and folding it in is precisely the change this
requirement forces into the open.

#### Scenario: The embedder receives the chunk's text unchanged

- **WHEN** a document is ingested
- **THEN** the texts handed to the embedder are the chunker's own output for that document, with nothing prepended or appended

#### Scenario: A recorded heading path is not embedded

- **WHEN** a document with headings is ingested
- **THEN** its chunks record a heading path and the text handed to the embedder is unchanged by it
