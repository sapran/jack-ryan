## Context

See `proposal.md` — Why. The migration mechanism was chosen by putting three
approaches against each other and scoring them on two axes: correctness and risk,
and fit and proportion. Both judges ranked the same option first. What follows is
that option plus the grafts the losing designs earned.

Three facts about the current store shape the whole design.

**Editing `_SCHEMA` does not alter an existing store.** Every table is
`CREATE TABLE IF NOT EXISTS`, so adding a column to the script adds it for new
stores and silently does not for old ones. That asymmetry is invisible in the
diff, and it is why the baseline must be frozen rather than merely conventionally
left alone.

**`_verify_meta` is records-or-refuses and nothing more.** Two keys go through
it, `schema_version` and `contract_fingerprint`, and it treats them identically.
They are not alike: one describes how evidence is stored, the other what the
stored vectors mean.

**Corpus identity is a plain string nothing parses.** It is compared as a whole,
displayed in two places, and quoted in the refusal. No consumer would break on a
format change — but every recorded value would stop matching, which is a worse
kind of break, and one no test would catch on a fresh checkout.

## Goals / Non-Goals

**Goals:**

- A store recorded under an older schema opens, rather than requiring an operator
  to throw away a corpus over a column.
- The migration path is exercised by ordinary work, not only by a fixture.
- No currently reachable corpus identity changes value.
- Two mistakes that today surface late — a mis-sized embedder, and a schema
  refusal wearing the wrong remedy — surface at the point they are made.

**Non-Goals:**

- A general migration framework. Steps are a tuple, not a plugin system.
- Reversibility. There is no down-migration; the backup is the way back.
- Migrating corpus identity. It is compared, never carried forward — that is the
  distinction the whole change rests on.
- Recording where a casefile was ingested from, or deriving document identifiers
  so that a reingest reproduces them. Both were proposed and both are real, and
  both change what identity means, which is a separate change with its own delta
  spec.

## Decisions

### An additive ladder, over rebuilding derived data or a reingest policy

Three approaches were designed and judged.

*Rebuild the derived half* exploits a genuine property: chunks, the full-text
index and the vectors are all derived from `documents.extracted_text`. A
migration could keep the source-of-truth tables and rebuild everything below
them. Rejected as the primary mechanism because rebuilding means re-embedding,
which is the most expensive thing this system does, and paying it for a column
addition is disproportionate. It is kept as a tool a future step may reach for.

*Reingest is the migration path* argues for a policy rather than a mechanism, and
it was the honest challenger: it costs nothing to build and cannot itself
corrupt anything. Rejected on what it assumes. Reingest requires the operator to
still hold the originals — and, as recorded in `docs/implementation-notes.md`,
this workbench does not archive them despite `docs/design.md` § 5 saying it does.
A policy whose remedy depends on a guarantee the code does not make is not a
policy.

*The additive ladder* won both judges. An ordered tuple of steps, each adding
and never removing, applied in order to carry a store forward.

### Freeze at 4, not 5, so the first rung is climbed by every store

The baseline is restored to the shape it had before `text_source`, and
`text_source` becomes the ladder's first step.

*Why:* a migration runner that only executes against a hand-built fixture is
exercised by nothing an operator ever does. It is written once, and next touched
on the day it is first genuinely needed — which is the day it matters most and
the worst day to discover it rotted. Freezing one version back makes every fresh
store the test suite creates climb the same rung a migrated store climbs, so the
runner is covered by the whole suite rather than by one test.

*Cost:* the schema a reader sees in `_SCHEMA` is no longer the schema the code
produces. That is a real readability loss, paid for with a comment at the
freeze and with the parity test below.

### `SCHEMA_VERSION` is derived from the ladder

Written by hand, the version and the steps can disagree — and the failure of that
disagreement is a store stamped as migrated that is not. Deriving it makes the
two unable to differ.

### A step may only add, and that is checked rather than trusted

Add a column with a constant default; create a table, index or trigger; drop and
recreate a sidecar wholly derivable from `chunks`. Never touch `documents`,
`casefiles` or `chunks` destructively; never change a uniqueness constraint.

*Why checked:* this project's own history is that a rule stated only in a comment
is a rule a later change breaks without noticing. Two tests make it mechanical:
one reads the steps and rejects destructive statements; one compares the schema
of a fresh store against one walked up the ladder and requires them identical.

*Never make a step idempotent by catching "duplicate column".* That converts a
version row that lies into a silent success, which is the failure the version row
exists to prevent.

### Migrate first, compare identity second

The schema ladder runs before corpus identity is compared.

*Why:* a store that is migrated and then refused on identity is left improved and
undamaged, since every step is additive. The reverse order would refuse a store
the running code could have read. There is also a forward reason: renaming the
`store_meta` key from `contract_fingerprint` to `corpus_identity` — the parked
naming-drift item — is itself a future rung, and an identity check ahead of the
ladder would read a key the ladder is meant to rename.

### A backup, taken as a store rather than as a file

Before any step runs, the store is copied beside itself as
`<db>.v<recorded>.bak`, using SQLite's own backup API rather than a file copy, so
the copy is consistent rather than a snapshot of a file mid-write. It is never
deleted, and failure to write it refuses the migration.

