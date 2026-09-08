# mentions Specification

## Purpose
Defines how identifiers in the corpus — email addresses, telephone numbers,
bank accounts, company registration numbers — become facets an analyst can
inventory and pivots they can follow, and the rule that a shipped extractor
earns its place by precision rather than by coverage.

## Requirements

### Requirement: Identifiers are extracted at ingest by a registry of extractors

Mentions SHALL be extracted from a chunk's text by `MentionExtractor`
implementations held in a registry. Each SHALL declare the kind of identifier it
finds and its own name, and adding an extractor SHALL be registering one rather
than editing a branch.

This registry SHALL be the seam a model-backed extractor arrives through. A
classical named-entity model, or an optional model-backed pass, registers as one
more extractor with a kind and a name, and needs no schema change, no new facet
and no new surface. Selection living in the registry is what makes that true.

Extraction SHALL run over the chunks a document was divided into, and SHALL
record for each mention the kind, the text as it appeared, a normalised form, the
character offsets within the chunk, and which extractor found it.

Offsets SHALL be relative to the chunk rather than to the document, because a
chunk is the unit the store addresses and the unit a citation resolves to.

Extraction SHALL NOT be gated by a setting. Pattern extraction over a document's
chunks costs milliseconds and reaches no endpoint, and a facet nobody switched on
is a facet nobody has.

#### Scenario: Adding an extractor is registering one

- **WHEN** the set of extractors is inspected
- **THEN** each declares its kind and its name, and none knows about another

#### Scenario: A mention records where it was found

- **WHEN** a mention is extracted
- **THEN** its recorded offsets select that text from the chunk it was found in

#### Scenario: Extraction needs no configuration

- **WHEN** a document is ingested on an instance with nothing configured for mentions
- **THEN** its identifiers are extracted and stored

### Requirement: A shipped extractor is precise rather than eager

Every shipped extractor SHALL be one whose matches are worth faceting, and
precision SHALL be preferred over recall. A facet is an inventory an analyst
scans; one dominated by false matches is worse than an absent one, because it
costs attention and teaches the analyst to ignore the feature.

An identifier with a check digit SHALL be validated by it rather than matched by
shape alone. An identifier that is only a run of digits SHALL be anchored to a
nearby keyword that names it, because a bare run of digits fires on every date,
invoice line and page number in a corpus.

Where an extractor cannot meet that bar it SHALL be dropped rather than
loosened. Shipping three precise extractors is better than four of which one is
noise.

A normalised form SHALL be recorded beside the text as it appeared, so that a
pivot finds an identifier written another way, and the quotation still shows what
the document said.

#### Scenario: A failing check digit is not a mention

- **WHEN** text contains something shaped like a checksummed identifier but with a wrong check digit
- **THEN** it is not extracted

#### Scenario: A bare run of digits with no keyword is not a mention

- **WHEN** text contains a run of digits of the right length with no identifying keyword near it
- **THEN** it is not extracted

#### Scenario: A pivot finds an identifier written another way

- **WHEN** the same identifier appears in two documents with different spacing or punctuation
- **THEN** both are found by one pivot, and each quotation shows the form its own document used

### Requirement: Mentions are rebuilt with the chunks they belong to

A document's mentions SHALL be written in the same transaction that writes its
chunks, and SHALL be replaced whenever those chunks are replaced.

This is not a preference about tidiness. A chunk's identifier is minted afresh on
every reingest, so a mention written by a separate call after the chunks were
stored would reference either an identifier that no longer exists or one from a
previous ingest. Writing them together is what makes a mention's reference to a
chunk always resolvable.

A failure while writing a document's chunks SHALL leave no mention for that
document, on the same terms and by the same transaction as its chunks, its
full-text entries and its vectors.

Deleting a chunk, a document or a casefile SHALL leave no mention belonging to
it.

#### Scenario: Reingest leaves every mention pointing at a live chunk

- **WHEN** a document is reingested
- **THEN** every mention for it resolves to a chunk that exists, and none references a chunk from the previous ingest

#### Scenario: A failed chunk write leaves no mention

- **WHEN** storing a document's chunks fails partway
- **THEN** no mention for that document remains

#### Scenario: Deleting a casefile leaves no mention behind

