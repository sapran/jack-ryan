# document-ingestion Specification

## Purpose

Defines how a file becomes a document: which extractor reads it, what identity
it carries, and what ingestion refuses to accept.

## Requirements

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

### Requirement: A legacy binary format is read by converting it to its modern equivalent

A format for which no reader exists SHALL be read by converting the file to its
modern equivalent and handing the result to the extractor that already reads
that equivalent. The converted text SHALL be rendered by that extractor and by
no other, so that one corpus never holds two renderings of the same kind of
document. A second rendering would not surface as an error — it would surface as
retrieval quality, which nothing downstream can detect.

The media type stored for such a document SHALL be the legacy type the file on
disk actually is, not the type it was converted to. The conversion is how the
text was obtained; it is not what the evidence is. Which path produced the text
SHALL be recoverable from the recorded extractor, distinguishing a converted
file from one read directly.

A file whose container contradicts its suffix SHALL be handled on what it is
rather than on what it is named. A file that is already in the modern format
under a legacy suffix SHALL be read directly, with no conversion. A file that is
neither the legacy container nor the modern one SHALL be refused with an error
naming the file and what was expected of it, rather than passed to a converter
whose own failure would name neither.

When the converter is absent, that document SHALL fail with an error naming the
remedy, and the ingest run SHALL continue. The converter SHALL NOT be verified
at the start of a run: unlike the recognition engine, which every page-bearing
document needs, a converter is needed only by the documents that use it, and a
host ingesting none must not be stopped by it.

Every failure of a conversion — a non-zero exit, a timeout, an unwritable
output, an unusable converter — SHALL be reported as the same typed extraction
error every other reader raises, so that one unreadable file fails one document
rather than ending the run.

Whether a converter is available SHALL be reported on the operator-facing status
surfaces, in one vocabulary across all of them, so that a host unable to read
these formats is discoverable before a long ingest rather than during one.

#### Scenario: A legacy document is rendered by the reader for its modern equivalent

- **WHEN** a legacy binary document is ingested and its modern equivalent has a registered reader
- **THEN** the text is produced by that reader, in the same rendering that reader gives the modern format

#### Scenario: The stored type is the legacy type, not the converted one

- **WHEN** a legacy document has been converted and read
- **THEN** the document records the media type of the file on disk, and records an extractor naming both the conversion and the reader that produced the text

#### Scenario: A modern file under a legacy suffix is read directly

- **WHEN** a file named with a legacy suffix is found to already be in the modern format
- **THEN** it is read by the modern format's reader with no conversion, and is recorded as having taken that path

#### Scenario: A file matching neither container is refused

- **WHEN** a file named with a legacy suffix is neither the legacy container nor the modern one
- **THEN** it is refused with an error naming the file and what was expected, rather than handed to the converter

#### Scenario: An absent converter fails the document, not the run

- **WHEN** a legacy document is ingested on a host with no converter installed
- **THEN** that document fails with an error naming the remedy, and the other files in the run are still ingested

#### Scenario: A failed conversion fails one document

- **WHEN** the converter exits non-zero, exceeds its time limit, or writes no output
- **THEN** the failure is reported as a typed extraction error against that file, and the run continues

#### Scenario: Converter availability is reported before a run

- **WHEN** an operator asks either status surface what the instance can do
- **THEN** both report whether a converter is available, using the same vocabulary
