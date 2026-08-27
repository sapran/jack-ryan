## MODIFIED Requirements

### Requirement: Formats are handled by registered extractors, not by branching

Extraction SHALL be performed by `Extractor` implementations held in a registry.
Each SHALL declare what it accepts, and the router SHALL select one by
inspecting the file. An extractor SHALL NOT know about another, and adding a
format SHALL be registering an extractor rather than editing the pipeline.

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

When no registered extractor accepts a file, ingestion SHALL fail with a typed
error naming the file and its type rather than storing an empty document.

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
