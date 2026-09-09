## Context

Both defects come from the same habit: storing a fact that the rows already
determine, and writing it before the rows exist. The pair-identity stores *how*
a place was reached alongside *where* it is, and then treats the pair as the
place. The completeness flag stores a claim about the rows, in a different
transaction from the rows. This design removes both stored copies.

## Decision 1: a location is a path, not a root and a path

`(source_root, containment_path)` was chosen so that two dumps each holding
`ledger.txt` at their top level stayed two locations. That goal is right and is
kept — but the pair over-discriminates. It distinguishes observations, and an
observation is not a place:

```
ingest /dump                    -> ("/dump",     "sub/note.txt")
ingest /dump/sub/note.txt       -> ("/dump/sub", "note.txt")
```

Two rows, one file. Keying on the joined path collapses them and still separates
`/dumps/alpha/ledger.txt` from `/dumps/beta/ledger.txt`, because those paths
differ. The joined path is also the only form any surface ever showed, so this
is the representation catching up with the disclosure.

**What is lost:** which root an observation was reached through. That is a fact
about the operator's command, not about where the evidence sits, and no surface
reported it. The old rows keep it — see Decision 4.

## Decision 2: whether the record is whole is derived from when it began

The claim "every place these bytes were observed is recorded" is true exactly
when the record has existed since the document was created. That is directly
checkable:

```
whole  <=>  the record holds an observation
            AND min(first_seen_at) <= created_at
```

`created_at` is preserved across reingest, so it remains the document's true
creation. Every case falls out without a stored flag:

| state | earliest observation | verdict |
|---|---|---|
| created now, observed now | `= created_at` | whole |
| reingested from a second root | still the first, `= created_at` | whole |
| predates the record | later than `created_at` | unknown |
| **first write interrupted, retried from another root** | later than `created_at` | **unknown** |
| observations deleted out of band | none | unknown |

The fourth row is the PM's blocker, and it closes because the derivation asks a
question the corrupted state cannot answer falsely. A stored flag could only be
patched — by demoting it when found empty — which leaves the stored copy in
place and depends on noticing.

**This is the argument the change it supersedes made against itself.** Task 5's
own design Decision 4 rejected a `locations_recorded_since` timestamp because it
"would duplicate `min(first_seen_at)` … and two copies of one fact that can
disagree is the defect class this repository argues against throughout" — and
then kept a boolean doing exactly that. The PM found the disagreement.

**Timestamp equality is load-bearing and is pinned.** A new document's
`created_at` and its first observation's `first_seen_at` are the same `now`,
written in one transaction, so `<=` holds by equality. A future refactor calling
`_now()` twice would make every new document read `unknown` — a safe direction,
but wrong — so a test asserts the two are equal rather than merely ordered.

## Decision 3: one call stores a document and its observation

`upsert_document` is removed and `store_document` takes the observation as a
required parameter. Both writes share one transaction and one lock, so the
interrupted state is unreachable going forward rather than merely detectable.

An optional parameter was rejected for the reason `storage-seam` already gives
about a separate method: a seam that can be used in the wrong order eventually
is, and an optional one is used wrongly without eventually. Three tests
construct documents through this seam and now supply a location, which makes
their fixtures match what an ingest actually produces.

Note the two fixes are independent and both are wanted. Atomicity prevents the
state; the derivation tells the truth about stores that are already in it,
including the one the PM built. Shipping only atomicity would leave every
already-crashed store able to claim `complete` after one reingest.

## Decision 4: the old table is carried forward and kept

Rung 10 copies `document_locations` into `document_observations`, joining each
pair and collapsing duplicates to the earliest timestamp:

```sql
INSERT OR IGNORE INTO document_observations (document_id, location_path, first_seen_at)
SELECT document_id, source_root || '/' || containment_path, MIN(first_seen_at)
  FROM document_locations
 GROUP BY document_id, source_root || '/' || containment_path
```

The `GROUP BY` is what repairs an existing store's duplicate places, so no
repair command is needed and no reingest is authorised.

`document_locations` is left untouched and unwritten. Deleting it would be
tidier and would destroy the only record of which root each place was reached
through — provenance, discarded to improve a representation. The rung comment
says it is retained deliberately so that a later reader does not clean it up.

**The join uses SQL concatenation, which agrees with `PurePosixPath` for every
path this tool records** — a resolved absolute directory never ends in a
separator — with one exception: a file ingested from the filesystem root would
yield `//note.txt` here and `/note.txt` in Python. Ingesting `/` is not a case
worth code, but it is worth writing down rather than discovering.

## Decision 5: the listing marking derives from the same rule

A listing marks a document found in more than one place. Under the retired flag
the threshold was `> 1` for a document with its own row and `> 0` for one
without. Both are the same statement about additional places, so the query
aliases `MIN(first_seen_at)` beside the existing count and the threshold becomes
one expression on the domain object:

```
additional = location_count - (1 if the record is whole else 0)
```

One derivation, used by the verdict and by both listing surfaces, so an adapter
no longer carries a rule of its own — which is what the reviewer objected to in
the previous change for a different value.
