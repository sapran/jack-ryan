## MODIFIED Requirements

### Requirement: Configuration is layered into a corpus contract and swappable profiles

Configuration SHALL be split into two layers with different lifetimes. The
`contract` layer is corpus-coupled: changing any value invalidates an existing
corpus. The `profiles` layer is infrastructure and SHALL be safe to change at
any time, with one exception named below.

The contract SHALL declare the values the pipeline actually consumes: the chunk
size and overlap used to divide text, the model and dimensionality used to embed
it, and the embedding library and exact version that produces the vectors. Every
declared value SHALL be one the pipeline reads, so that the fingerprint covers
exactly what determines corpus identity and nothing else.

The embedding library version is corpus-coupled because one model under two
versions of the same library can produce vectors that are not comparable — a
change of pooling strategy being the case that has already occurred. Such
vectors are the declared width and are otherwise well-formed, so no later check
can detect them.

The profile's choice of embedder is the exception to the profile layer being
safe to change. It selects which implementation produces the vectors, so
changing it invalidates every vector already stored, exactly as a contract value
would. It remains in the profile layer because it is a deployment choice, and
corpus identity accounts for it separately rather than by duplicating it into
the contract, where two copies could disagree.

Extraction settings — the recognition engine, its language, the escalation
floor, and whether the vision rung is enabled — SHALL live in the profile. They
change the text a document yields, but only for documents ingested after the
change, and the difference they produce is visible in the text itself rather
than hidden in vectors of the correct width. That is the same reasoning that
keeps the extraction engine out of the contract, and it is why a document
records which rung produced its text: what the fingerprint does not guard, the
per-document record makes findable.

Retrieval settings — which reranker is used if any, how many candidates it sees,
and how wide a result's text may be — SHALL live in the profile, and SHALL NOT
enter corpus identity. They are read at query time and write nothing: no vector,
no chunk, no stored text. Changing one changes what the next search returns and
leaves the corpus exactly as it was, so no store need ever be refused for them.
This is a stronger claim than the one made for extraction settings, which do
change stored text and are kept out of the contract on a deliberate trade;
retrieval settings leave no residue at all.

Enrich settings — whether a per-chunk contextual summary, the heading path above
a chunk, or any other context is folded into what is embedded — SHALL live in
the contract, together with the identity of whatever produces that text. The
reason is the one already accepted for the embedding library version: folding
context into a chunk before embedding it changes what the vector means, the
vectors are the declared width and otherwise well-formed, and no later check can
tell a corpus holding both kinds apart. A switch alone is not sufficient: a
different summarising model writes different summaries, so the model that wrote
them is corpus-coupled by the same argument.

The classification test is therefore not which pipeline stage a setting belongs
to, but whether it changes what the embedder is given *without changing the text
the document stores*. That is what separates this case from extraction settings,
which change what the embedder is given too — by changing the extracted text
itself, which leaves the difference legible in the corpus and recorded per
document. Folded-in context leaves the stored chunk exactly as it was and the
vector different, and nothing records that it happened.

The contract's coverage claim SHALL hold in both directions. That every declared
value is one the pipeline reads is one half; the other is that every setting able
to change a stored vector without changing any stored text SHALL enter corpus
identity — declared in the contract, or composed into the identity as the
embedder above is. Turning such a setting on then refuses an existing corpus and
names a reingest, rather than appending vectors built another way. A setting of
this kind left in the profile layer and out of corpus identity would deliver the
exact failure corpus identity exists to prevent, through the layer declared safe
to change.

Precedence SHALL be: a real environment variable, then `config.yaml`, then the
built-in default. `config.yaml` SHALL be read only when `JACKRYAN_CONFIG` is
set, so a bare checkout runs on built-in defaults with no file present.

#### Scenario: Defaults apply with no configuration file

- **WHEN** an instance starts with no `JACKRYAN_CONFIG` set
- **THEN** the built-in contract applies and the profile is `local`

#### Scenario: An environment variable outranks the file

- **WHEN** `config.yaml` sets `default_profile: local` and `JACKRYAN_PROFILE` is `remote`
- **THEN** the `remote` profile is selected

#### Scenario: An empty profile variable is treated as unset

- **WHEN** `JACKRYAN_PROFILE` is empty or whitespace
- **THEN** `default_profile` from the file is used

#### Scenario: Every contract value is consumed

- **WHEN** the contract is inspected against the pipeline
- **THEN** each declared value is read by chunking or by embedding

#### Scenario: The contract declares the embedding library version

- **WHEN** the contract is inspected
- **THEN** it declares the embedding library and the exact version the corpus was built under

#### Scenario: Extraction settings do not change corpus identity

- **WHEN** the recognition engine or its language is changed
- **THEN** corpus identity is unchanged and an existing corpus still opens

#### Scenario: Retrieval settings do not change corpus identity

- **WHEN** the reranker, its candidate depth, or the result window budget is changed
- **THEN** corpus identity is unchanged and an existing corpus still opens

#### Scenario: Every setting that changes what is embedded is in the contract

- **WHEN** a document is ingested and the text handed to the embedder is inspected
- **THEN** it is the chunk's own text, divided by the contract's chunk size and overlap, with no context folded into it
