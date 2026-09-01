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

### Requirement: What is embedded for a chunk is the chunk's text, and any folded context enters corpus identity

The text the ingestion pipeline hands to the embedder for a chunk SHALL be that
chunk's own text, and SHALL be that alone unless folding context in is configured
and the identity of whatever produces that context has entered corpus identity.
With nothing configured, no heading path, no summary and no other context SHALL
be folded in — which is the shipped default.

The asymmetric prefix an embedder applies inside the port is not an exception.
It is applied by the implementation rather than the caller, it is identical for
every passage, and it is covered by the embedder's own identity in the corpus
fingerprint.

Where folding is configured, three things SHALL hold together, and the value of
this requirement is in the conjunction rather than in any one of them.

First, the chunk's **stored** text SHALL be unchanged: it stays the chunk's own
text, so a citation still resolves to what the document says and the recorded
offsets still select it. Only what the embedder is given changes. That asymmetry
is exactly why the setting is corpus-coupled and cannot be treated as
infrastructure.

Second, the context folded in SHALL be recorded beside the chunk. Because the
stored text is unchanged by design, nothing else on disk would say what the
vector was built from, and a fold that leaves no record is indistinguishable
after the fact from no fold at all.

Third, the recorded context SHALL NOT enter the full-text index. A model's words
answering a keyword search would report a document as containing a term that
appears nowhere in it, and a ranked list has no way to mark which of its hits
matched the evidence and which matched a summary of it.

A chunk's heading path SHALL continue to be recorded and SHALL NOT be embedded,
whether or not folding is configured. It is available, it is context, and folding
it in would be a separate change under the same rule.

This is stated at length rather than left implicit because it is the thing a
later change is most likely to alter without noticing the cost. Contextual
retrieval — prepending a per-chunk summary before embedding — produces vectors
that are not comparable with ones built from the chunk's text alone. Corpus
identity is what refuses that mixture, and it is what a test asserts rather than
a comment describing it.

#### Scenario: The embedder receives the chunk's text unchanged

- **WHEN** a document is ingested with no folding configured
- **THEN** the texts handed to the embedder are the chunker's own output for that document, with nothing prepended or appended

#### Scenario: A recorded heading path is not embedded

- **WHEN** a document with headings is ingested
- **THEN** its chunks record a heading path and the text handed to the embedder is unchanged by it, whether or not folding is configured

#### Scenario: Folded context reaches the embedder and is recorded, and the stored text is not

- **WHEN** a document is ingested with folding configured
- **THEN** each text handed to the embedder is the recorded context followed by the chunk's own text, the chunk's stored text is the chunk's own text alone, and the recorded context is absent from the full-text index

### Requirement: A producer of folded context that fails stops the document rather than embedding it bare

When folding is configured and the producer of that context fails for a document,
that document SHALL fail with a typed error and SHALL be reported as failed. It
SHALL NOT fall back to embedding the chunk's text alone.

This is deliberately the opposite of the reranker's transient-failure policy, and
the difference is the reason both are stated. A reranker that fails while scoring
has cost the caller a better ordering; the fused order is a real ranking, nothing
is stored, and refusing to answer would make retrieval quality a condition of
retrieval. A producer that fails while folding is on is a different shape: falling
back would store vectors built from one kind of input inside a corpus whose
identity asserts the other. Both are the declared width, both are well-formed,
and no later check can separate them — the exact failure corpus identity exists
to prevent, arriving through the code rather than through the configuration. One
document reported as failed is recoverable; one document silently incomparable
with the rest is not.

A producer that returns fewer results than it was given SHALL be a failure of the
same kind, never padded to length. Padding would fold context into some chunks of
one document and not others, which is the same corruption at finer grain.

A producer that is named but cannot be reached at all SHALL be fatal for the run
rather than per document, because it is a misconfiguration and not a fact about
any one document. The two SHALL be distinguished by error type rather than by
which call happened first, so that reordering the handling cannot silently turn
one into the other.

#### Scenario: A failed producer fails the document and embeds nothing for it

- **WHEN** the producer of folded context fails for one document while folding is configured
- **THEN** that document is reported as failed and no chunk of it is stored or embedded

#### Scenario: A short result is a failure rather than padded

- **WHEN** the producer returns fewer results than the chunks it was given
- **THEN** it fails with a typed error, rather than the missing entries being filled in

#### Scenario: An unreachable producer is fatal for the run

- **WHEN** a producer is named but cannot be reached
- **THEN** the run fails naming the setting, rather than each document failing individually
