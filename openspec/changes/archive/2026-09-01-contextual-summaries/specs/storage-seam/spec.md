## ADDED Requirements

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
