# document-hierarchy Specification

## Purpose

Defines what it means for one document to have come out of another — how
ancestry is recorded and queried, how it interacts with casefile scoping and
deletion, and how it reaches an analyst as the path they would follow to find
the evidence by hand.

## Requirements

### Requirement: A document records the document it came out of

A document SHALL carry a reference to its parent, absent for a document ingested
directly. Ancestry SHALL be queryable in both directions: the children of a
document, and the chain of ancestors of a document up to the one that was
ingested directly.

A child SHALL belong to the same casefile as its parent. Ancestry SHALL NOT
cross a casefile boundary, because a casefile is a compartment.

#### Scenario: A directly ingested document has no parent

- **WHEN** a file is ingested on its own
- **THEN** its document records no parent

#### Scenario: Ancestry is queryable in both directions

- **WHEN** a document extracted from a container is stored
- **THEN** it is listed among its parent's children, and its parent appears in its ancestor chain

#### Scenario: A child shares its parent's casefile

- **WHEN** a container is ingested into a casefile
- **THEN** every descendant it produces belongs to that same casefile

### Requirement: Deleting a document deletes what came out of it

Deleting a document SHALL delete its descendants and their derived data. A
descendant SHALL NOT outlive its parent, because a document whose containment
path no longer resolves cannot be cited.

#### Scenario: Deleting a container removes its descendants

- **WHEN** a document with children is deleted
- **THEN** its descendants and their chunks are deleted with it

### Requirement: A document reports the path it was found at

Every document SHALL be able to report its containment path — the names of its
ancestors from the directly ingested file down to itself. The path SHALL be what
an analyst would follow to find the same evidence by hand.

Where a document is presented to an agent or an analyst with its source, the
containment path SHALL be presented rather than the immediate name alone,
because an attachment's own filename identifies nothing on its own.

#### Scenario: A nested document reports its full path

- **WHEN** a document extracted several levels down is inspected
- **THEN** it reports the names of its ancestors from the ingested file down to itself

#### Scenario: A directly ingested document's path is its own name

- **WHEN** a document with no parent reports its containment path
- **THEN** the path is its own name

### Requirement: Listing returns what was ingested, and reaches expansions on request

A document listing SHALL return only directly ingested documents by default, and
SHALL return expanded descendants when explicitly asked. Three archives that
expand to forty thousand documents SHALL present as three documents to a caller
who asked for an inventory, because that is what was put in.

A listing SHALL make a document's place in the hierarchy visible, and a document
with children SHALL be identifiable as such without listing them, so that a
caller can tell there is more to reach.

Counts describing a casefile SHALL state which they are counting. A count that
mixes containers and their descendants without saying so misrepresents the size
of the corpus.

#### Scenario: A listing excludes expanded children by default

- **WHEN** a casefile's documents are listed with no option given
- **THEN** only documents ingested directly are returned

#### Scenario: Expansions are returned when asked for

- **WHEN** a casefile's documents are listed with descendants requested
- **THEN** documents produced by expansion are returned as well

#### Scenario: A container is identifiable without listing its children

- **WHEN** a document with children appears in a listing
- **THEN** it is marked as having children, and how many

#### Scenario: A count says what it counted

- **WHEN** a casefile reports how many documents it holds
- **THEN** the figure states whether it includes documents produced by expansion
