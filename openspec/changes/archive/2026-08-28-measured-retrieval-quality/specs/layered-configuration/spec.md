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

### Requirement: Configuration fails loudly rather than substituting a default

An unknown profile name, an unknown `contract` key, or an unresolvable `${VAR}`
secret placeholder SHALL be fatal at load. The error SHALL name what was asked
for, and for a profile SHALL also name the profiles that are defined.

A declared embedding library version that does not match the version actually
installed SHALL be fatal at load, and the error SHALL name both the declared and
the installed version. A declaration allowed to drift from reality would
reproduce, one level up, the divergence the fingerprint exists to catch: the
corpus would record a pooling strategy it was not built with.

A contract typo SHALL NOT be tolerated, because an ignored key would leave the
instance running under different corpus rules than the operator wrote down.

A profile key the loader does not recognise SHALL be fatal at load, naming the
key. A profile setting that is quietly ignored costs more than a rejected one:
the instance runs, every document ingests, and only the text is wrong. A
mistyped recognition language is exactly that failure, and it is indistinguishable
from any other mistyped profile key at the point the file is read.

A recognition language the configured engine cannot serve SHALL be fatal when
the engine is constructed, before any document is read, naming the setting and
what the engine accepts. It is checked there rather than at load because only
the engine can answer authoritatively, and building it costs seconds that every
other use of the configuration should not pay.

A reranker named in a profile SHALL be one the instance can construct, and
failure to construct it SHALL be fatal, naming the setting and the failure. It is
checked when the reranker is first needed rather than at load, for the same
reason the recognition engine is: only the implementation can answer, and
building it costs time and possibly a download that `jackryan status` should not
pay. An empty setting means no reranking and SHALL NOT be an error — the absence
of a reranker is a configuration, not a failure to load one.

#### Scenario: Unknown profile is fatal and names the alternatives

- **WHEN** a profile is requested that `config.yaml` does not define
- **THEN** loading fails, naming the requested profile and the defined ones

#### Scenario: Unknown contract key is fatal

- **WHEN** the `contract` block contains a key the loader does not recognise
- **THEN** loading fails, naming the unknown key

#### Scenario: An unset secret placeholder is fatal

- **WHEN** a profile value is `${VAR}` and `VAR` is not in the environment
- **THEN** loading fails naming `VAR`, rather than resolving to an empty string

#### Scenario: A declared library version that is not the installed one is fatal

- **WHEN** the contract declares an embedding library version other than the one installed
- **THEN** loading fails, naming both the declared version and the installed one

#### Scenario: An unknown profile key is fatal

- **WHEN** a profile block contains a key the loader does not recognise
- **THEN** loading fails, naming the unknown key

#### Scenario: An unserviceable recognition language is fatal

- **WHEN** a profile names a recognition language the configured engine cannot serve
- **THEN** the ingest fails before reading any document, naming the setting and what the engine accepts

#### Scenario: A reranker that cannot be constructed is fatal

- **WHEN** a profile names a reranker the instance cannot construct
- **THEN** the search fails naming the setting and the failure, rather than returning the fused order

#### Scenario: No reranker configured is not an error

- **WHEN** a profile names no reranker
- **THEN** the instance searches without one and reports no error
