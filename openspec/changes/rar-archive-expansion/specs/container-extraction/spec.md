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

One volume of a multi-volume set SHALL be refused with an error saying so,
rather than yielding the entries of the first volume as though they were the
whole archive. The refusal SHALL be decided on what the archive says about
itself — the volume flag its own header carries, or an entry declaring that its
data continues elsewhere — and SHALL NOT depend on the file's name. A name is
chosen by whoever handed over the dump: an old-style first volume is
`name.rar`, a renamed one carries no ordinal at all, and an analyst numbering
their own files produces `evidence.part1.rar` for an archive that is whole.

#### Scenario: A supported document inside a RAR archive is extracted

- **WHEN** a RAR archive containing a supported document is ingested
- **THEN** the archive and the document are both stored, and the document's text is extracted by the extractor that handles its format

#### Scenario: A RAR archive's entries are not all resident at once

- **WHEN** a RAR archive's entries are read
- **THEN** they are yielded one at a time, so expansion can be stopped partway

#### Scenario: An entry inside a RAR archive may not escape its extraction directory

- **WHEN** a RAR archive holds an entry whose name is absolute or traverses upward
- **THEN** that entry is refused and the archive's other entries are still ingested

#### Scenario: An oversized entry is judged on what was read, not on what was declared

- **WHEN** a RAR archive holds an entry whose content exceeds the accepted size
- **THEN** the decision is made on the bytes actually read rather than on the size the archive declares

### Requirement: An archive that cannot be opened fails, and never reads as empty

An archive the reader cannot open SHALL fail as a document, with an error naming
why. It SHALL NOT be stored as a container with no children.

An archive whose own headers do not account for the file — truncated, or
carrying no main header — SHALL fail the same way, even where the reader
returns no error. This is not the same case as the one above and needs stating
separately: the reader answers an unparseable header with end-of-archive rather
than a failure, so a cut archive arrives as zero entries and no exception.

An archive that opens and genuinely holds nothing SHALL still be stored as a
container with no children. That is the one case the two claims coincide in, and
the distinction is which of them is true.

An encrypted archive is the case this rule exists for. "This archive holds
nothing" and "this archive could not be opened" are different claims about
evidence, and storing the second as the first is a false statement an analyst
cannot detect: a container with zero children is indistinguishable from an
archive that was genuinely empty. The same reasoning refuses extracted text
consisting only of punctuation rather than storing it as an empty document.

Encryption SHALL be refused for every generation of the format the reader
accepts and for both of its password modes, by the listing pass and by the
expansion pass alike, from one shared decision. Two passes deciding this
separately can disagree, and the pass that reads an entry's bytes is not the
pass whose refusal is reported: an archive expanded without its listing first
would otherwise hand back ciphertext to be chunked, embedded and indexed as
though it were the document's text.

#### Scenario: An encrypted archive fails with a reason

- **WHEN** an archive whose contents cannot be read without a password is ingested
- **THEN** the document fails with an error naming encryption, and no container with zero children is stored

#### Scenario: A truncated archive fails rather than reading as empty

- **WHEN** an archive whose headers declare more than the file contains is ingested
- **THEN** the document fails with an error naming why, and no container with zero children is stored

#### Scenario: An archive that genuinely holds nothing is still stored

- **WHEN** an archive that opens cleanly and holds no entries is ingested
- **THEN** it is stored as a container with no children

#### Scenario: One volume of a multi-volume set is refused however it is named

- **WHEN** an archive that declares itself part of a volume set is ingested under any filename
- **THEN** the document fails with an error naming multi-volume and a remedy, and no entry of it is stored

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
