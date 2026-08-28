# extraction-quality-gate Specification

## Purpose

Defines how a document made of pages is read: an escalating ladder from the
page's own text layer, to recognition, to a vision model, stopping as soon as
what comes back is thick enough to be a real reading. Also defines how the
recognition engine is chosen — named, never inferred from the host — and what
each document records about which rung produced its text, because text
recovered by recognition is weaker evidence than text lifted off the page and
an analyst has to be able to tell them apart.

## Requirements

### Requirement: A page-bearing document is read through an escalating gate

A document that carries pages or is itself an image SHALL be read through an
ordered ladder of rungs, from the cheapest to the most expensive, stopping at
the first rung whose text clears a floor.

The first rung SHALL read the document's own text layer with recognition
disabled. This is the correct and fastest reading of a born-digital document,
which is the majority, and it is what makes the rungs below it rare.

The second rung SHALL recognise the page images. It SHALL be attempted when the
first rung's text falls below the floor, which is what a scan looks like: pages
present, almost no text on them.

The third rung SHALL read the pages with a vision model. It SHALL be attempted
only when the second rung's text is also below the floor and the rung is enabled
in the profile. It is off unless enabled, because it costs model weights and
time that a deployment must choose to spend.

The floor SHALL be expressed as a count of characters per page, so that it means
the same thing for a one-page letter and a two-hundred-page report, and it SHALL
be configurable.

When no rung clears the floor, the richest of the attempts SHALL be the result,
and it SHALL be subject to the same refusal as any other extraction: a document
that yields nothing usable is refused rather than stored.

A format that carries no page images SHALL NOT be escalated. There is nothing
for recognition to read in a word-processor file, a spreadsheet, a message or a
markup document, so escalating one would spend the cost and change the text for
no possible gain.

#### Scenario: A born-digital document stops at the first rung

- **WHEN** a document with a usable text layer is extracted
- **THEN** its text comes from the text layer and no recognition is attempted

#### Scenario: A scan escalates to recognition

- **WHEN** a document whose pages carry almost no text is extracted
- **THEN** recognition is attempted and its text is the result

#### Scenario: The vision rung is not reached unless it is enabled

- **WHEN** recognition also returns text below the floor and the vision rung is disabled
- **THEN** no vision model is loaded, and the richest attempt so far is the result

#### Scenario: A format without pages is never escalated

- **WHEN** a word-processor, spreadsheet, message or markup document is extracted
- **THEN** it is read once and no recognition is attempted, whatever its length

#### Scenario: The floor is relative to length

- **WHEN** two documents of different page counts recover the same total characters
- **THEN** whether each escalates depends on its characters per page, not its total

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

### Requirement: The recognition engine and its language are named, not inferred

The recognition engine and the recognition language SHALL be named in the
profile.

A setting that defers the choice to the host SHALL be refused. An engine
selected by what happens to be installed on the machine makes extracted text —
which becomes the corpus — a property of the machine that ingested it, so the
same evidence read on two machines would produce two different corpora with
nothing recording the difference.

The default SHALL be an engine and recognition language that read English,
Ukrainian and Russian, because those are the languages this workbench is for and
a default that silently drops two of them is worse than no default.

Where an engine recognises one language at a time, the profile SHALL name
exactly one and a list SHALL be refused. Accepting a list and using the first
would leave an operator who wrote three languages believing all three are read.

A language the configured engine cannot serve SHALL be refused when the engine
is constructed, naming what it accepts. Only the engine can answer that
authoritatively, so it is asked rather than a table in this codebase that would
drift from it.

#### Scenario: An engine chosen by the host is refused

- **WHEN** a profile defers the recognition engine to whatever the host provides
- **THEN** loading fails, naming the setting

#### Scenario: The default reads all three working languages

- **WHEN** an instance starts with no recognition settings configured
- **THEN** the default engine and language recognise English, Ukrainian and Russian

#### Scenario: More languages than the engine supports is refused

- **WHEN** a profile names several recognition languages for an engine that recognises one
- **THEN** loading fails rather than silently using the first

#### Scenario: A language the engine cannot serve is refused

- **WHEN** the configured engine is constructed with a language it does not serve
- **THEN** construction fails, naming the setting and what the engine accepts

### Requirement: An extraction engine that cannot be built stops the ingest

An engine or vision model named in the profile and not constructible SHALL be
fatal before any document of an ingest is read. The error SHALL name the setting
that selected it and how to proceed without it.

It SHALL NOT fall back to another engine, and it SHALL NOT fall back to reading
pages without recognition. Both would leave an instance quietly ingesting scans
as empty or near-empty documents, which is unrecoverable without noticing and
reingesting.

The check SHALL be made once per ingest run, before the first document, rather
than on the first document that happens to need recognition. A run that stops
part way has already stored documents, and which ones it stored depends on the
order the files were walked.

The engine SHALL be built to check it, not looked up. A converter that holds an
engine's settings can be constructed without the engine existing, so anything
short of building it reports that a misconfigured instance is healthy.

The vision model is checked more weakly: its name SHALL be resolved, and its
weights SHALL NOT be loaded. They are gigabytes, and the rung is reached only by
documents that defeated both rungs above it, so loading them at the start of
every run would charge every ingest for a rung it will almost never use. A
vision model that resolves but cannot run therefore fails on the first document
that needs it. This is a weaker guarantee than the one made for the recognition
engine, and it is stated rather than glossed.

#### Scenario: A configured engine that cannot load stops the ingest

- **WHEN** an ingest begins with a recognition engine that cannot be constructed
- **THEN** it fails before reading any document, naming the setting and how to proceed without it

#### Scenario: A failed engine does not silently disable recognition

- **WHEN** the configured engine cannot be constructed
- **THEN** the ingest fails rather than proceeding with recognition disabled

#### Scenario: Reading the corpus does not require a recognition engine

- **WHEN** an instance searches or reads without ingesting
- **THEN** no recognition engine is constructed

#### Scenario: A vision model that is not a real model spec stops the ingest

- **WHEN** an ingest begins with a configured vision model that names no known spec
- **THEN** it fails before reading any document, without loading any weights
