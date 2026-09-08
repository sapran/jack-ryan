## Purpose
Defines how an ingest run states what it did not cover, how that statement is
recorded against the casefile, and the three-state verdict a casefile discloses
about its own contents — so that an empty search result can be told apart from
missing evidence. Absence of evidence is only readable as absence if the corpus
can say how completely it was filled; where no record can answer, the verdict is
unknown and never complete.

## ADDED Requirements

### Requirement: An ingest run reports every reason it did not cover what it was offered

An ingest run SHALL report whether everything offered to it reached the corpus,
and SHALL carry the reasons it did not. The verdict and the reasons SHALL be one
derivation rather than two accumulations: a run reported as complete while
carrying a reason, or as incomplete with no reason to give, is the failure this
requirement exists to make unreachable.

A reason SHALL be reported for each of: a bound that stopped expansion, a
document that failed to be read, an entry a container's reader refused, a file
offered by a folder walk that no registered extractor accepts, and entries a
container's listing named that its reader never delivered.

A file a folder walk offered and no extractor accepts SHALL be reported rather
than passed over in silence. Silence is indistinguishable from having ingested
it, and an analyst searching for what that file said finds nothing — which reads
as the corpus not mentioning it.

Entries a container listed but never delivered SHALL be reconciled against the
count the container's own extraction published, rather than by re-deciding
whether an entry was too large. A reader that drops an entry between listing it
and delivering it leaves the container's own searchable text naming a document
that will never exist.

A shortfall SHALL NOT be reported twice. Where a bound stopped a container's
expansion, or that expansion raised, the reason already reported is the cause and
the shortfall is its consequence.

#### Scenario: A run that read everything offered reports itself complete

- **WHEN** every file offered to an ingest run is read and stored
- **THEN** the run reports itself complete and carries no reasons

#### Scenario: A failed document makes the run incomplete

- **WHEN** a run stores some of the files offered to it and one of them fails to be read
- **THEN** the run reports itself incomplete and its reasons say that an offered item failed

#### Scenario: An offered file no extractor accepts is reported, not skipped in silence

- **WHEN** a folder offered to an ingest run holds a file no registered extractor accepts
- **THEN** the run reports that file as having no extractor, and reports itself incomplete

#### Scenario: An entry the reader refused reaches the caller

- **WHEN** a container's reader refuses one of its entries
- **THEN** the run's report carries that refusal, naming the container and the entry, and reports itself incomplete

#### Scenario: Entries the listing names but the reader never delivered are reported

- **WHEN** a container's listing names more entries than its reader delivers
- **THEN** the run reports how many of the listed entries were not delivered

### Requirement: Every surface returning an ingest result carries its coverage, in one vocabulary

Every surface that returns an ingest result SHALL carry the run's coverage
verdict and its reasons, and SHALL do so in one vocabulary. The reasons a caller
weighs before trusting the corpus SHALL be rendered once and shared, because two
renderings of that answer are free to diverge and the divergence is invisible.

A human surface SHALL state in its own summary that a run did not cover
everything it was offered, and SHALL list the reasons.

An incomplete run SHALL NOT be reported as a failure. What was stored is a real
result, and a caller offering a folder of mixed content is not failing.

#### Scenario: Both human surfaces return the same ingest result

- **WHEN** the same folder is ingested through each human surface
- **THEN** both return the same fields under the same names, with the same coverage verdict and the same reasons

#### Scenario: An incomplete run says so in the human summary

- **WHEN** a run that did not cover everything offered is reported to a person
- **THEN** the summary says so and lists each reason, and the counts it already printed are unchanged

### Requirement: A casefile records what each ingest run covered

A completed ingest run SHALL be recorded against its casefile, carrying what it
covered, what it did not, and how many documents the casefile held both before
the run began and after it finished.

A run that raised part way SHALL NOT be recorded, because recording it would
mean deciding what a half-run covered and any such answer is a guess.

That absence SHALL be detectable rather than merely true. A run that raised, was
killed, or failed to write its own record leaves the documents it already stored
behind it, so the counts either side of each recorded run SHALL be compared:
where a run began against more documents than the previously recorded run left,
the record has stopped accounting for the corpus and SHALL say so. Absence alone
is not sufficient — it reveals only an unrecorded *first* run, and leaves a
casefile whose later run aborted reading as though every document in it were
accounted for.

The record SHALL outlive the process that wrote it, and SHALL be removed with the
casefile it describes.

#### Scenario: A completed run is recorded

- **WHEN** an ingest run completes
- **THEN** a record exists against that casefile carrying what the run covered and what it did not

#### Scenario: A recorded run survives the store being reopened

- **WHEN** a store holding a recorded run is closed and opened again
- **THEN** the record still reports what that run covered

#### Scenario: Deleting a casefile deletes its ingest records

- **WHEN** a casefile holding recorded ingest runs is deleted
- **THEN** its records are gone and no other casefile's records are affected

#### Scenario: A run that raised part way is not recorded, and its absence is detectable

- **WHEN** an ingest run raises after storing some of what it was offered, and a later run completes cleanly
- **THEN** no record exists for the run that raised, and the record reports that it has stopped accounting for what the casefile holds

### Requirement: A casefile discloses what is recorded about its coverage, and says unknown when nothing is

A casefile SHALL disclose a coverage verdict of one of three values — complete,
incomplete, or unknown — together with the counts the record holds behind it.

The verdict SHALL be unknown on any of three grounds: no run is recorded; the
casefile holds documents that predate its earliest recorded run; or the record
has stopped accounting for what the casefile holds. None SHALL be reported as
complete — a casefile whose evidence no record accounts for cannot be claimed to
hold everything offered to it, however clean every later run was.

The third ground is not a variant of the first two. They concern the beginning
of the record; it concerns the middle, and it is the only one that reaches a run
which aborted after a clean one. A verdict resting on the first two alone
reports such a casefile complete while files it was offered are missing.

A recorded limitation SHALL outrank an unaccounted-for corpus in the verdict,
because a known gap is a fact worth stating while unknown only says the record
cannot answer. No state SHALL be hidden by that ordering — every surface SHALL
report the counts beside the word.

The verdict SHALL be a rule of the service layer rather than of the store, so
that the store cannot hold a second opinion about what its counts add up to.

Where the verdict is not complete, the disclosure SHALL say that an empty search
result may mean missing evidence rather than absence.

#### Scenario: A casefile with no recorded run reports unknown

- **WHEN** a casefile has no recorded ingest run
- **THEN** its coverage is unknown, and the disclosure says nothing about it can be claimed as complete

#### Scenario: Documents predating the record keep the verdict unknown

- **WHEN** a casefile held documents before its earliest recorded run began, and every recorded run since was clean
- **THEN** its coverage is unknown, and the disclosure says how many documents predate the record

#### Scenario: A recorded limitation makes the casefile incomplete

- **WHEN** a recorded run for a casefile reported a limitation
- **THEN** its coverage is incomplete, and the disclosure says an empty search may mean missing evidence rather than absence

#### Scenario: A casefile filled only by clean recorded runs reports complete

- **WHEN** every document in a casefile arrived through a recorded run that reported no limitation
- **THEN** its coverage is complete, and the disclosure says how many runs are recorded

#### Scenario: An aborted run between clean ones keeps the verdict unknown

- **WHEN** a casefile's recorded runs are all clean, but a run between them raised part way and left documents behind
- **THEN** its coverage is unknown rather than complete, and the disclosure says the record has stopped accounting for what the casefile holds
