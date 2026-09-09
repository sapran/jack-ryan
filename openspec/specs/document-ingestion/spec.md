# document-ingestion Specification

## Purpose

Defines how a file becomes a document: which extractor reads it, what identity
it carries, and what ingestion refuses to accept.

## Requirements

### Requirement: Formats are handled by registered extractors, not by branching

Extraction SHALL be performed by `Extractor` implementations held in a registry.
Each SHALL declare what it accepts, and the router SHALL select one by
inspecting the file. An extractor SHALL NOT know about another, and adding a
format SHALL be registering an extractor rather than editing the pipeline.

Selection SHALL be by the file's declared type first. Where no registered
extractor claims that type, the router SHALL read the file's leading bytes and,
if they positively identify a format the registry already handles, SHALL route
the file to that format's extractor. A file whose declared type is *accepted* by
an extractor SHALL NOT be routed by its content, so content routing cannot
change how any file the registry already reads is read. Accepted rather than
merely declared: an extractor MAY advertise a type and still refuse a given
file, and it is the refusal that decides.

A signature SHALL identify a format affirmatively. That a file's bytes decode as
text SHALL NOT be treated as a signature: admitting it would draw every
unhandled text-shaped file into the corpus as a document, which is the same
failure as storing text that carries no letters or digits — it looks ingested and
is worth less than a refusal.

The single question "can this file be read" SHALL have one answer used
everywhere, so that a caller deciding whether to attempt a file and a caller
extracting it cannot disagree.

Where a file is routed by its content, the extractor SHALL be given the file
under the type it was identified as, so that no extractor is handed a declared
type it cannot key on. A document routed by its content SHALL record that it
was, and SHALL keep the name it carries on disk: reading a file as something
other than its name is a disclosure to the analyst, not a correction of the
evidence.

The declared type advertised as supported SHALL remain what the registry
declares. Content routing is a recovery path and SHALL NOT widen it.

Every extractor SHALL return a normalised result carrying the extracted text,
whatever structure it recovered, the file's native metadata, how the text was
obtained, and whether the file holds further files, so that everything
downstream is independent of which extractor ran.

An extractor that holds further files SHALL yield them one at a time, on a
separate call from the one that extracts its text. It SHALL NOT return them all
together: a container holding many entries would otherwise be wholly resident in
memory before the expansion budget could refuse any of it, leaving the ceiling
unreachable in the case it exists for.

An extractor SHALL yield its children for the pipeline to route and SHALL NOT
extract them itself, because doing so would make support for a format depend on
which container it was found in.

A page image offered on its own SHALL be accepted and read as a document. A
photographed or scanned page arrives as an image file in a real dump as often as
it arrives inside a PDF, and refusing it would put that evidence out of reach of
the corpus entirely.

When no registered extractor accepts a file by its declared type and its content
identifies no handled format, ingestion SHALL fail with a typed error naming the
file and its type rather than storing an empty document.

Text SHALL count as usable only if it carries at least one letter or digit in
some script. Text that is whitespace and punctuation alone SHALL be refused as
though it were empty, because it is what failed recognition produces and it is
worse than a failure: it passes an emptiness check, stores, chunks, embeds, and
leaves a document an analyst can list and can never find.

A container SHALL be exempt from the rule that a document must yield usable
text: an archive whose value is entirely in its entries SHALL be stored so that
its children have a parent to hang from.

#### Scenario: A registered format is routed to its extractor

- **WHEN** a file of a supported type is ingested
- **THEN** the extractor that accepts it produces the normalised result

#### Scenario: An unsupported format is refused

- **WHEN** a file no extractor accepts, whose content identifies no handled format, is ingested
- **THEN** ingestion fails with a typed error naming the file and its type

#### Scenario: A file yielding no usable text is refused

- **WHEN** extraction produces no usable text and the file holds nothing to expand
- **THEN** ingestion fails rather than storing a document with empty content

#### Scenario: Text with no letters or digits is refused

- **WHEN** extraction recovers only whitespace and punctuation
- **THEN** ingestion fails rather than storing it as a document

#### Scenario: A page image is ingested as a document

- **WHEN** an image of a page is ingested
- **THEN** it is accepted and read, rather than refused as an unsupported type

#### Scenario: A container's entries are not all resident at once

- **WHEN** a container's entries are read
- **THEN** they are yielded one at a time, so expansion can be stopped partway

#### Scenario: A container with no text of its own is stored

- **WHEN** an archive with no text of its own but with extractable entries is ingested
- **THEN** the archive is stored and its entries become its children

#### Scenario: A file whose declared type no extractor claims is read on its content

- **WHEN** a file carrying a decorated or absent extension holds a format the registry handles
- **THEN** it is routed to that format's extractor and ingested, rather than refused as an unsupported type

#### Scenario: A file with a claimed declared type is never routed on content

- **WHEN** a file's declared type is accepted by a registered extractor
- **THEN** that extractor reads it and the file's content is not consulted to select another

#### Scenario: A content-routed document discloses how it was read

- **WHEN** a file is routed by its content rather than its declared type
- **THEN** the stored document records that route and keeps the filename it carries on disk

#### Scenario: A text-shaped file is not drawn in by decoding alone

- **WHEN** a file no extractor claims carries no identifying signature, though its bytes decode as text
- **THEN** it is refused, rather than stored as a plain-text document

#### Scenario: Attempting a file and extracting it agree

- **WHEN** the pipeline decides whether any extractor can read a file
- **THEN** the decision is the one extraction itself would make, so a file judged readable is not skipped before extraction

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

