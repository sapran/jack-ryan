## Why

The corpus fingerprint records the embedding model, its width, and now the
library version — but not *which embedder actually produced the vectors*. The
choice between the real embedder and the deterministic stand-in lives in
`Profile.embedder`, and profiles are declared swappable infrastructure, so the
fingerprint cannot see it.

The result is a corpus that can be opened under a configuration that did not
build it. Reproduced during review of PR #12: ingest into a data directory under
`embedder: deterministic`, reopen it under `embedder: model`, and the store
admits it without complaint, because both produce the same fingerprint. Real e5
query vectors are then cosine-compared against blake2b hash vectors of the
declared width. Vectors of the right width that are not comparable — the exact
failure the contract guard exists to prevent, and the one class of corruption
no later check can detect.

Adding `embed_library` made this worse rather than causing it. Before, the
fingerprint was silent about the producer. Now it positively asserts
`fastembed==0.8.0` built vectors that a hash function built. A guard that states
something false is worse than one that says nothing, because it invites trust.

The underlying error is a misclassification. `profiles` are documented as
"swappable infrastructure — changing one is always safe", and that is true of
every profile field except this one: changing `embedder` silently invalidates
every vector in the corpus. It has been corpus-coupled all along while sitting
in the layer that promises it is not.

## What Changes

- Corpus identity is computed from the contract **and the embedder that was
  actually constructed**, rather than from the contract alone. The store records
  and enforces that combined value.
- **BREAKING**: the recorded fingerprint string changes, so a corpus built
  before this change is refused until reingested. As with the previous change,
  this is the correct outcome and is nearly free while no corpus outside
  development exists.
- A corpus built with the deterministic embedder is refused by a real-model
  configuration, and the reverse. The refusal names both, so the cause is
  legible rather than a hex mismatch.
- The fingerprint reported by `/health` and by `jackryan status` becomes the one
  the store actually enforces. Today they report `Contract.fingerprint()`, which
  after this change is only a component of corpus identity — reporting a value
  that does not guard anything is how an operator ends up debugging the wrong
  string.
- `profiles` documentation stops claiming that changing any profile value is
  safe, and names `embedder` as the exception with its consequence.

## Capabilities

### New Capabilities

None. This closes a hole in capabilities that already exist.

### Modified Capabilities

- `layered-configuration`: corpus identity is the contract plus the embedder
  actually built, not the contract alone; and the profile layer's "always safe
  to change" claim is corrected for `embedder`.
- `storage-seam`: what the store records and enforces is corpus identity in that
  wider sense, and a cross-embedder reopen is refused.

## Impact

- `src/jackryan/config.py` — a `corpus_fingerprint(contract, embedder_name)`
  function beside `Contract.fingerprint()`; the latter stays as the contract's
  own identity and becomes one input to the former.
- `src/jackryan/app.py` — `build_context` must construct the embedder *before*
  initialising the store, which is the reverse of the present order.
- `src/jackryan/server.py`, `src/jackryan/cli.py` — report the enforced value.
- `src/jackryan/embedding/port.py` — `EmbedderPort.name` becomes load-bearing
  rather than incidental, and is documented as such.
- Every existing corpus — refused until reingested.
- `docs/implementation-notes.md` — the parked finding moves to fixed.
