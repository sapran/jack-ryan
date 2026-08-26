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

- **The contract fingerprint does not cover the embedding library version.**
  Fully written up in `docs/handover.md` — it has its own section there, with a
  suggested three-step fix. Repeated here only so this file is a complete index
  of what is known and unfixed.