*Why this is not over-cautious:* a migration is the only operation in this system
that rewrites a corpus in place, and the evidence in it is not reconstructible
from anywhere else once the originals have left the analyst's hands — which, per
the finding above, this workbench does not prevent.

*Consequence for the transaction:* `Connection.backup()` cannot run inside a
write transaction. So the version is read once without a lock, the backup is
taken, and the version is then **re-read inside** the write transaction that
applies the steps. The unlocked first read is not an optimisation; the re-read is
what makes it correct.

### The FTS trigger travels with the FTS columns

`chunks_after_delete` supplies only `text` to the FTS5 `'delete'` command. With
today's single-column `chunks_fts` that is correct. With a second column it is
not: the deleted row's tokens for that column stay in the index, `MATCH` keeps
returning it, and a strict `integrity-check` reports the database malformed. It
would fire on every ordinary reingest, because rebuilding a document's chunks
begins by deleting them.

This was reproduced rather than reasoned about. A summaries column is on the M3
roadmap, so this is a trap set for the next schema change. The rule is therefore:
a step that changes the FTS column list drops and recreates the trigger in the
same transaction — with a test asserting the trigger's column list equals the
table's, so the two cannot drift.

### Escape, do not hash

Corpus identity escapes `\`, `|` and control characters within each component,
and deliberately does **not** escape `=`.

*Why not hash:* `openspec/specs/storage-seam` requires the refusal to name both
values and say how to proceed, on the stated grounds that two long strings
differing in one component already tell an operator too little. Two hex digests
tell them nothing, and would empty the identity field that `/health` and
`jackryan status` publish precisely so an operator can see what refused them.
Keeping a hash for comparison and plain text for display is two representations
of one setting that can disagree — the bug shape the embedder-identity change
closed.

*Why not `=`:* `embed_library` legitimately contains `==`. Since the component
keys are fixed identifiers containing no `=`, splitting on unescaped `|` and then
on the first `=` still round-trips unambiguously. Leaving `=` alone is also what
keeps every existing identity byte-identical, because no current value contains
`|` or `\`.

*What is actually fixed:* not a constructible two-corpora collision — that needs
two free-text components and only `embed_model` is free. What is fixed is a
deceptive identity, where a crafted `embed_model` makes the reported value name
an embedder the instance is not using. The collision becomes reachable the day a
third embedder exists, since `EmbedderPort.name` is an unvalidated `str`.

### The width check goes before the store, not after

In `build_context`, immediately after the embedder is constructed and before
`SqliteStore` is. Placed after `initialize`, it would be too late in the case
that matters: on a fresh corpus the vector table has already been created at the
contract's width and a valid identity recorded, leaving a wrongly sized store on
disk. The test asserts no database file exists after the refusal — a fresh data
directory with nothing in it is the proof that the check ran ahead of the store.

It compares *declared* widths only. `ModelEmbedder` already raises if the loaded
model disagrees with what it was told; this guard becomes load-bearing the day an
embedder learns its width from the model rather than from the contract.

### `read_as` moves below the adapters

It currently lives in `interfaces/mcp/fencing.py`. Three adapters now need it,
and a CLI importing from the MCP package to render a column would be the wrong
direction. It moves beside `TEXT_SOURCES` in `ingestion/quality_gate.py`, which
is where the vocabulary it collapses to already lives, and `fencing.py`
re-exports it so the MCP surface is unchanged.

## Risks / Trade-offs

**The frozen baseline no longer describes the schema the code produces.** → A
comment at the freeze says so, and the parity test fails if the ladder and the
baseline ever diverge.

**A migration could be interrupted.** → Every step runs inside one transaction
with one commit, so an interrupted migration rolls back to the recorded version;
and the backup exists regardless.

**The backup will surprise someone with disk usage.** → Accepted, and named in
the refusal path and the handover. Silently deleting the one copy of a corpus's
previous state to save space is the wrong trade for evidence.

**Escaping is invisible until it matters.** A reader may not see why the join is
not a plain join. → The test that a crafted `embed_model` cannot impersonate an
embedder clause is the executable explanation.

## Migration Plan

The first migration is `v4 → v5`, one statement, adding `text_source` with a
constant default and no backfill: a document ingested before the column has no
honest value, and `read_as` already collapses anything outside the known
vocabulary to `unrecorded`, so such a document discloses itself correctly with no
new code.

The red test comes first, because nothing covers `schema_version` today: build a
populated store at the frozen v4 shape, open it with the current binary, and
watch it raise the existing "only appendable" refusal. Then make it migrate, and
assert the pre-existing documents still read and report `unrecorded`.

## Open Questions

None that change the specs, the approach or the tasks. Two findings surfaced by
the design work are recorded in `docs/implementation-notes.md` rather than
resolved here: that originals are never archived despite `docs/design.md` § 5
saying they are, which changes what "reingest" costs everywhere that word is
written; and that recording an ingest root and deriving document identifiers
would make a reingest reproduce the same identifiers, which is the natural next
change and alters what identity means.
