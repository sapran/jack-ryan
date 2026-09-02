# container-extraction Specification

## Purpose

Defines how a file that holds other files is expanded into them — recursion
through the one router, so support is a property of a format rather than of
where it was found, and the budgets that stop a crafted archive from consuming
the machine.

## Requirements

### Requirement: A container is expanded through the same router as any other file

An extractor MAY hold child documents alongside its text, yielded one at a time
on a separate call. Each child SHALL be routed and extracted by the same
registry that handles a file offered directly,
so a format is supported inside a container exactly when it is supported outside
one, and a container extractor SHALL NOT know how to read what it contains.

A container SHALL be stored as a document in its own right, carrying whatever
text it has of its own, so that the containment path is a chain of real
documents rather than a string reconstructed later.

#### Scenario: A supported format nested in an archive is extracted

- **WHEN** an archive containing a supported document is ingested
- **THEN** the archive and the document are both stored, and the document's text is extracted by the extractor that handles its format

#### Scenario: The container itself is a document

- **WHEN** a container is ingested
- **THEN** a document exists for the container, and its children reference it as their parent

#### Scenario: An unsupported entry does not fail the container

- **WHEN** a container holds an entry no extractor accepts
- **THEN** that entry is skipped and reported, and the container's other entries are still ingested

### Requirement: Mail is expanded into messages and their attachments

An `.eml` or `.msg` file SHALL be a document whose text carries the message
headers an analyst reads — at least sender, recipients, date, and subject —
followed by the body. A `.mbox` file SHALL be a container whose children are its
messages.

An attachment SHALL be a child document of the message it arrived on, extracted
through the same router.

#### Scenario: A message carries its headers in its text

- **WHEN** a mail message is ingested
- **THEN** its text carries sender, recipients, date, and subject alongside the body

#### Scenario: An attachment is a child of its message

- **WHEN** a message with an attachment is ingested
- **THEN** the attachment is stored as a child document of the message

#### Scenario: A mailbox is expanded into its messages

- **WHEN** an mbox file is ingested
- **THEN** each message it holds is a child document of the mailbox

### Requirement: A spreadsheet is rendered as text that reads and embeds

A spreadsheet SHALL be rendered as text in which each sheet is identified and
each row is recoverable, so that a passage returned to a reader shows which
sheet and which row it came from rather than an undifferentiated run of values.

An empty sheet SHALL NOT prevent a workbook with usable sheets from being
ingested.

#### Scenario: Sheets are distinguishable in the extracted text

- **WHEN** a workbook of several sheets is ingested
- **THEN** the extracted text identifies each sheet and preserves its rows

#### Scenario: A workbook with one empty sheet still ingests

- **WHEN** a workbook holds both an empty sheet and a populated one
- **THEN** the workbook is ingested and the populated sheet's content is present

### Requirement: Recursion is bounded by depth, by count, and by bytes produced

Expansion SHALL be bounded by a maximum nesting depth, a maximum number of
descendants per ingest, and a maximum total of extracted bytes. Reaching a bound
SHALL stop expansion and report what was refused; it SHALL NOT discard what was
already ingested.

The byte bound SHALL count bytes produced by extraction rather than bytes read
from disk, because the attack this defends against is a small archive that
expands enormously.

#### Scenario: Nesting beyond the depth bound is refused

- **WHEN** a container nested deeper than the depth bound is ingested
- **THEN** expansion stops at the bound and reports what was not expanded

#### Scenario: A high-expansion archive is stopped by the byte budget

- **WHEN** a small archive whose entries expand past the byte budget is ingested
- **THEN** expansion stops when the budget is exhausted and reports that it was

#### Scenario: What was ingested before a bound was reached is kept

- **WHEN** expansion stops at a bound
- **THEN** the documents already stored remain, and the ingest reports itself as incomplete rather than failing wholesale

### Requirement: An entry may not escape the directory it is extracted into

An entry whose path escapes the extraction root — by absolute path, by parent
traversal, or by symbolic link — SHALL be refused. Refusing one entry SHALL NOT
abandon the rest of the container.

#### Scenario: A traversing entry is refused

- **WHEN** an archive holds an entry whose path points outside the extraction root
- **THEN** that entry is refused and the archive's remaining entries are still ingested

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
