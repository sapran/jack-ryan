# Implementation notes

Findings surfaced during work that were deliberately not fixed at the time, so
that a change stays the size it was scoped to be. Each line says what, where,
and why it was parked.

## Parked

- **`scripts/verify_model_paths.py` — the end-to-end check is weaker than its
  comment claims.** The comment above the search call says the query "shares no
  content word with the text" and names `"who signed"`, but the code sends
  `"who was awarded the lease"`, which shares *awarded* and *lease* with the
  corpus text it ingests. FTS alone would match it, so the check proves the
  vector leg ran and returned, not that semantic retrieval beat keywords.
  Parked: found while running the script on 2026-08-26 to record its result in
  `docs/handover.md`; fixing it is a change to a verification script, not to the
  archive it was run for. Fix by querying a genuine paraphrase with no shared
  content word, and asserting the hit is vector-only.

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

- **The contract fingerprint does not cover the embedding library version.**
  Fully written up in `docs/handover.md` — it has its own section there, with a
  suggested three-step fix. Repeated here only so this file is a complete index
  of what is known and unfixed.
