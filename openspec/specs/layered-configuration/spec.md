# layered-configuration Specification

## Purpose

Defines how an instance is configured: a corpus-coupled `contract` whose values
cannot change once documents exist, swappable infrastructure `profiles`, the
precedence between sources, and the rule that a misconfiguration stops the
instance rather than being silently replaced by a default.

## Requirements

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
