## MODIFIED Requirements

### Requirement: An embedder that cannot load fails loudly

When the configured embedder cannot be loaded, ingestion SHALL fail with a typed
error. It SHALL NOT fall back to another implementation, because vectors that
silently mean something different would corrupt the corpus in a way no later
check could detect.

An embedding whose width disagrees with the contract SHALL be refused.

The embedder's declared width SHALL additionally be compared with the contract's
before the store is opened. Both values are known at the point the instance is
assembled, and comparing them there turns a failure that would otherwise appear
part-way through an ingest — after the vector index has been created at the wrong
width and a valid identity recorded — into a refusal before anything is written.
The refusal SHALL name both widths and say which side to change, noting that the
contract's width is corpus-coupled and changing it forces a reingest.

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

#### Scenario: A mis-sized embedder is refused before a store is created

- **WHEN** an instance is assembled with an embedder whose width differs from the contract's
- **THEN** it fails naming both widths, and no store file is created