- **WHEN** a casefile holding documents with mentions is deleted
- **THEN** no mention belonging to its chunks remains

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

### Requirement: The documents carrying an identifier can be enumerated exhaustively

An instance SHALL be able to list every document in a casefile that carries one normalised
identifier, a bounded page at a time, so that a caller reaches the whole set rather than the
part a ranked retrieval surfaced.

This is a separate path from ranked search, deliberately. Search answers "which passages
best match this", bounded by a candidate depth and a result limit; this answers "which
documents carry this", bounded only by how many pages the caller reads. Conflating them
gives an analyst a ranking they read as a census.

The enumeration SHALL accept the identifier in the same form the search filter accepts — a
kind and a value together, or a value alone matching any kind — and SHALL match the
normalised form by the same normalisation the filter applies, so that a value copied out of
the inventory or out of a passage resolves. An identifier kind no extractor produces SHALL
be refused naming the kinds that exist. An empty identifier SHALL be refused rather than
answered: an enumeration that matched nothing in particular would report an empty carrier
set, which reads as "this casefile carries no such identifier".

Each entry SHALL carry the document it names, how many textual occurrences that document
holds, and a passage identifier addressing the earliest of them. The occurrence count SHALL
be counted the way the inventory counts — distinct positions in the document, never stored
rows — so that the entries' counts sum to the inventory's count for that identifier and the
number of entries equals the inventory's document count. Two figures the same instance
reports about the same identifier must agree, or one of them is silently wrong.

The passage identifier is what makes the enumeration usable as evidence rather than as a
list: a document reached this way SHALL be readable and citable without a ranked search
first. The passage stays the unit that is cited, as it is everywhere else.

The enumeration SHALL report how many entries it returned and how many the carrier set
holds, separately named, and SHALL carry the position to continue from while entries remain.
Its ordering SHALL be total, so that a page boundary cannot fall inside a tie and repeat or
skip an entry, and SHALL lead with the occurrence count so that the most heavily carrying
document is reached first. Bounds SHALL be clamped rather than refused.

The enumeration SHALL be confined to one casefile, as every read is, and SHALL be answerable
without embedding anything: it is a question about what was extracted, not about similarity.
It SHALL NOT be implemented by asking the retrievers for a greater depth, because a fused
rank is not a stable page boundary.

#### Scenario: Every carrier is returned exactly once across the pages

- **WHEN** an identifier carried by more documents than one page holds is enumerated to its end, on an unchanged corpus
- **THEN** the pages together name each carrying document exactly once, and no document that does not carry it

#### Scenario: The enumeration and the inventory agree about one identifier

- **WHEN** an identifier's carriers are enumerated and the same identifier is inventoried as a facet
- **THEN** the number of carriers equals the inventory's document count, and the carriers' occurrence counts sum to the inventory's mention count

#### Scenario: One occurrence seen by two overlapping chunks is counted once by its carrier

- **WHEN** a carrier holds an occurrence lying wholly inside the overlap between two of its chunks
- **THEN** that carrier reports one occurrence, not two

#### Scenario: A carrier is cited without a ranked search

- **WHEN** a document is reached only through the enumeration and its entry's passage identifier is cited
- **THEN** the citation resolves to a passage of that document, with no search having run

#### Scenario: The caller's spelling is normalised before matching

- **WHEN** an identifier is enumerated in a spelling a document used rather than in its normalised form
- **THEN** the same carriers are returned, and the response reports the normalised form it matched

#### Scenario: An unknown kind is refused and an absent identifier is not

- **WHEN** an enumeration is asked for a kind no extractor produces
- **THEN** it fails naming the kinds that exist

#### Scenario: An identifier the casefile does not carry is an empty page

- **WHEN** an enumeration is asked for a well-formed identifier no document carries
- **THEN** it returns no entries and reports a carrier set of nothing, saying that the inventory records only what the extractors found

#### Scenario: An empty identifier is refused

- **WHEN** an enumeration is asked with no identifier
- **THEN** it fails rather than returning an empty carrier set

#### Scenario: The enumeration is confined to its casefile

- **WHEN** two casefiles carry the same identifier and one is enumerated
- **THEN** only that casefile's documents are returned
