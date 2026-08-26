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
