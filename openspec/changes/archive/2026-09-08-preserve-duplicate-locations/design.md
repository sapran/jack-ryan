## Context

The loss is two lines of SQL. The design question is not how to stop overwriting
— that is a deletion — but **what a document may honestly say about where it was
found**, given that every document in every existing corpus was stored before
anything recorded it.

## Decision 1: keep the first location, not the latest

Two clauses leave `DO UPDATE SET`. The choice of *which* location the document
itself reports is the load-bearing part, and first-observed wins for a reason
that has nothing to do with which is more interesting:

**A citation must not move.** `case_cite` names the containment path, and an
analyst writes that path into a report. If the document's own path tracked the
latest copy, reingesting an unrelated folder next month would silently change
what a citation written today points at. Nothing would report the move. Under
first-observed, the path is fixed at the moment the document is created and is
immutable thereafter — which is exactly the property `created_at`, already
excluded from the same `SET` list, has.

The additional locations are still fully reportable; they are simply not the one
the citation names. Choosing latest-observed would have made the accumulated set
available too, and still have left citations mutable — so it loses on the one
axis that cannot be recovered elsewhere.

## Decision 1a: a location is the ingest root plus the path within it

The obvious key is the containment path alone, and it is wrong. A containment
path is relative to whatever was ingested — `child.relative_to(path)` for a
walk, `path.name` for a named file — so `jackryan ingest case /dumps/alpha` and
`jackryan ingest case /dumps/beta`, each holding `ledger.txt` at its top level,
both produce the string `ledger.txt`. Keyed on that, the second observation
collides with the first and the second custodian is silently lost. That is the
headline case, so the root joins the primary key.

This is the first absolute host path the corpus stores. `ingest_runs` records no
target path and `IngestOutcome.path` is report-only, so the posture change is
deliberate and is noted here rather than left to be discovered: the evidence
store now carries where on the operating analyst's filesystem material was read
from, and every surface that discloses a location discloses that. It is
justified because the root *is* the discriminating evidence — which custodian's
dump a file came from — and because a location that cannot be followed by hand
fails the standard `document-hierarchy` already sets for a containment path.

**An expansion's root is inherited from its top-level file, never `work.root`.**
For a document produced by expansion `work.root` is the scratch directory its
bytes were materialised into, which is created afresh on every run. Recording it
would insert a new row on every reingest of one container, report a false
discovery each time, and grow the table without bound. Inheriting the top-level
root also makes the location genuinely followable: go to that directory, open
that archive, find that entry.

## Decision 2: four values for what a run learned, not a boolean

`INSERT OR IGNORE` returns whether the row was new, and the tempting design is to
report that directly as "new location: yes/no". It is wrong for documents that
predate the record.

Such a document has `locations_recorded = 0` and no rows. Reingesting it from the
very path it was originally ingested from inserts a row, and the store truthfully
reports it as new — but calling that a *discovery* asserts that this path was not
among the ones previously observed, which is precisely what was overwritten and
cannot be known. So the verdict is decided in the service, where `existing` is
already in hand:

```
existing is None                    → first     (a new document)
not existing.locations_recorded     → unknown   (predates the record; unanswerable)
the store inserted a row            → new       (a genuine discovery)
otherwise                           → known     (an ordinary reingest)
```

The ordering matters: `unknown` is tested **before** the store's answer, so a
migrated document can never produce a `new` it cannot support. This is the same
shape as `CasefileService.coverage`'s three-state verdict, and `unknown` means
the same thing there — *the record cannot answer*, which is weaker than *there is
a gap* and stronger than silence.

## Decision 3: `locations_recorded` is written on insert and never on conflict

The flag is the whole basis of the `unknown` verdict, so it must be impossible
for a reingest to launder a migrated document into a complete one. Two mechanisms
hold it:

- The new column defaults to `0`, so every pre-existing row is `unknown` without
  a migration writing anything.
- `locations_recorded` appears in the upsert's insert list and is **absent from
  `DO UPDATE SET`**, so only an insert by the new code can set it to 1.

A document migrated from an older schema therefore keeps saying it predates the
record however many times it is reingested — which is correct, because the copies
it lost are still lost.

## Decision 4: a flag, not a timestamp

A `locations_recorded_since` timestamp was considered and rejected. It would
duplicate `min(first_seen_at)` from `document_locations`, and two copies of one
fact that can disagree is the defect class this repository argues against
throughout — the same argument `layered-configuration/spec.md:35-36` makes for
composing the embedder into corpus identity rather than duplicating it into the
contract. The flag answers the only question asked of it: may this record be read
as whole.

## Decision 5: record locations for expansions too, uniformly

An expansion's `identity_path` is part of its identity, so identical bytes on two
messages are two documents and each will ever have exactly one location. Writing
a row for it is therefore redundant.

It is done anyway, because the alternative is worse. If only directly ingested
documents had rows, then `document_locations` would answer "no locations
recorded" for an expansion, and every surface would have to branch on how the
document came to exist before it could interpret the answer. Uniformity costs
roughly 80 bytes per document — under 0.1% of a 435 MB store — and buys one
answer shape. `location_count` also stops needing a second derivation for the
expanded case, which the contingency in the plan spells out as the trap.

## Decision 6: bounded at 20, with no continuation

Every other bounded thing on the MCP surface carries a position to continue from,
and `mcp-tool-surface` makes a point of there being one continuation contract
rather than two. Locations are the deliberate exception, and the delta says so
explicitly rather than leaving it as an omission.

The reason is that the count is the answer. A document observed in 200 places is
characterised by *200*, which the payload carries; its 21st path adds nothing an
analyst would act on. A continuation would teach an agent to page toward
information it already has, and paging is the expensive habit on a surface whose
bounds exist to stop exactly that. Twenty paths at the 200-character ceiling is
at most 4,000 characters beside a 20,000-character read.

If review disagrees, the contingency is written down: add `offset` to the service
method and `continue_from` to the payloads in `list_document_page`'s vocabulary,
and amend the delta to *require* it rather than forbid it. What must not ship is a
`continue_from` no caller can pass.

## Decision 7: the ordering is total

`document_locations` orders by `first_seen_at, containment_path`. The timestamp
alone is not total: two locations recorded inside one ingest run share `now`, and
a bound falling inside that tie would return a different subset between two calls
on an unchanged corpus. That is the same failure `mcp-tool-surface` legislates
against for paged listings, and the same one that cost 0.058 recall@1 when
retrieval ties were broken by an identifier.

The path is the tiebreaker rather than the row id, because the path is a property
of the corpus and a row id is minted afresh by a reingest.

## Decision 8: `new_locations` is a finding, not a limitation

`IngestReport.limitations` derives `complete`. A copy found at a new location was
read and stored — the run covered everything it was offered — so putting it in
`limitations` would flip `complete` to false and report a discovery as a
shortfall. It is a separate derived property, rendered by the CLI under its own
sentence, below the limitations block and phrased as something learned rather
than something missed.
