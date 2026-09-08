## MODIFIED Requirements

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
