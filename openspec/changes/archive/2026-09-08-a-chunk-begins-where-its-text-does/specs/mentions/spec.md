# mentions Specification

## MODIFIED Requirements

### Requirement: A casefile's identifiers can be inventoried as a facet

An instance SHALL be able to report which identifiers a casefile contains,
counted, so an analyst can see what is there before deciding what to search for.
The inventory SHALL be answerable for one kind or across all kinds.

Each entry SHALL carry the kind, the normalised value, how many times it was
mentioned, and in how many documents. Both counts are needed and neither
substitutes for the other: an identifier mentioned forty times in one document is
a different fact from one mentioned once in each of forty.

The inventory SHALL be ordered by how often an identifier occurs, and SHALL be
bounded, because a large corpus holds more identifiers than a caller can read.

The inventory SHALL be scoped to one casefile, as every search is, because a
casefile is the compartment.

Asking for a kind that no extractor produces SHALL be an error naming the kinds
that exist, rather than an empty inventory. An empty result reads as "this corpus
contains none", which is a different and false statement.

"How many times it was mentioned" SHALL be a count of textual occurrences in the
documents, never of stored rows. Chunks overlap by the contract's overlap, so an
identifier near a boundary is extracted once per chunk covering it; counting rows
makes the figure wrong by the overlap, and wrong invisibly, because nothing in
the number says which of its occurrences were the same one seen twice.

An occurrence SHALL therefore be distinguished by the document it sits in
together with its position in that document, and that position SHALL be derived
from where the chunk's stored text begins in the extracted text. Derived instead
from the window the chunk was trimmed from, one occurrence acquires a different
position in every chunk that trimmed a different amount, and it is counted twice
again — by another route, with the count's own definition still correct.

The per-document figure SHALL remain a count of documents: two documents
mentioning an identifier at the same position are two documents, and one
occurrence seen by two chunks of one document is one mention in one document.

#### Scenario: An inventory reports both counts

- **WHEN** a casefile's identifiers are inventoried
- **THEN** each entry names its kind and normalised value, and reports both how many mentions and how many documents

#### Scenario: An inventory is confined to its casefile

- **WHEN** two casefiles contain the same identifier and one is inventoried
- **THEN** only that casefile's counts are reported

#### Scenario: An unknown kind is refused rather than answered emptily

- **WHEN** an inventory is asked for a kind no extractor produces
- **THEN** it fails naming the kinds that exist, rather than returning nothing

#### Scenario: One occurrence seen by two overlapping chunks counts once

- **WHEN** an identifier lies wholly inside the overlap between two chunks of one document
- **THEN** the inventory reports one mention in one document

#### Scenario: One occurrence in each of two documents counts as two

- **WHEN** two documents each mention an identifier once, at the same position in their own text
- **THEN** the inventory reports two mentions in two documents

## ADDED Requirements

### Requirement: A stale document position can be repaired without reingesting

An instance SHALL offer an operator a bounded pass over one casefile that
recomputes each mention's recorded document position from the stored text, so a
corpus whose positions were derived under an earlier rule is corrected without
re-extracting, re-chunking or re-embedding anything.

The pass SHALL write only that derived position. Extracted text, chunks, vectors,
full-text entries and every other field of a mention SHALL be left exactly as
they are: a casefile is evidence, and this corrects something derived from it.

The pass SHALL be invoked deliberately by an operator and SHALL NOT run because a
store was opened. It SHALL NOT appear on the agent surface, which is a read
surface.

The pass SHALL report what it examined and what it changed — documents, chunks,
chunks whose stored text could not be located, and positions corrected — so a run
that corrected nothing is distinguishable from one that did not look.

Where a chunk's stored text is not found within the span its own offsets name,
that chunk SHALL be counted and left alone. A position guessed for it would
resolve and be wrong, which is worse than one known to be stale.

Running the pass again SHALL correct nothing further and SHALL report that,
because it recomputes each position from the stored text rather than adjusting
what is already recorded.

#### Scenario: A stale position is corrected from the stored text

- **WHEN** the pass runs over a casefile whose mention positions were derived from untrimmed windows
- **THEN** each position is recomputed from where its chunk's text begins, and the inventory then counts one occurrence once

#### Scenario: The pass leaves the evidence alone

- **WHEN** the pass corrects a position
- **THEN** the document's text, the chunk rows, the vectors and every other mention field are unchanged

#### Scenario: A repeated pass corrects nothing

- **WHEN** the pass runs twice over one casefile
- **THEN** the second run reports no correction and the inventory is unchanged

#### Scenario: A chunk whose text is not at its offsets is left alone

- **WHEN** a chunk's stored text is not found within the span its offsets name
- **THEN** that chunk is counted as unlocatable, and no mention of it is repositioned

#### Scenario: The repair is absent from the agent surface

- **WHEN** the agent tool surface is inspected
- **THEN** no tool performs the repair
