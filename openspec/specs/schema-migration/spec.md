# schema-migration Specification

## Purpose

Defines how a store carries an existing corpus forward when the schema changes:
what a migration step may do, in what order steps are applied, what is copied
before anything is rewritten, and what is refused rather than migrated. The
distinction it rests on is that a schema describes how the same evidence is
stored and can be changed, while corpus identity describes what the stored
vectors mean and cannot.

## Requirements

### Requirement: A store is carried forward by an ordered ladder of additive steps

The store SHALL define a frozen baseline schema and an ordered sequence of
migration steps. The baseline SHALL be the shape the store creates from nothing,
and once a step exists above it the baseline SHALL NOT be edited again.

The running schema version SHALL be derived from the ladder rather than written
independently, so that adding a step and declaring the version cannot disagree.

A store whose recorded version is below the running one SHALL be carried forward
by applying, in order, every step above its recorded version. A store already at
the running version SHALL be left untouched.

Every step SHALL be additive. A step MAY add a column with a constant default,
create a table, an index or a trigger, or drop and recreate a sidecar structure
that is wholly derivable from the tables it summarises. A step SHALL NOT drop or
rewrite a table that holds evidence, and SHALL NOT change a uniqueness
constraint. This SHALL be enforced by inspecting the steps themselves, not only
by convention, because a rule that only a comment states is a rule that a later
change will break without noticing.

The steps and the baseline SHALL produce the same schema. A store built fresh
from the baseline and then walked up the ladder SHALL be indistinguishable from a
store built by the current code, and this SHALL be checked rather than assumed.

#### Scenario: An older store is carried forward

- **WHEN** a store recorded at an older schema version is opened
- **THEN** every step above that version is applied in order and the recorded version is updated

#### Scenario: A current store is left alone

- **WHEN** a store already at the running schema version is opened
- **THEN** no step runs and nothing is written

#### Scenario: The ladder and the baseline agree

- **WHEN** a store created from the baseline and walked up the ladder is compared with one created by the current code
- **THEN** their schemas are identical

#### Scenario: A destructive step is refused before it can ship

- **WHEN** the migration steps are inspected
- **THEN** any step that would drop or rewrite a table holding evidence is a failure

### Requirement: The first rung is climbed by every store, including new ones

The baseline SHALL be frozen far enough back that the ladder's first step is
applied to a store created today.

A migration runner that only ever executes against a hand-built fixture is
exercised by nothing an operator does, and rots between the day it is written and
the day it is first needed — which is the day it matters most. Freezing the
baseline one version behind the current schema makes every fresh store climb the
same rung a migrated store climbs.

#### Scenario: A fresh store exercises the migration runner

- **WHEN** a store is created from nothing
- **THEN** it is built from the baseline and carried up the ladder, not created at the running version directly

### Requirement: A store is backed up before it is changed

Before any step runs, the store SHALL be copied beside itself, named for the
version being left behind. The copy SHALL NOT be deleted afterwards.

A migration is the one operation that rewrites a corpus in place, and this
project's evidence is not reconstructible from anywhere else once the originals
have left the analyst's hands. The copy SHALL be a usable store in its own right,
not a file copy taken while writes are in flight.

If the copy cannot be made, the store SHALL be refused rather than migrated, and
the error SHALL name the path it tried to write.

#### Scenario: A backup exists before the first step runs

- **WHEN** a store is carried forward
- **THEN** a copy of it as it was beforehand exists beside it, and opens as a store

#### Scenario: A store that cannot be backed up is not migrated

- **WHEN** the backup cannot be written
- **THEN** the store is refused, naming the path, and no step has run

### Requirement: What cannot be migrated is refused with its own message

A store older than the oldest migratable version, or newer than the running
binary, SHALL be refused rather than migrated.

The refusal SHALL be distinct from the corpus-identity refusal. They fail for
different reasons and have different remedies: an identity mismatch is resolved
by restoring the configuration that created the corpus, which is meaningless
advice for a schema that no longer exists in the running code. The schema refusal
SHALL name the recorded version, the running version, and what the operator can
do.

#### Scenario: A store from a newer binary is refused

- **WHEN** a store recorded at a version above the running one is opened
- **THEN** it is refused, naming both versions, rather than being left to fail later

#### Scenario: The schema refusal does not borrow the identity remedy

- **WHEN** a store is refused for its schema version
- **THEN** the message describes a schema remedy, not restoring a configuration
