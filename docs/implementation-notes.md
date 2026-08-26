# Implementation notes

Findings surfaced during work that were deliberately not fixed at the time, so
that a change stays the size it was scoped to be. Each line says what, where,
and why it was parked.

## Parked

- **The fingerprint does not record *which embedder* built the vectors, so a
  deterministic corpus opens under a real-model profile.** Needs its own
  OpenSpec change; deliberately kept out of `contract-covers-embedding-library`
  because the fix crosses the contract/profile split and is a design decision,
  not a patch.

  `Profile.embedder` is infrastructure and `Contract.fingerprint()` covers only
  the contract, so the two embedders are indistinguishable to the store.
  Reproduced end to end during review of PR #12: one data dir, ingest under
  `embedder: deterministic`, then reopen under `embedder: model` — same
  fingerprint, store opens without complaint, and real e5 query vectors are then
  cosine-compared against blake2b hash vectors of the correct width. Vectors of
  the right width that are not comparable: the exact defect class the contract
  guard exists to prevent.

  The gap pre-dates that PR — the embedder choice was never in the fingerprint —
  but adding `embed_library` made the fingerprint state something *positively
  false* for the deterministic path, where before it was merely silent. A
  corpus built by the stand-in now asserts `fastembed==0.8.0` produced it.

  Two candidate fixes, both with consequences worth thinking about rather than
  picking quickly: add an `embedder` field to the contract (simple, but puts an
  infrastructure choice inside the corpus-coupled layer, which the layering
  exists to prevent); or have the composition root write the embedder identity
  into the store's recorded fingerprint separately from `Contract.fingerprint()`
  (keeps the layers apart, but means the fingerprint reported by `/health` is no
  longer the one the store holds). `CLAUDE.md`'s rule that the deterministic
  embedder must never become an implicit fallback is the thing being protected.

- **`scripts/verify_model_paths.py` — `check_real_embedder` bypasses the
  application's model-cache resolution.** It constructs `ModelEmbedder` directly
  with `cache_dir=<tempdir>/models`, instead of going through `build_embedder`,
  which honours `JACKRYAN_MODEL_CACHE`. The Dockerfile sets that variable and
  prefetches the weights into it. So in an image built with
  `--build-arg PREFETCH_MODELS=true` and run offline — the second run mode the
  script's own docstring recommends — this one check tries to download into an
  empty cache and records FAIL, directly beside the script's message that "a
  failure here is a real finding, not a flaky environment". The other two
  embedder loads go through `build_context` and are unaffected. It also means a
  full run fetches the model into three separate temp caches and deletes them.
  Parked: found by review of PR #11 on 2026-08-26; it is a defect in a
  verification script carried by that PR, not in the archive the PR is for, and
  it cannot produce a false PASS. Fix by building the embedder from a `Config`
  through `build_embedder`, and letting the cache outlive the temp workspace.

- **`check_real_embedder`'s own width comparison is dead code.** `ModelEmbedder`
  already raises `EmbeddingError` on a width mismatch, so the script's
  `if width != contract.embed_dimensions` branch is unreachable. This is
  cosmetic, not a hole: a mismatch is still caught and still fails the run with
  an accurate message, verified by forcing one. Noted so nobody "fixes" the
  guard by weakening the one in `ModelEmbedder`.

## Fixed

- **~~The contract fingerprint does not cover the embedding library version.~~**
  Fixed by the `contract-covers-embedding-library` change on 2026-08-26: the
  contract declares `embed_library`, the fingerprint covers it, and a declared
  version that is not the installed one is fatal at both configuration load and
  embedder construction. See `docs/handover.md` for the decisions.

- **~~`scripts/verify_model_paths.py` — the end-to-end check is weaker than its
  comment claims.~~** Fixed in #10 on 2026-08-26, and resolved the other way
  round from what the note proposed: rather than strengthening the check to a
  paraphrase with no shared content word, the comment was corrected to say what
  the check actually establishes — that the vector leg ran and returned, with
  retrieval quality explicitly out of scope. The defect was that the comment
  lied, and it no longer does.
