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

The path a document reports is the first location its bytes were observed at.
Where the same bytes were observed at further locations, those additional
locations SHALL be reportable beside the path the document reports, and the
disclosure SHALL be bounded: a document found in more places than the bound is
characterised by how many, not by its next path. Each recorded location SHALL be
a followable path, carrying the directories above the file as well as the file's
own name, because a relative path on its own neither distinguishes one dump from
another nor can be followed to the evidence.

Locations SHALL be counted as distinct places, not as distinct observations. The
same file offered twice through different ingest roots is one place, and a count
that reported it as two would tell an analyst a file was duplicated across the
material when it was not — a false finding, which is worse than an absent one on
this surface.

Where a listing marks a document as observed at more than one place, it SHALL
also say whether that count is the whole story. Where the record began after the
document was stored, nothing identifies which of its rows is the place the
document itself reports, so a count of one may be that place rather than a
second — and a listing carries no other qualifier, because it never builds the
record a single document's disclosure is drawn from. Marking without the
qualifier states a second place that may not exist; suppressing the mark
instead would hide a place that does.

Where the record cannot answer what those locations were, the disclosure SHALL
say so rather than presenting the one path it has as the whole set. Presenting a
surviving path as a complete answer is a stronger claim than saying nothing, and
a false one.

#### Scenario: A nested document reports its full path

- **WHEN** a document extracted several levels down is inspected
- **THEN** it reports the names of its ancestors from the ingested file down to itself

#### Scenario: A directly ingested document's path is its own name

- **WHEN** a document with no parent reports its containment path
- **THEN** the path is its own name

#### Scenario: A document observed at several locations reports them

- **WHEN** a document whose bytes were observed at more than one source location is inspected
- **THEN** the additional locations are reported beside the path it reports, bounded, with how many were recorded in total

#### Scenario: A document whose locations were never recorded reports unknown

- **WHEN** a document stored before source locations were recorded is inspected
- **THEN** the disclosure reports the record as unable to answer rather than presenting its own path as the whole set

#### Scenario: One place offered through two roots is counted once

- **WHEN** a document's bytes were offered twice at one path, reached through two different ingest roots
- **THEN** it reports one location, and a listing does not mark it as found in several places

#### Scenario: A listing says whether its location count is the whole story

- **WHEN** a document whose record began after it was stored is marked in a listing as observed at more than one place
- **THEN** the entry also carries whether that count may be read as whole

### Requirement: Listing returns what was ingested, and reaches expansions on request

A document listing SHALL return only directly ingested documents by default, and
SHALL return expanded descendants when explicitly asked. Three archives that
expand to forty thousand documents SHALL present as three documents to a caller
who asked for an inventory, because that is what was put in.

A listing SHALL make a document's place in the hierarchy visible, and a document
with children SHALL be identifiable as such without listing them, so that a
caller can tell there is more to reach.

A listing entry SHALL likewise be markable as having been observed at more than
one source location, and how many, without listing them. This is the same
affordance the child marking gives and it exists for the same reason: a caller
scanning an inventory for files found in several places should not have to open
every document to find them.

Counts describing a casefile SHALL state which they are counting. A count that
mixes containers and their descendants without saying so misrepresents the size
of the corpus.

A listing SHALL be able to return one document's direct contents, selected by a
reference to that document, so that a container marked as having children can be
entered rather than only counted. Marking a container without offering any way to
open it leaves the evidence inside it reachable only where a search happens to
surface it — which is least likely exactly where a container makes it least
likely, because an attachment's text is short and its name is generic.

That selection SHALL be confined to the casefile the reference was resolved in,
and a reference naming a document in another casefile SHALL be refused without
reporting anything about its contents. A casefile is a compartment, and a
refusal that described what it declined to return would breach it while appearing
to respect it.

A document returned as a container's contents SHALL carry the same child marking
as one returned from the casefile's intake, so that nesting is reachable to any
depth rather than one level. A selection that marks the first level and not the
second tells a caller a nested archive holds nothing, which is a false statement
rather than a missing one.

The three selections SHALL be named in what a listing returns rather than left to
be inferred from its arguments, because an empty page means something different
in each: an empty intake, a casefile with nothing in it, and a container that
expanded to nothing are three different facts about the corpus.

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

#### Scenario: A container's contents are listed by naming it

- **WHEN** a listing is asked for the contents of a document with children
- **THEN** the documents expanded directly out of it are returned, and the listing names which document it listed

#### Scenario: A nested container is marked inside its parent's listing

- **WHEN** a container's contents include a document that is itself a container
- **THEN** that document is marked as having children, and how many

#### Scenario: A container in another casefile is refused

- **WHEN** a listing is asked for the contents of a document belonging to a different casefile
- **THEN** it fails as not found, and reports nothing about that document's contents

#### Scenario: A listing names which selection it returned

- **WHEN** a listing returns no documents
- **THEN** it names which selection was listed, so that an empty intake, an empty casefile and an empty container are distinguishable

#### Scenario: A document observed at several locations is marked in a listing

- **WHEN** a document whose bytes were observed at more than one source location appears in a listing
- **THEN** it is marked as observed at several locations, and how many, without them being listed
