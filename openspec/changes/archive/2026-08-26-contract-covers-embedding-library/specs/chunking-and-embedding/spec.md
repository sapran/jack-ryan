## MODIFIED Requirements

### Requirement: An embedder that cannot load fails loudly

When the configured embedder cannot be loaded, ingestion SHALL fail with a typed
error. It SHALL NOT fall back to another implementation, because vectors that
silently mean something different would corrupt the corpus in a way no later
check could detect.

An embedding whose width disagrees with the contract SHALL be refused.

The embedder SHALL additionally refuse to load when the installed embedding
library is not the version the contract declares. This is the same failure in a
subtler form: the library loads, the model loads, and the vectors are the right
width, but they are not comparable with the ones already stored. Width and
model name are not sufficient evidence that two vectors mean the same thing.

#### Scenario: A failed embedder stops ingestion

- **WHEN** the configured embedder cannot be loaded
- **THEN** ingestion fails with a typed error and no fallback is used

#### Scenario: A mis-sized embedding is refused

- **WHEN** an embedding's width disagrees with the contract
- **THEN** it is refused rather than stored

#### Scenario: An embedder built on the wrong library version refuses to load

- **WHEN** the installed embedding library differs from the version the contract declares
- **THEN** the embedder fails with a typed error naming both versions, rather than producing vectors
