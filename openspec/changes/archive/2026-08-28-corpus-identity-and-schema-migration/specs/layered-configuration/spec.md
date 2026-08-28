## MODIFIED Requirements

### Requirement: The contract has a fingerprint that changes with any value

The contract SHALL produce a stable fingerprint string covering every
corpus-coupled value, the embedding library version among them. Changing any one
of them SHALL change the fingerprint.

Corpus identity SHALL be that fingerprint combined with the identity of the
embedder actually constructed. The contract alone is not sufficient, because two
instances can agree on every contract value and still fill a corpus with vectors
that are not comparable — one from the real embedder, one from the deterministic
stand-in, both of the declared width. Corpus identity SHALL be computed where
both are known, rather than by copying the embedder choice into the contract.

The value reported to an operator as the instance's corpus identity SHALL be the
value the store enforces, so that a refusal can be explained by comparing the
strings shown.

A component's value SHALL NOT be able to read as another component. Corpus
identity is assembled by joining named components, so a value containing a
separator would otherwise produce an identity that asserts something the instance
is not configured for — an `embed_model` carrying an embedder clause makes the
reported identity and the refusal message name an embedder that is not in use.
Separators SHALL therefore be escaped within each component's value.

The escaping SHALL leave every already-recorded identity unchanged. A fix to how
identity is composed must not itself invalidate the corpora it protects, so the
characters escaped SHALL be only those no current value contains.

#### Scenario: A changed contract value changes the fingerprint

- **WHEN** two contracts differ in any single value
- **THEN** their fingerprints differ

#### Scenario: A changed embedding library version changes the fingerprint

- **WHEN** two contracts differ only in the declared embedding library version
- **THEN** their fingerprints differ, and a store built under one refuses the other

#### Scenario: A changed embedder changes corpus identity

- **WHEN** one contract is combined with the real embedder and with the deterministic embedder
- **THEN** the two corpus identities differ

#### Scenario: The reported identity is the enforced one

- **WHEN** an instance reports its corpus identity
- **THEN** the value reported is the one the store records and compares

#### Scenario: A value carrying a separator cannot impersonate another component

- **WHEN** a contract value contains text shaped like another component of the identity
- **THEN** the resulting identity differs from the one that component would genuinely produce

#### Scenario: Escaping does not invalidate an existing corpus

- **WHEN** an identity is composed from values that contain no escaped character
- **THEN** the string is unchanged, and a store recorded before the change still opens
