## MODIFIED Requirements

### Requirement: An embedder that cannot load fails loudly

When the configured embedder cannot be loaded, ingestion SHALL fail with a typed
error. It SHALL NOT fall back to another implementation, because vectors that
silently mean something different would corrupt the corpus in a way no later
check could detect.

An embedding whose width disagrees with the contract SHALL be refused.

The embedder's declared width SHALL be compared with the contract's before the
store is opened, and a disagreement SHALL be refused naming both widths and
saying which side to change.

The reach of this check SHALL be stated rather than assumed. An embedder built
from configuration takes its width *from* the contract, so the two cannot
disagree by that route; the comparison guards the seam where an embedder is
supplied directly, and it becomes the guard it reads like on the day an embedder
reports a width it was not given — one that learns its width from the model it
loaded. A contract declaring a width the configured model does not actually
produce is a different failure, caught by the embedder when it loads, part-way
through an ingest rather than before the store is opened.

The check SHALL be made before the store is constructed and not after, because
once the store is initialised the vector index has been created at the contract's
width and a valid corpus identity recorded — leaving a wrongly sized store on
disk that opens cleanly.

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

- **WHEN** an instance is assembled with a supplied embedder whose declared width differs from the contract's
- **THEN** it fails naming both widths, and no store file is created
