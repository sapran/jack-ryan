## Context

Two layers with different lifetimes: `contract` is corpus-coupled and frozen
once documents exist; `profiles` are infrastructure and safe to change. The
fingerprint is computed from the contract alone, and the store records it and
refuses to open under a different one.

`Profile.embedder` selects between `ModelEmbedder` and `DeterministicEmbedder`.
The deterministic one produces blake2b-derived vectors of the declared width
that carry no meaning; it exists so tests need no model download, and
`CLAUDE.md` states it must never become an implicit fallback. It is selected
only by explicit configuration — which is the guard that was thought sufficient.

It is not sufficient, because explicit selection controls *what happens next*,
not *what already happened*. A data directory carries no memory of which
embedder filled it, so the next process to open it is free to disagree with the
one that wrote it.

## Goals / Non-Goals

**Goals:**

- A corpus records which embedder produced its vectors, and refuses a
  configuration that would append or query with a different one.
- The value reported to operators is the value that guards.
- The correction is stated where the misclassification lives: the profile layer
  claims every field is safe to change, and one is not.

**Non-Goals:**

- Moving `embedder` out of `profiles` into `contract`. See below.
- Making the deterministic embedder safe to mix. It is not, and the fix is
  refusal rather than reconciliation.
- Migrating existing corpora.
- Detecting an embedder that changes behaviour without changing its name. That
  is the same class as a library changing behaviour without changing its
  version, and is what `embed_library` already covers for the real embedder.

## Decisions

### Corpus identity is contract + embedder, computed at the composition root

The alternative was to add an `embedder` field to `Contract`, which is a smaller
diff and makes `Contract.fingerprint()` complete on its own. It is rejected
because it would put an infrastructure selection inside the corpus-coupled
layer, and then the same value would exist in two places — `contract.embedder`
and `profile.embedder` — with nothing keeping them honest. A duplicated setting
that can disagree with itself is how this defect was introduced in the first
place.

Instead `corpus_fingerprint(contract, embedder_name)` composes the two, and
`build_context` — the one place wiring happens — is what calls it. The contract
keeps its own fingerprint as a component. Nothing moves between layers; the
layers are simply combined at the point where both are known.

This does mean corpus identity is no longer a property of the config file alone.
That is the honest position: it never was. Two config files that differ only in
which profile is selected produce different corpora, and the fingerprint should
say so.

### The reported fingerprint becomes the enforced one

`/health` and `jackryan status` currently report `Contract.fingerprint()`. After
this change that value guards nothing by itself. Continuing to report it would
leave an operator comparing a string that cannot explain the refusal they are
looking at — the specific trap of showing a number that is *nearly* the right
one. They report `corpus_fingerprint` instead.

### `EmbedderPort.name` becomes part of the contract between layers

`name` exists today as an incidental label. It now determines whether a corpus
opens, so it is documented as load-bearing: an implementation that changes its
`name` invalidates every corpus it has written, and two implementations must
never share one. This is a small surface to depend on, and the alternative —
deriving identity from the class name — would make a refactor rename break
corpora silently.

### The refusal names the embedders, not just the hashes

`_verify_meta` reports the recorded and configured values, which are now longer
strings differing in one component. The message stays as it is rather than
growing a special case: the two strings are printed in full and the differing
component is visible. A dedicated "you changed embedder" message would be
friendlier and would also be one more thing to keep true as the fingerprint
grows components.

## Risks / Trade-offs

- **Every existing corpus is refused.** Second breaking fingerprint change in a
  day. Both are nearly free now and expensive later, and the alternative is
  shipping a guard that is knowingly incomplete.
- **`build_context` must build the embedder before opening the store**, which
  reverses the current order. If constructing the embedder ever became
  expensive or fallible in a way that should not block opening the store for
  read-only work, this ordering would have to be revisited. Today
  `ModelEmbedder` defers all loading to first use, so construction is cheap and
  cannot fail — but that is a property being relied on, and it is worth stating
  rather than discovering.
- **A test that builds a `Context` with an injected embedder now affects corpus
  identity.** `build_context(config, embedder=...)` exists for exactly that, and
  the injected embedder's `name` is what gets recorded. That is correct, but it
  means a test double named something new writes a corpus no other configuration
  can open. Test doubles should reuse `deterministic` unless they mean otherwise.
- **This does not make the deterministic embedder's vectors meaningful.** It
  stops them being confused with real ones. Anything measuring retrieval quality
  against a deterministic corpus is still measuring nothing, which is a
  different problem recorded in `docs/handover.md`.
