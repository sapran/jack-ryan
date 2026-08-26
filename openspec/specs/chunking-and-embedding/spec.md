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
