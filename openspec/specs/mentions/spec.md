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

#### Scenario: An inventory reports both counts

- **WHEN** a casefile's identifiers are inventoried
- **THEN** each entry names its kind and normalised value, and reports both how many mentions and how many documents

#### Scenario: An inventory is confined to its casefile

- **WHEN** two casefiles contain the same identifier and one is inventoried
- **THEN** only that casefile's counts are reported

#### Scenario: An unknown kind is refused rather than answered emptily

- **WHEN** an inventory is asked for a kind no extractor produces
- **THEN** it fails naming the kinds that exist, rather than returning nothing
