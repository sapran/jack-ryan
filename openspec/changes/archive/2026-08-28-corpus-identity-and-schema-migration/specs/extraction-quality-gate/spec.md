## MODIFIED Requirements

### Requirement: A document records how its text was obtained

Every document SHALL record which rung produced its text: its own text layer,
recognition, a vision model, or direct parsing for a format that has no pages.

The record SHALL be stored with the document and SHALL survive reingest. Every
surface that lists or shows a document SHALL report it — the agent surface
wherever it returns corpus text, and equally the surfaces a person reads.

The human is the audience with the most use for it. An analyst is the one who
decides whether a document is worth re-scanning, whether a quotation can be
relied on, and whether a casefile has been read well enough to draw conclusions
from; an assistant that can see the value while the person cannot leaves that
decision to the party less able to act on it.

Every surface SHALL report it in the same vocabulary and under the same name, so
that a person and an assistant discussing the same document are not using two
words for one fact. A value the codebase does not recognise SHALL be reported as
unrecorded rather than passed through, on every surface alike.

Two reasons make this load-bearing rather than decorative. Text recovered by
recognition can be wrong in ways that read as fluent, so a quotation taken from
it is weaker evidence than one lifted from a text layer, and an analyst must be
able to tell the two apart without opening the original. And corpus identity
deliberately does not cover the extraction engine, so this is the only record
that makes a later re-extraction targetable: without it, improving the
recognition engine means reingesting everything or knowing nothing.

#### Scenario: The rung that produced the text is stored

- **WHEN** a document is ingested
- **THEN** it records whether its text came from a text layer, recognition, a vision model, or direct parsing

#### Scenario: Reingest preserves how the text was obtained

- **WHEN** a document is ingested again
- **THEN** the record reflects the rung that produced the text on that ingest

#### Scenario: A person listing documents can see which were recognised

- **WHEN** documents are listed or shown on a surface a person reads
- **THEN** each reports how its text was obtained

#### Scenario: One vocabulary across every surface

- **WHEN** the same document is shown to a person and to an assistant
- **THEN** both report how its text was obtained using the same name and the same words
