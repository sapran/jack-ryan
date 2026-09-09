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

**A recorded location SHALL be the path the bytes were observed at, and that
path alone SHALL be what makes one location distinct from another.** Two
observations that name the same path SHALL be one location, however each was
reached. The path SHALL be followable by hand, so it SHALL carry the directories
above the file as well as the file's own name: a path relative to a root that is
not recorded neither distinguishes one dump from another nor leads anyone to the
evidence, which is why two dumps each holding one file at their top level are two
locations.

Keying a location on the ingested root paired with the path within it SHALL NOT
be done, because the same file reached through two different roots yields two
pairs denoting one place — a folder walk and then that folder's nested file named
directly produce `(dump, sub/note.txt)` and `(dump/sub, note.txt)`. Both name the
same file, and recording them separately reports a discovery where nothing was
discovered and counts one physical location twice.

For a document produced by expansion the recorded path SHALL begin at the
top-level file that was ingested and follow the containment chain to it, and
SHALL NOT name any working directory its bytes were materialised into while it
was read. Such a directory is created afresh on every run, so recording it would
make each reingest of one container report locations it had never seen.

A document's own filename and containment path SHALL be the first location its
bytes were observed at, and SHALL NOT be overwritten by a later copy found
elsewhere. That path is what a citation names, so a citation written before the
second copy arrived SHALL still resolve to what it named.

An ingest result SHALL distinguish a copy found somewhere not previously
recorded from a reingest of a location already known. The two are the same
document either way, but only one of them is something the analyst has just
learned.

**Whether a document's location record is whole SHALL be derived from when
recording began, and SHALL NOT be asserted by a stored claim of its own.** The
record is whole exactly when it has existed since the document was created,
which is what comparing the earliest recorded observation against the document's
creation establishes. A separately stored claim is a second copy of that fact
and can disagree with it: an instance that wrote the claim and then failed
before writing the observation carries a document asserting a whole record it
does not have.

**A later observation SHALL NOT turn missing history into a whole record.**
Where recording began after the document was created — because the document
predates the record, or because the write that should have opened its record did
not complete — the record SHALL report itself unable to answer, and SHALL keep
doing so however many further observations are added. Recording a location this
instance can see is not evidence about the locations it cannot.

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
- **THEN** both locations are recorded, because the paths they were observed at differ

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

#### Scenario: One file reached through two ingest roots is one location

- **WHEN** a folder is ingested and then a file inside it is ingested directly, by naming that file or its own folder
- **THEN** one location is recorded for that file, and no run reports it as newly discovered

#### Scenario: An interrupted first ingest leaves the history unable to answer

- **WHEN** a document is stored but the write that opens its location record does not complete, and identical bytes are later ingested from a different root
- **THEN** the record reports itself unable to answer rather than whole, and says so however many further locations are added
