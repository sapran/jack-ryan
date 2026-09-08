## MODIFIED Requirements

### Requirement: A document's identity is its content, and survives reingest

A document ingested directly SHALL be identified within its casefile by the hash
of its bytes.

A document produced by expansion has no file of its own on disk, and SHALL be
identified by the bytes the extractor produced for it together with the
containment path it was found at. Identical bytes reached by two different paths
SHALL therefore be two documents: that the same file was attached to two
different messages is a finding, and collapsing them into one document with one
parent would destroy the link an analyst is looking for.

Reingesting identical bytes SHALL reuse the existing document's identifier and
rebuild its derived data, so that any reference held elsewhere stays valid. This
SHALL hold for a document produced by expansion: re-ingesting the container that
produced it SHALL reuse the identifiers of everything it produces, because the
same container yields the same paths.

The same bytes in two different casefiles SHALL be two documents, because a
casefile is a compartment and identity does not cross it.

Identical bytes offered from several ordinary source locations SHALL remain one
document, because identity for a directly ingested file is its content alone.
Every source location a document's bytes were observed at SHALL be recorded
against it. The set of places one file was found is evidence of shared custody
and distribution in its own right, and it is the deduplication that makes that
set discoverable rather than something to be traded away for it.

A recorded source location SHALL be the root that was ingested together with
the path within it, and the two together SHALL be what makes one location
distinct from another. A containment path is relative to whatever was ingested,
so two dumps each holding one file at their top level yield the same relative
path; keyed on that path alone the second observation would be indistinguishable
from the first and the second custodian would be lost — which is the case this
record exists for. The two together SHALL also be followable by hand, which a
path relative to an unrecorded root is not.

For a document produced by expansion the root SHALL be that of the top-level
file it came out of, and SHALL NOT be any working directory its bytes were
materialised into while it was read. Such a directory is created afresh on every
run, so recording it would make each reingest of one container report locations
it had never seen.

A document's own filename and containment path SHALL be the first location its
bytes were observed at, and SHALL NOT be overwritten by a later copy found
elsewhere. That path is what a citation names, so a citation written before the
second copy arrived SHALL still resolve to what it named.

An ingest result SHALL distinguish a copy found somewhere not previously
recorded from a reingest of a location already known. The two are the same
document either way, but only one of them is something the analyst has just
learned.

Where a document was stored before its source locations were recorded, the
record SHALL be reported as unable to answer rather than presented as whole. Such
a document's locations were overwritten before they could be kept, and a surface
offering what survives as the complete set would be asserting something this
instance cannot know.

#### Scenario: Reingesting the same bytes keeps the identifier

- **WHEN** a file already ingested is ingested again into the same casefile
- **THEN** the document keeps its identifier and its chunks are rebuilt

#### Scenario: The same file in two casefiles is two documents

- **WHEN** identical bytes are ingested into two casefiles
- **THEN** each casefile holds its own document with its own identifier

#### Scenario: Reingesting a container keeps its descendants' identifiers

- **WHEN** a container already ingested is ingested again into the same casefile
- **THEN** the documents it produces keep the identifiers they had

#### Scenario: The same bytes found at two paths are two documents

- **WHEN** identical bytes are extracted from two different containment paths in one casefile
- **THEN** each is its own document, and each reports the path it was found at

#### Scenario: Identical bytes in two folders keep both locations

- **WHEN** identical bytes are ingested from two different ordinary source folders in one casefile
- **THEN** the casefile holds one document, and both source locations are recorded against it

#### Scenario: Identical bytes under two ingest roots keep both locations

- **WHEN** two separately ingested roots each hold identical bytes at the same path within them
- **THEN** both locations are recorded, distinguished by the root each was ingested from

#### Scenario: Reingesting a container records no new location for its entries

- **WHEN** a container already ingested is ingested again from the same root
- **THEN** its expanded documents record no further location, and the run reports no newly recorded location

#### Scenario: A later copy does not overwrite the first location

- **WHEN** a copy of an already-ingested file is ingested from a different location
- **THEN** the document still reports the filename and containment path it was first observed at

#### Scenario: Reversing the input order preserves the same locations

- **WHEN** the same two source locations are ingested in the opposite order
- **THEN** the same set of locations is recorded, and the document reports whichever was observed first

#### Scenario: A same-location reingest records no new location

- **WHEN** a file is ingested twice from the same location
- **THEN** one location is recorded, and the second run reports the location as already known

#### Scenario: A copy at a new location is reported without making the run incomplete

- **WHEN** a run records a location it had not seen for a document the casefile already held
- **THEN** the result names the newly recorded location and the run still reports itself complete

#### Scenario: A document ingested before locations were recorded says so

- **WHEN** a document stored before source locations were recorded is reingested
- **THEN** its location record is reported as unable to answer, and no location is invented for the copy that was overwritten
