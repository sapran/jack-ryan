## MODIFIED Requirements

### Requirement: Formats are handled by registered extractors, not by branching

Extraction SHALL be performed by `Extractor` implementations held in a registry.
Each SHALL declare what it accepts, and the router SHALL select one by
inspecting the file. An extractor SHALL NOT know about another, and adding a
format SHALL be registering an extractor rather than editing the pipeline.

Every extractor SHALL return a normalised result carrying the extracted text,
whatever structure it recovered, the file's native metadata, and any child
documents it found, so that everything downstream is independent of which
extractor ran. An extractor that finds children SHALL return them for the
pipeline to route; it SHALL NOT extract them itself, because doing so would make
support for a format depend on which container it was found in.

When no registered extractor accepts a file, ingestion SHALL fail with a typed
error naming the file and its type rather than storing an empty document.

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

- **WHEN** extraction produces no usable text and no children
- **THEN** ingestion fails rather than storing a document with empty content

#### Scenario: A container with no text of its own is stored

- **WHEN** an archive with no text of its own but with extractable entries is ingested
- **THEN** the archive is stored and its entries become its children

### Requirement: A document's identity is its content, and survives reingest

A document ingested directly SHALL be identified within its casefile by the hash
of its bytes.

A document produced by expansion has no file of its own on disk, and SHALL be
identified by the bytes the extractor produced for it together with the
containment path it was found at. Identical bytes reached by two different paths
SHALL therefore be two documents: that the same file was attached to two
different messages is a finding, and collapsing them into one document with one
parent would destroy the link an analyst is looking for.

Reingesting identical bytes SHALL reuse the existing document's identifier and
rebuild its derived data, so that any reference held elsewhere stays valid. This
SHALL hold for a document produced by expansion: re-ingesting the container that
produced it SHALL reuse the identifiers of everything it produces, because the
same container yields the same paths.

The same bytes in two different casefiles SHALL be two documents, because a
casefile is a compartment and identity does not cross it.

#### Scenario: Reingesting the same bytes keeps the identifier

- **WHEN** a file already ingested is ingested again into the same casefile
- **THEN** the document keeps its identifier and its chunks are rebuilt

#### Scenario: The same file in two casefiles is two documents

- **WHEN** identical bytes are ingested into two casefiles
- **THEN** each casefile holds its own document with its own identifier

#### Scenario: Reingesting a container keeps its descendants' identifiers

- **WHEN** a container already ingested is ingested again into the same casefile
- **THEN** the documents it produces keep the identifiers they had

#### Scenario: The same bytes found at two paths are two documents

- **WHEN** identical bytes are extracted from two different containment paths in one casefile
- **THEN** each is its own document, and each reports the path it was found at

### Requirement: Ingestion refuses what it cannot safely read

Ingestion SHALL refuse a symbolic link, and SHALL refuse a path that resolves
outside the directory it was asked to read. It SHALL bound the size of a file it
will accept.

These SHALL hold for an entry inside a container as strictly as for a file on
disk. A container is untrusted input, and the paths inside it are chosen by
whoever built it.

#### Scenario: A symbolic link is refused

- **WHEN** a symbolic link is offered for ingestion
- **THEN** it is refused rather than followed

#### Scenario: An oversized entry inside a container is refused

- **WHEN** a container holds an entry larger than the accepted file size
- **THEN** that entry is refused and the container's other entries are still ingested
