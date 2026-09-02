# document-ingestion Specification

## MODIFIED Requirements

### Requirement: Formats are handled by registered extractors, not by branching

Extraction SHALL be performed by `Extractor` implementations held in a registry.
Each SHALL declare what it accepts, and the router SHALL select one by
inspecting the file. An extractor SHALL NOT know about another, and adding a
format SHALL be registering an extractor rather than editing the pipeline.

Selection SHALL be by the file's declared type first. Where no registered
extractor claims that type, the router SHALL read the file's leading bytes and,
if they positively identify a format the registry already handles, SHALL route
the file to that format's extractor. A file whose declared type is claimed by an
extractor SHALL NOT be routed by its content, so content routing cannot change
how any file the registry already reads is read.

A signature SHALL identify a format affirmatively. That a file's bytes decode as
text SHALL NOT be treated as a signature: admitting it would draw every
unhandled text-shaped file into the corpus as a document, which is the same
failure as storing text that carries no letters or digits — it looks ingested and
is worth less than a refusal.

The single question "can this file be read" SHALL have one answer used
everywhere, so that a caller deciding whether to attempt a file and a caller
extracting it cannot disagree.

Where a file is routed by its content, the extractor SHALL be given the file
under the type it was identified as, so that no extractor is handed a declared
type it cannot key on. A document routed by its content SHALL record that it
was, and SHALL keep the name it carries on disk: reading a file as something
other than its name is a disclosure to the analyst, not a correction of the
evidence.

The declared type advertised as supported SHALL remain what the registry
declares. Content routing is a recovery path and SHALL NOT widen it.

Every extractor SHALL return a normalised result carrying the extracted text,
whatever structure it recovered, the file's native metadata, how the text was
obtained, and whether the file holds further files, so that everything
downstream is independent of which extractor ran.

An extractor that holds further files SHALL yield them one at a time, on a
separate call from the one that extracts its text. It SHALL NOT return them all
together: a container holding many entries would otherwise be wholly resident in
memory before the expansion budget could refuse any of it, leaving the ceiling
unreachable in the case it exists for.

An extractor SHALL yield its children for the pipeline to route and SHALL NOT
extract them itself, because doing so would make support for a format depend on
which container it was found in.

A page image offered on its own SHALL be accepted and read as a document. A
photographed or scanned page arrives as an image file in a real dump as often as
it arrives inside a PDF, and refusing it would put that evidence out of reach of
the corpus entirely.

When no registered extractor accepts a file by its declared type and its content
identifies no handled format, ingestion SHALL fail with a typed error naming the
file and its type rather than storing an empty document.

Text SHALL count as usable only if it carries at least one letter or digit in
some script. Text that is whitespace and punctuation alone SHALL be refused as
though it were empty, because it is what failed recognition produces and it is
worse than a failure: it passes an emptiness check, stores, chunks, embeds, and
leaves a document an analyst can list and can never find.

A container SHALL be exempt from the rule that a document must yield usable
text: an archive whose value is entirely in its entries SHALL be stored so that
its children have a parent to hang from.

#### Scenario: A registered format is routed to its extractor

- **WHEN** a file of a supported type is ingested
- **THEN** the extractor that accepts it produces the normalised result

#### Scenario: An unsupported format is refused

- **WHEN** a file no extractor accepts is ingested
- **THEN** ingestion fails with a typed error naming the file and its type

#### Scenario: A file yielding no usable text is refused

- **WHEN** extraction produces no usable text and the file holds nothing to expand
- **THEN** ingestion fails rather than storing a document with empty content

#### Scenario: Text with no letters or digits is refused

- **WHEN** extraction recovers only whitespace and punctuation
- **THEN** ingestion fails rather than storing it as a document

#### Scenario: A page image is ingested as a document

- **WHEN** an image of a page is ingested
- **THEN** it is accepted and read, rather than refused as an unsupported type

#### Scenario: A container's entries are not all resident at once

- **WHEN** a container's entries are read
- **THEN** they are yielded one at a time, so expansion can be stopped partway

#### Scenario: A container with no text of its own is stored

- **WHEN** an archive with no text of its own but with extractable entries is ingested
- **THEN** the archive is stored and its entries become its children

#### Scenario: A file whose declared type no extractor claims is read on its content

- **WHEN** a file carrying a decorated or absent extension holds a format the registry handles
- **THEN** it is routed to that format's extractor and ingested, rather than refused as an unsupported type

#### Scenario: A file with a claimed declared type is never routed on content

- **WHEN** a file's declared type is claimed by a registered extractor
- **THEN** that extractor reads it and the file's content is not consulted to select another

#### Scenario: A content-routed document discloses how it was read

- **WHEN** a file is routed by its content rather than its declared type
- **THEN** the stored document records that route and keeps the filename it carries on disk

#### Scenario: A text-shaped file is not drawn in by decoding alone

- **WHEN** a file no extractor claims carries no identifying signature, though its bytes decode as text
- **THEN** it is refused, rather than stored as a plain-text document

#### Scenario: Attempting a file and extracting it agree

- **WHEN** the pipeline decides whether any extractor can read a file
- **THEN** the decision is the one extraction itself would make, so a file judged readable is not skipped before extraction
