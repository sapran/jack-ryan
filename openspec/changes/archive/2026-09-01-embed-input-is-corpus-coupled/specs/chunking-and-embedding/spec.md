## ADDED Requirements

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
