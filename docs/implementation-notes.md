# Implementation notes

Findings surfaced during work that were deliberately not fixed at the time, so
that a change stays the size it was scoped to be. Each line says what, where,
and why it was parked.

## Parked

- **Nothing bounds how long an ingest may spend, and recognition makes that
  matter.** `ExpansionBudget` bounds nesting depth, descendant count and
  extracted bytes — not time. `docs/design.md` § 5 names "a per-document time
  budget" as part of the Finalize step; no such thing exists in
  `src/jackryan/`. Recognition raises the cost of a page from milliseconds to
  seconds, and the `extraction-quality-gate` change makes image files ingestable
  for the first time, so an archive of five hundred small photographs sits well
  inside the byte ceiling and costs roughly a quarter-hour of CPU. Not
  introduced by that change — the shipped extractor already ran recognition on
  every PDF by docling's default, and the change makes born-digital PDFs
  *cheaper* — but it widens the input surface that reaches it. Parked: a time or
  work budget is its own design (per document? per run? what happens to what was
  already stored when it expires?) and belongs with the retry ledger, not inside
  a change about extraction quality. docling's own `document_timeout` pipeline
  option is the likely lever.

- **The store has no migration path, and `text_source` spent the last of the
  free schema changes.** `_SCHEMA` is `CREATE TABLE IF NOT EXISTS`, there is no
  `ALTER TABLE` anywhere, and `_verify_meta` refuses a store whose recorded
  `schema_version` differs from the running one. So every schema change so far
  has meant "recreate the corpus", which has been free only because no corpus
  exists outside development. The next one will not be. Parked: writing a
  migration mechanism is a change of its own, and doing it speculatively before
  the first real corpus would be building against a guess.

- **The embedder's width is never checked against the contract's, though the
  composition root now has both.** `build_context` constructs the embedder
  before sizing the store, so `chosen.dimensions` and
  `contract.embed_dimensions` are both in hand one line apart — and are not
  compared. `build_context(config, embedder=DeterministicEmbedder(64))` against
  a 1024-wide contract creates the vector table at 1024, records a valid
  identity, opens cleanly, and then fails on every chunk deep inside an ingest.
  One line would turn that into a boot-time refusal at the same depth as the
  identity guard. Parked: found by review of the change that created the
  adjacency; it is a different guard from the one that change is about.

- **Corpus identity is an unescaped `|`-joined string over operator-supplied
  values.** `Contract.fingerprint()` and `corpus_fingerprint` both join with `|`
  and `=` without escaping, so an `embed_model` containing `|embedder=` produces
  an identity that cannot be parsed back unambiguously. No two-corpora collision
  was demonstrated and the shape pre-dates both fingerprint changes, but this is
  the one string whose entire job is that two different corpora never share an
  identity. Fix by escaping separators in values, or by hashing the components.

- **Naming drift: the store still calls corpus identity `contract`.**
  `initialize(contract_fingerprint=...)`, the `store_meta` key, the refusal text
  and the `"contract"` field in `/health` and `jackryan status` all say
  *contract*, while the specs and docs say *corpus identity* and the value now
  includes a profile setting. An operator comparing a refusal against `/health`
  sees a key named `contract` holding something wider. Parked because renaming
  the `store_meta` key needs a migration or a documented legacy name, and the
  JSON field is a published surface — both bigger than the change that exposed
  it.

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

- **~~The fingerprint did not record which embedder built the vectors.~~** Fixed
  by the `corpus-identity-covers-the-embedder` change on 2026-08-26. Of the two
  candidate fixes recorded here, the second was taken: corpus identity is
  composed at the composition root from the contract plus the embedder actually
  constructed, rather than adding an `embedder` field to the contract. An
  `embedder` contract field would have put an infrastructure selection in the
  corpus-coupled layer *and* duplicated a setting that already exists in the
  profile — two copies that can disagree, which is the shape of the bug being
  closed. The noted downside of the chosen fix was dealt with rather than
  accepted: `/health` and `jackryan status` now report the enforced identity, so
  the value an operator sees is the value that refused them.
