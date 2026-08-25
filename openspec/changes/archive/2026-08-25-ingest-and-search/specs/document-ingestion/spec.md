## ADDED Requirements

### Requirement: Formats are handled by registered extractors, not by branching

Extraction SHALL be performed by `Extractor` implementations held in a registry.
Each SHALL declare what it accepts, and the router SHALL select one by
inspecting the file. An extractor SHALL NOT know about another, and adding a
format SHALL be registering an extractor rather than editing the pipeline.

Every extractor SHALL return a normalised result carrying the extracted text,
whatever structure it recovered, and the file's native metadata, so that
everything downstream is independent of which extractor ran.

When no registered extractor accepts a file, ingestion SHALL fail with a typed
error naming the file and its type rather than storing an empty document.

#### Scenario: A registered format is routed to its extractor

- **WHEN** a file of a supported type is ingested
- **THEN** the extractor that accepts it produces the normalised result

#### Scenario: An unsupported format is refused

- **WHEN** a file no extractor accepts is ingested
- **THEN** ingestion fails with a typed error naming the file and its type

#### Scenario: A file yielding no usable text is refused

- **WHEN** extraction produces no usable text
- **THEN** ingestion fails rather than storing a document with empty content

### Requirement: A document's identity is its content, and survives reingest

A document SHALL be identified within its casefile by the hash of its bytes.
Reingesting identical bytes SHALL reuse the existing document's identifier and
rebuild its derived data, so that any reference held elsewhere stays valid.

The same bytes in two different casefiles SHALL be two documents, because a
casefile is a compartment and identity does not cross it.

#### Scenario: Reingesting the same bytes keeps the identifier

- **WHEN** a file already ingested is ingested again into the same casefile
- **THEN** the document keeps its identifier and its chunks are rebuilt

#### Scenario: The same file in two casefiles is two documents

- **WHEN** identical bytes are ingested into two casefiles
- **THEN** each casefile holds its own document with its own identifier

### Requirement: Ingestion refuses what it cannot safely read

Ingestion SHALL refuse a symbolic link, and SHALL refuse a path that resolves
outside the directory it was asked to read. It SHALL bound the size of a file it
will accept.

#### Scenario: A symbolic link is refused

- **WHEN** a symbolic link is offered for ingestion
- **THEN** it is refused rather than followed
