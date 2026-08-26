## Purpose

Defines how a file that holds other files is expanded into them — recursion
through the one router, so support is a property of a format rather than of
where it was found, and the budgets that stop a crafted archive from consuming
the machine.

## ADDED Requirements

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
