## RENAMED Requirements

- FROM: `### Requirement: What is embedded for a chunk is exactly the chunk's text`
- TO: `### Requirement: What is embedded for a chunk is the chunk's text, and any folded context enters corpus identity`

## MODIFIED Requirements

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

## ADDED Requirements

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
