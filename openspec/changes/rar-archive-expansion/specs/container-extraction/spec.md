## ADDED Requirements

### Requirement: A RAR archive is expanded like any other container

`.rar` SHALL be a registered container format. Its entries SHALL be routed and
extracted by the same registry that handles a file offered directly, bounded by
the same expansion budget, and subject to the same rules on entry names as every
other container. The extractor SHALL NOT know how to read what it holds.

Entries SHALL be yielded one at a time and each entry's bytes SHALL be read
incrementally, so that no archive is wholly resident in memory and expansion can
be stopped partway. An entry whose content exceeds the accepted size SHALL be
determined by what was read rather than by the size the archive declares,
because a declared size is chosen by whoever built the archive.

The reader SHALL be a library bound in process rather than an external
archiver invoked as a subprocess. This is a constraint on how the format is
read, not an implementation note: a subprocess reader for this format either
requires a non-free component or extracts whole archives to disk, and the second
would put an archive's full expansion on disk before the byte budget could
refuse any of it.

Multi-volume archives SHALL be refused with an error saying so, rather than
yielding the entries of the first volume as though they were the whole archive.

#### Scenario: A supported document inside a RAR archive is extracted

- **WHEN** a RAR archive containing a supported document is ingested
- **THEN** the archive and the document are both stored, and the document's text is extracted by the extractor that handles its format

#### Scenario: A RAR archive's entries are not all resident at once

- **WHEN** a RAR archive's entries are read
- **THEN** they are yielded one at a time, so expansion can be stopped partway

#### Scenario: An entry inside a RAR archive may not escape its extraction directory

- **WHEN** a RAR archive holds an entry whose name is absolute or traverses upward
- **THEN** that entry is refused and the archive's other entries are still ingested

#### Scenario: An entry larger than the bound is caught by what was read

- **WHEN** a RAR archive holds an entry whose content exceeds the accepted size
- **THEN** it is excluded on the bytes actually read rather than on the size the archive declared

### Requirement: An archive that cannot be opened fails, and never reads as empty

An archive the reader cannot open SHALL fail as a document, with an error naming
why. It SHALL NOT be stored as a container with no children.

An encrypted archive is the case this rule exists for. "This archive holds
nothing" and "this archive could not be opened" are different claims about
evidence, and storing the second as the first is a false statement an analyst
cannot detect: a container with zero children is indistinguishable from an
archive that was genuinely empty. The same reasoning refuses extracted text
consisting only of punctuation rather than storing it as an empty document.

#### Scenario: An encrypted archive fails with a reason

- **WHEN** an archive whose contents cannot be read without a password is ingested
- **THEN** the document fails with an error naming encryption, and no container with zero children is stored

#### Scenario: An unopenable archive does not stop the run

- **WHEN** an archive that cannot be opened is ingested alongside others
- **THEN** that document fails and the remaining files are still ingested

### Requirement: The archive reader's availability is reported, not enforced at startup

The archive reader SHALL NOT be verified at the start of an ingest run. A host
that ingests no archive SHALL NOT be stopped by a reader it will never call —
the same reasoning that reports the document converter rather than requiring it,
and deliberately not the reasoning applied to the recognition engine, which
every page-bearing document needs.

When the reader is unavailable, an archive SHALL fail as a document with an
error naming the reader and the remedy, and the run SHALL continue. It SHALL NOT
be skipped silently and SHALL NOT be stored as though it had been opened.

Availability SHALL be reported by the operator-facing surfaces before a run
starts, from a single definition, so that two adapters cannot describe one host
in two vocabularies.

#### Scenario: An absent reader fails the archive, not the run

- **WHEN** an archive is ingested on a host where the reader is unavailable
- **THEN** that document fails with an error naming the reader, and other documents in the run still ingest

#### Scenario: Reader availability is reported before a run

- **WHEN** an operator asks an instance for its status
- **THEN** the reported archive-reader availability is the same value on every surface that reports it
