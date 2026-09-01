## ADDED Requirements

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
