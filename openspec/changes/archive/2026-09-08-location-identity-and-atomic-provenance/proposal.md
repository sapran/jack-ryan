## Why

Task 5 shipped the location record and PM verification found two ways it lies.
Both were reproduced before this proposal was written, against `85c24a4`.

**An interrupted first ingest lets a later root claim the whole history.**
`documents.locations_recorded` is written by the document's own insert;
`document_locations` is written by a second call afterwards. Kill the process
between them and the document survives asserting a whole record with no rows.
That state alone reads `unknown`, which is correct and is what the existing
zero-row guard gives. The hole is the *retry*: ingest identical bytes from a
second root and the store now holds one row, the flag is still true, and the
verdict flips to `complete` — naming root B as the whole story while root A,
where the document actually came from, was never recorded and never will be.

```
root A ingest interrupted   -> flag=True rows=0  verdict='unknown'   (correct)
root B ingested             -> flag=True rows=1  verdict='complete'  (false)
                               observed at: <root-b>/ledger.txt
                               root A present: False
```

**One physical file is recorded as several locations.** The published identity
is the ingest root paired with the path within it. The same file reached through
two different roots therefore yields two pairs denoting one place: ingest a
folder and then its nested file directly and the store holds
`(dump, sub/note.txt)` and `(dump/sub, note.txt)`, the run reports a
**discovery**, and the surfaces show the identical rendered path twice with
`total = 2`.

```
1. ingest the folder                 -> location 'first'
2. ingest the nested file directly   -> location 'new'   <- nothing was discovered
3. ingest the containing subfolder   -> location 'known'
   2 locations recorded, 1 distinct rendered path
```

The second is a contract inconsistency rather than an implementation slip: the
identity rule permits it while the scenario *A same-location reingest records no
new location* promises it cannot happen. One of the two has to change, and it is
the identity rule — a count an analyst reads as "this file was in two places" is
a false finding, which on this surface is worse than an absent one.

## What Changes

**Current behaviour.** A location is `(source_root, containment_path)`, so one
place reached two ways is two locations and a reingest through a different root
announces a discovery. Whether the record is whole is a stored flag, written
before the row that would justify it, so a crash makes the two disagree and a
later observation launders the disagreement into `complete`.

**Desired behaviour.**

- **A location is one path.** Schema rung 10 adds `document_observations`, keyed
  `(document_id, location_path)`. The same file reached through any root is one
  observation, so step 2 above records nothing and reports `known`. Two dumps
  each holding `ledger.txt` at their top level remain two locations, because
  their paths differ — which is what the root was added for and is preserved.
- **A document and its observation are one write.** `store_document`
  replaces `upsert_document` and takes the observation as a required parameter,
  writing both in one transaction. `upsert_document` is removed rather than
  deprecated, so the ordering hazard cannot be reintroduced by a caller.
- **Whether the record is whole is derived, never stored.** It is whole exactly
  when recording began no later than the document was created — `min(first_seen_at)
  <= created_at`. That is the definition of the claim rather than a proxy for it,
  and being derived it cannot disagree with the rows. A document whose recording
  began later reads `unknown` and keeps reading `unknown` however many
  observations follow, which closes the retry transition.
- **`documents.locations_recorded` is retired.** It is the stored copy that was
  proved able to disagree, and the ladder is additive so the column stays,
  unwritten and unread, with the rung comment saying why.
- **Existing records are carried forward, not rewritten.** Rung 10 copies
  `document_locations` into the new table, joining each pair into a path and
  collapsing observations that denote the same place to their earliest
  timestamp. `document_locations` is left exactly as it is: it is the prior
  record of how each place was reached, and deleting it to tidy up would destroy
  provenance to fix a representation.

**Deliberately not in scope.** Each is recorded in
`docs/implementation-notes.md` and none is touched here: the failed-backup
residue accepted on migration retry (a pre-existing migration-safety defect),
the missing location count on `case_mention_documents` (a surface-consistency
gap outside the listing scope task 5 declared), the two cleanup tests that glob
the process-global temporary directory, and the stale partial-list description in
`tests/test_document_locations.py` — the last of which this change makes moot
and therefore corrects in passing, because the file it sits in is rewritten here
anyway.

## Impact

**Specs: three `MODIFIED` requirements and one `ADDED`.** Scoped by
falsification against every published requirement, re-read this session.

| Published text | Verdict |
|---|---|
| `document-ingestion:168-175` — a location is "the root that was ingested together with the path within it, and the two together SHALL be what makes one location distinct" | **MODIFIED** — this is the sentence that permits one place to be two locations |
| `document-ingestion:193-197` — a document stored before locations were recorded reports unable to answer | **MODIFIED** — widened from "stored before the record existed" to "recording began after the document was created", which is the same rule and also covers the interrupted write |
| `document-hierarchy:62-65` — each additional location carries "the root it was ingested from as well as the path within it" | **MODIFIED** — a location is now one followable path, and a count is of places rather than observations |
| `untrusted-content-boundary:50-57` — "A location is the ingested root joined to the path within it" | **MODIFIED** — same rewording; the sanitisation rule it exists for is unchanged and still covers the whole path |
| `storage-seam` — "Everything derived from a chunk is written in the chunk's own transaction" | **not falsified**, and the precedent this change follows. Its scope is data derived from a chunk; an observation is not. A sibling requirement is **ADDED** for the document's own write, quoting the same reason about a seam usable in the wrong order |
| `mcp-tool-surface:146-152` — a document's locations are a bounded disclosure with no continuation | **not falsified**: the bound, the count and the absence of a continuation are unchanged. The count now counts places, which is what the payload always claimed to carry |
| `schema-migration:29-34` — every step additive, no uniqueness constraint changed | **satisfied**: rung 10 creates a table and copies into it. No existing constraint is altered — the new key is on a new table — and nothing is dropped or deleted |
| `ingestion-coverage:22-24` — the closed enumeration of coverage reasons | **not falsified**: no reason is added. A location that turns out to be one already known is not a shortfall, and `complete` is untouched |
| `document-ingestion:127-128` — a content-routed file keeps the filename it carries on disk | **not falsified**: unchanged by this change |

- **Code:** `src/jackryan/storage/migrations.py`, `src/jackryan/storage/port.py`,
  `src/jackryan/storage/sqlite.py`, `src/jackryan/services/ingestion.py`,
  `src/jackryan/cli.py`, `src/jackryan/server.py`,
  `src/jackryan/interfaces/mcp/server.py`.
  `rendering.py` and `interfaces/mcp/fencing.py` are **not** edited: the payload
  keys and the provenance block keep their shape, because what changed is which
  rows exist, not how they are disclosed.
- **Tests:** `tests/test_document_locations.py` extended and its stale
  description corrected; `tests/test_store.py`, `tests/test_mcp_fencing.py` and
  `tests/test_text_source.py` updated for the retired `upsert_document`;
  `tests/test_migrations.py` gains the carry-forward of an existing record.
- **Store:** every existing store pays one full-file backup on first open, which
  `schema-migration:77-78` requires. No repair or reingest of any existing
  corpus is authorised by this change, and none is needed: rung 10 carries the
  records forward.
- **Docs:** the two resolved entries in `docs/implementation-notes.md` are
  marked fixed; `docs/functional-review-todo.md` records this change's evidence
  and leaves task 5 awaiting independent PM acceptance.
