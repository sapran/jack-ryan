## Why

Four findings sat parked in `docs/implementation-notes.md` because none of them
blocked the change that found them. They are collected here because they share a
property the others do not: **each becomes more expensive, or impossible, once a
real corpus exists.** No corpus exists outside development today. That is the
whole reason to do them now rather than when they bite.

**The store cannot migrate, and has just spent the last free schema change.**
`_SCHEMA` is `CREATE TABLE IF NOT EXISTS`, there is no `ALTER TABLE` anywhere,
and `_verify_meta` refuses any store whose recorded `schema_version` differs from
the running one. Every schema change so far has therefore meant "recreate the
corpus", which cost nothing because the only corpora were disposable. The M3 and
M4 roadmap adds at least three more — per-chunk summaries, mentions, and the
operating picture's entry table. The first operator with real evidence in a
casefile will meet the first one of those as a wall.

**Corpus identity is assembled by unescaped string joining.** `|` and `=` are
separators and no value escapes them, so a value containing a separator produces
an identity that reads as something it is not. State the reach precisely, because
the parked note overstated it: no two-corpora collision is constructible through
a configuration file, since a collision needs two free-text components to trade
text across a separator and only `embed_model` is free — `embed_library` is
canonicalised and verified against the installed distribution, the chunk sizes
and width are integers, and the embedder name is a two-value enum. What is
reachable today is a **deceptive identity**: `embed_model` containing
`|embedder=model` yields a `/health` value and a refusal message that assert an
embedder the instance is not running. The unreachable collision becomes reachable
the day a third embedder is added, because `EmbedderPort.name` is an unvalidated
`str`.

**The composition root holds two vector widths and never compares them.**
`build_context` constructs the embedder, then sizes the vector index from the
contract, with `chosen.dimensions` and `contract.embed_dimensions` in scope one
line apart. A mismatch opens cleanly, records a valid identity, creates the
vector table at the wrong width, and then fails on every chunk part-way through
an ingest.

**`text_source` reaches the assistant but not the analyst.** The MCP surface
reports it wherever it returns corpus text, and the store holds it, but no
human-facing surface shows it. The person who decides whether a document needs
re-scanning cannot ask which documents were read by recognition without querying
SQLite directly.

## What Changes

- **An additive migration ladder.** `_SCHEMA` is frozen at the shape it had
  before `text_source` — version 4 — and never edited again. An ordered tuple of
  steps carries a store forward from there. `SCHEMA_VERSION` is derived from the
  ladder rather than written by hand.
- **`text_source` becomes the ladder's first rung**, rather than part of the
  frozen baseline. A store created fresh today therefore climbs the same rung a
  migrated store climbs, so the runner is exercised by every store the test suite
  builds and cannot rot unexercised. This is the reason to freeze at 4 and not 5.
- **A step may only add.** Add a column with a constant default, create a table,
  an index or a trigger, or drop and recreate a sidecar that is derivable from
  `chunks`. Never drop or rewrite `documents`, `casefiles` or `chunks`; never
  change a uniqueness constraint. The rule is enforced by a test that reads the
  steps, not only by a docstring.
- **A backup is taken before any step runs**, beside the store, named for the
  version being left, and never deleted.
- **The two `store_meta` guards stop sharing one refusal message.** A schema
  version that is too old, or newer than the running binary, gets its own text
  naming the versions and the remedy; today it borrows the corpus-identity
  message, whose remedy — "restore the configuration the values above name" — is
  meaningless for a schema.
- **Corpus identity escapes its separators**, per component, escaping `\`, `|`
  and control characters and deliberately **not** `=`. Every currently reachable
  identity is byte-identical before and after, so no existing store is refused.
- **The composition root compares the two widths** before the store is opened,
  and refuses with a message naming both and saying which side to change.
- **`text_source` appears on every surface that lists or shows a document** — the
  CLI, both REST endpoints, and `case_list_documents` — under the same key and
  the same vocabulary the agent already sees.

**Not breaking.** No currently reachable corpus identity changes, and the schema
ladder is what stops the schema change from breaking anything. A store recorded
before `embed_library` and `embedder` entered corpus identity is still refused —
by the identity guard, which this change does not touch.

## Capabilities

### New Capabilities

- `schema-migration`: how a store carries a corpus forward across a schema
  change — what a step may do, in what order, what is backed up, and what is
  refused rather than migrated.

### Modified Capabilities

- `storage-seam`: the recorded schema version is migrated rather than merely
  compared, and its refusal is distinct from the corpus-identity refusal.
- `layered-configuration`: corpus identity escapes its separators so that no
  component's value can be read as another component.
- `chunking-and-embedding`: the embedder's width is checked against the
  contract's before a store is opened.
- `extraction-quality-gate`: every surface that lists or shows a document
  reports how its text was obtained, not only those returning corpus text.

## Impact

- `src/jackryan/storage/sqlite.py` — the frozen baseline, the step ladder, the
  runner, the backup, and the split refusal.
- `src/jackryan/config.py` — escaping in `Contract.fingerprint` and
  `corpus_fingerprint`.
- `src/jackryan/app.py` — the width comparison, before the store is constructed.
- `src/jackryan/ingestion/quality_gate.py` — `read_as` moves here, beside the
  vocabulary it collapses to, so three adapters share one implementation rather
  than importing it from the MCP package.
- `src/jackryan/cli.py`, `src/jackryan/server.py`,
  `src/jackryan/interfaces/mcp/server.py` — the document renderers.
- **No new dependency**, and no change to what is ingested or how it is read.
