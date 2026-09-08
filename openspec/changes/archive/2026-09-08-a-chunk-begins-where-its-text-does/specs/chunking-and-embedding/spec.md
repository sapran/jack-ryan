# chunking-and-embedding Specification

## MODIFIED Requirements

### Requirement: Chunking follows the corpus contract and stays locatable

Extracted text SHALL be divided into chunks using the size and overlap declared
in the corpus contract, preferring paragraph boundaries where they fall within
range. Chunking SHALL be deterministic: the same text and contract SHALL always
produce the same chunks.

Every chunk SHALL record its ordinal and its character offsets into the
extracted text, so a passage can always be located in the document it came from.

Those offsets SHALL select the chunk's stored text exactly: the extracted text
between them SHALL be that text, character for character, with no trimming
needed to make the two agree. A chunk's text is its window with surrounding
whitespace removed, so offsets naming the window are wrong by that whitespace —
and wrong invisibly, because the difference is only whitespace and every check
that trims before comparing passes.

The exactness is load-bearing rather than tidy. Anything deriving a position in
the document from a chunk's offsets and an offset inside that chunk's text adds
the two together, so a start naming the window puts the result before the
characters it claims to address. The identifier inventory distinguishes
occurrences by document position, so two overlapping chunks that trimmed unequal
whitespace gave one textual occurrence two positions, and it was counted twice.

#### Scenario: Chunking is reproducible

- **WHEN** the same text is chunked twice under one contract
- **THEN** the chunks are identical

#### Scenario: A chunk can be located in its source

- **WHEN** a chunk is produced
- **THEN** the extracted text between its recorded offsets is that chunk's text exactly

#### Scenario: A chunk whose window opened on whitespace is still located exactly

- **WHEN** a chunk's window begins or ends inside whitespace
- **THEN** its recorded offsets select its stored text, not the window that contained it
