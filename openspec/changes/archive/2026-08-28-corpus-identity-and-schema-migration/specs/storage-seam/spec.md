## MODIFIED Requirements

### Requirement: The store records and enforces corpus identity

On first initialisation the store SHALL record its schema version and the
configured corpus identity. On every later initialisation it SHALL compare the
recorded values against the configured ones and SHALL refuse to open on a
mismatch, because a corpus is only appendable under the rules that created it.

The two recorded values SHALL be treated differently, because they fail for
different reasons. A schema version below the running one SHALL be carried
forward rather than refused; corpus identity SHALL always be compared and never
migrated. A schema describes how the same evidence is stored, and can be changed
without changing what the evidence means; corpus identity describes what the
stored vectors mean, and nothing can reconcile two answers to that.

The schema SHALL be carried forward before corpus identity is compared. A store
that is migrated and then refused on identity is left improved and undamaged,
whereas comparing identity first would refuse a store the running code could have
read.

Corpus identity SHALL include which embedder produced the vectors, not only the
contract they were configured by. A store filled by the deterministic embedder
SHALL be refused by a real-model configuration, and the reverse. Both produce
vectors of the declared width, so nothing downstream can distinguish them: the
refusal at open is the only point where the difference is still visible.

The refusal SHALL name both the recorded value and the configured one, and SHALL
state how to proceed: restore the configuration the recorded value names, or
reingest under the current one. Two long identity strings differing in one
component tell an operator what happened but not what to do about it, and this
refusal is expected during ordinary work — every fingerprint change produces it
for every existing corpus.

A refusal for the schema version SHALL NOT use the corpus-identity remedy.
"Restore the configuration the recorded value names" cannot be acted on for a
schema the running code no longer contains.

#### Scenario: Reopening under the same contract succeeds

- **WHEN** a store is reopened with the contract that created it
- **THEN** it opens normally

#### Scenario: Reopening under a different contract is refused

- **WHEN** a store is reopened with a different contract fingerprint
- **THEN** initialisation fails, naming the recorded and the configured values

#### Scenario: Reopening under a different embedder is refused

- **WHEN** a store filled by one embedder is reopened by a configuration selecting another
- **THEN** initialisation fails, naming the recorded and the configured values

#### Scenario: The refusal says how to proceed

- **WHEN** a store refuses to open under a different corpus identity
- **THEN** the message states that the configuration can be restored or the casefiles reingested

#### Scenario: An older schema is migrated where an older identity is refused

- **WHEN** a store recorded at an older schema version but a matching corpus identity is opened
- **THEN** it is carried forward and opens, rather than being refused

#### Scenario: The schema is carried forward before identity is compared

- **WHEN** a store has both an older schema version and a different corpus identity
- **THEN** the schema is migrated and the store is then refused on identity