### Requirement: Ingestion refuses what it cannot safely read

Ingestion SHALL refuse a symbolic link, and SHALL refuse a path that resolves
outside the directory it was asked to read. It SHALL bound the size of a file it
will accept.

These SHALL hold for an entry inside a container as strictly as for a file on
disk. A container is untrusted input, and the paths inside it are chosen by
whoever built it.

#### Scenario: A symbolic link is refused

- **WHEN** a symbolic link is offered for ingestion
- **THEN** it is refused rather than followed

#### Scenario: An oversized entry inside a container is refused

- **WHEN** a container holds an entry larger than the accepted file size
- **THEN** that entry is refused and the container's other entries are still ingested

### Requirement: A legacy binary format is read by converting it to its modern equivalent

A format for which no reader exists SHALL be read by converting the file to its
modern equivalent and handing the result to the extractor that already reads
that equivalent. The converted text SHALL be rendered by that extractor and by
no other, so that one corpus never holds two renderings of the same kind of
document. A second rendering would not surface as an error — it would surface as
retrieval quality, which nothing downstream can detect.

The media type stored for such a document SHALL be the legacy type the file on
disk actually is, not the type it was converted to. The conversion is how the
text was obtained; it is not what the evidence is. Which path produced the text
SHALL be recoverable from the recorded extractor, distinguishing a converted
file from one read directly.

A file whose container contradicts its suffix SHALL be handled on what it is
rather than on what it is named. A file that is already in the modern format
under a legacy suffix SHALL be read directly, with no conversion. A file that is
neither the legacy container nor the modern one SHALL be refused with an error
naming the file and what was expected of it, rather than passed to a converter
whose own failure would name neither.

When the converter is absent, that document SHALL fail with an error naming the
remedy, and the ingest run SHALL continue. The converter SHALL NOT be verified
at the start of a run: unlike the recognition engine, which every page-bearing
document needs, a converter is needed only by the documents that use it, and a
host ingesting none must not be stopped by it.

Every failure of a conversion — a non-zero exit, a timeout, an unwritable
output, an unusable converter — SHALL be reported as the same typed extraction
error every other reader raises, so that one unreadable file fails one document
rather than ending the run.

Whether a converter is available SHALL be reported on the operator-facing status
surfaces, in one vocabulary across all of them, so that a host unable to read
these formats is discoverable before a long ingest rather than during one.

#### Scenario: A legacy document is rendered by the reader for its modern equivalent

- **WHEN** a legacy binary document is ingested and its modern equivalent has a registered reader
- **THEN** the text is produced by that reader, in the same rendering that reader gives the modern format

#### Scenario: The stored type is the legacy type, not the converted one

- **WHEN** a legacy document has been converted and read
- **THEN** the document records the media type of the file on disk, and records an extractor naming both the conversion and the reader that produced the text

#### Scenario: A modern file under a legacy suffix is read directly

- **WHEN** a file named with a legacy suffix is found to already be in the modern format
- **THEN** it is read by the modern format's reader with no conversion, and is recorded as having taken that path

#### Scenario: A file matching neither container is refused

- **WHEN** a file named with a legacy suffix is neither the legacy container nor the modern one
- **THEN** it is refused with an error naming the file and what was expected, rather than handed to the converter

#### Scenario: An absent converter fails the document, not the run

- **WHEN** a legacy document is ingested on a host with no converter installed
- **THEN** that document fails with an error naming the remedy, and the other files in the run are still ingested

#### Scenario: A failed conversion fails one document

- **WHEN** the converter exits non-zero, exceeds its time limit, or writes no output
- **THEN** the failure is reported as a typed extraction error against that file, and the run continues

#### Scenario: Converter availability is reported before a run

- **WHEN** an operator asks either status surface what the instance can do
- **THEN** both report whether a converter is available, using the same vocabulary

### Requirement: A carried-forward location is spelled as a live one is

A location carried forward from an older schema SHALL be spelled by the same
join that spells a location recorded live. Reingesting evidence that has not
changed SHALL therefore record no further location for it and SHALL NOT report a
discovery, whether the record it is compared against was written by this build
or carried across from an older one.

Two spellings of one path SHALL be one location, and the earliest time either
was observed SHALL be the time the surviving location reports. That timestamp is
what the wholeness of the record is judged against, so keeping the later of the
two would present an old record as a young one.

Where an older representation spelled a path in a way no normalisation can
reverse — a source root of `/`, whose concatenation with a name is already its
own normal form — the carry-forward SHALL derive the location from the
representation that still says what was meant, rather than from the spelling
that lost it.

The representations a carry-forward reads from SHALL be preserved, not replaced.
They are the record as it was kept, and they are what makes a carry-forward's
own correctness checkable afterwards.

#### Scenario: A migrated archive entry is one location after reingest

- **WHEN** a store recorded before locations were keyed on the path alone holds an entry whose path was spelled with a redundant component, and the unchanged container is ingested again
- **THEN** one location is recorded for that entry, the run reports it as already known, and the record does not announce a discovery

#### Scenario: Two spellings of one place already recorded collapse

- **WHEN** a carried-forward store holds the same place under two spellings
- **THEN** one location is reported, and it carries the earlier of the two observation times

#### Scenario: A location observed under the filesystem root survives the carry-forward

- **WHEN** a store recorded a location whose ingested root was the filesystem root itself
- **THEN** the carried-forward location is the path a live observation of that file would record

#### Scenario: Two genuinely different places both survive the carry-forward

- **WHEN** a carried-forward store holds one document observed at two paths that differ
- **THEN** both locations are kept, because the paths they were observed at differ
