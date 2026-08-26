## MODIFIED Requirements

### Requirement: The store records and enforces corpus identity

On first initialisation the store SHALL record its schema version and the
configured corpus identity. On every later initialisation it SHALL compare the
recorded values against the configured ones and SHALL refuse to open on a
mismatch, because a corpus is only appendable under the rules that created it.

Corpus identity SHALL include which embedder produced the vectors, not only the
contract they were configured by. A store filled by the deterministic embedder
SHALL be refused by a real-model configuration, and the reverse. Both produce
vectors of the declared width, so nothing downstream can distinguish them: the
refusal at open is the only point where the difference is still visible.

The refusal SHALL name both the recorded value and the configured one.

#### Scenario: Reopening under the same contract succeeds

- **WHEN** a store is reopened with the contract that created it
- **THEN** it opens normally

#### Scenario: Reopening under a different contract is refused

- **WHEN** a store is reopened with a different contract fingerprint
- **THEN** initialisation fails, naming the recorded and the configured values

#### Scenario: Reopening under a different embedder is refused

- **WHEN** a store filled by one embedder is reopened by a configuration selecting another
- **THEN** initialisation fails, naming the recorded and the configured values
