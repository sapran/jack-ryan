## Why

When the same file is ingested from two different folders, this tool destroys the
evidence that it was found in both.

Content deduplication is correct and is not in question: identity for a directly
ingested file is the hash of its bytes, `identity_path` is empty, and two copies
resolve to one document exactly as `document-ingestion/spec.md:140` requires.
The defect is what the second copy does to the first. `upsert_document`'s
`ON CONFLICT … DO UPDATE SET` overwrites `filename` and `containment_path` from
`excluded` (`storage/sqlite.py:300-351`), so the later copy's location silently
replaces the earlier one and the earlier one is unrecoverable — not moved, not
marked superseded, gone.

**In a forensics tool the set of places a file was found is itself evidence.**
One ledger in `custodian-a/` and the identical ledger in `custodian-b/` is shared
custody; the same attachment across a dump is distribution. That is frequently
the finding, and today the corpus keeps whichever copy the walk happened to reach
last. Two things make it worse than an ordinary lost field:

| | |
|---|---|
| **It is invisible.** | Nothing reports a conflict. The document looks complete, its one path resolves, and an analyst has no way to suspect a second location ever existed. |
| **It moves a citation.** | `case_cite` names the containment path. Reingesting a folder can change what a citation written yesterday points at, with no record that it moved. |

**This is not deferred work pulled forward.** `docs/design.md:110` makes the
prototype loop *"ingest documents → the AI works the corpus over MCP and answers
with resolvable citations"*, and a citation whose path is rewritten by an
unrelated later run does not resolve in the sense that matters. `docs/design.md`
§5 defers the per-document failure and retry ledger and the store-versus-disk
doctor to M4; this is neither. It records an observation made at ingest time and
discloses it. It adds no retry, reconciles nothing against the filesystem, and
repairs no existing corpus.

## What Changes

**Current behaviour.** Identical bytes from two folders resolve to one document,
whose `filename` and `containment_path` are those of whichever copy was ingested
most recently. The earlier location is discarded. No surface reports that more
than one location was ever seen, and no ingest result distinguishes a newly
discovered copy from an ordinary reingest.

**Desired behaviour.**

- **Nothing about deduplication changes.** Two copies remain one document. The
  existing guard for that, `test_containers.py:238`, is untouched.
- **The first observed location wins, permanently.** `filename` and
  `containment_path` leave the upsert's `DO UPDATE SET`, joining `created_at`,
  which is already excluded for the same reason. A citation stops being able to
  move.
- **Schema step 9, `document_locations`**: one row per document per observed
  location, keyed on `(document_id, source_root, containment_path)`, carrying
  when it was first seen and cascading with its document. Plus
  `documents.locations_recorded`, an integer flag defaulting to 0.
- **A location is the ingest root joined to the path within it**, and this is
  the one place the plan was wrong. A containment path is relative to whatever
  was ingested, so two dumps each holding `ledger.txt` at their top level
  produce the same string; keyed on that alone the second custodian's copy
  collides with the first and is lost, which is the very case being fixed. The
  root is therefore part of the key — making this **the first absolute host path
  the corpus stores**, a deliberate posture change noted in `design.md`. For a
  document produced by expansion the root is inherited from its top-level file,
  never the scratch directory its bytes were materialised into, which is new on
  every run and would report a false discovery on every container reingest.
- **No backfill, deliberately.** An existing document gets no location row. The
  only timestamp available is `created_at`, which is when the document was first
  ingested and not when any particular copy was observed. Inventing it would
  fabricate exactly the evidence this change exists to preserve.
- **`StorePort.record_document_location` and `.document_locations`**: one write
  whose return value says whether the location was new, one bounded read, both in
  domain objects.
- **A four-value ingest outcome** — `first` / `known` / `new` / `unknown` — because
  "this location was not previously recorded" and "we cannot say whether it was"
  are different claims and only one of them is a discovery.
- **`IngestReport.new_locations`**, derived like `limitations` and deliberately
  **not** part of it: a copy found in a second place *was* ingested, so the run
  covered everything it was offered. Folding it into `limitations` would report a
  discovery as a shortfall and flip `complete` to false.
- **A three-field service record** (`DocumentLocationRecord`) carrying the store's
  facts, this layer's verdict, and the document — modelled on `CasefileCoverage`.
  The `unknown` caveat is written once, on the record, so two surfaces cannot
  word it differently.
- **The disclosure reaches every surface**: CLI `document show` and its `--json`
  form, the REST detail route, `case_read_document`'s provenance block, and a
  `locations` marking on both listings — the `child_count` precedent exactly.
- **Bounded at 20 with no continuation.** A document found in more than twenty
  places is characterised by the count, which the payload carries.

**Deliberately not in scope.**

- **`case_search`, `case_cite` and `case_get_passage` are unchanged.** A search
  response is bounded across the whole response, so a per-result location list is
  precisely the payload that bound exists to prevent. And a citation must name one
  path a person can follow by hand — which is now the stable first-observed one,
  a strict improvement — where a list inside a citation string cannot be followed
  at all.
- **No repair command and no reingest of any existing corpus.** A document that
  predates the record reports `unknown` for as long as it is never reingested, and
  that is the honest answer. `jackryan repair mention-offsets` exists because
  offsets are recomputable from stored text; an overwritten path is not
  recoverable from anything.
- **`serialize_document` and `rendering.render_document` are untouched.** Both are
  shared by a listing and a detail view, and both argue in place against being
  widened. The location fields are added by each surface, exactly as `found_at`
  and `children` already are.
- **No new REST route.** The disclosure belongs on the document a caller already
  asked for.

## Impact

**Specs: four `MODIFIED` requirements across four capabilities, no new
capability, and no `ADDED` block.** Scoped by falsification against every
published requirement rather than by topic, re-read this session:

| Published text | Verdict |
|---|---|
| `document-ingestion/spec.md:140` — a document's identity is its content | **MODIFIED** — dedup unchanged; the location record, the first-observed rule and the four-value outcome are added |
| `document-hierarchy/spec.md:48` — a document reports the path it was found at | **MODIFIED** — "the path is its own name" stays true and stays verbatim; it is now explicitly the *first* observed name |
| `document-hierarchy/spec.md:68` — listing marks a container without listing it | **MODIFIED** — the same affordance for a document observed in several places |
| `untrusted-content-boundary/spec.md:12` — corpus text is fenced and attributed | **MODIFIED** — additional paths are sanitised on identical terms; there is no weaker class of path |
| `mcp-tool-surface/spec.md:104` — reads are bounded, truncation explicit | **MODIFIED** — locations are a bounded disclosure and the one deliberate exception to the continuation contract |
| `document-ingestion/spec.md:127-128` — a content-routed file "keeps the filename it carries on disk" | **not falsified**, and the near miss of this change. It constrains which name a stored document takes from the file it was read from, not which of two observations of the same bytes wins. The stored name is still one the file carries on disk — the one at the location observed first |
| `ingestion-coverage/spec.md:22-24` — the closed enumeration of coverage reasons | **not falsified**: no reason is added. A newly recorded location is not a shortfall, which is why `new_locations` is derived separately from `limitations` |
| `ingestion-coverage/spec.md:41` — "A run that read everything offered reports itself complete" | **stays true**: no reason is added, so nothing flips `complete`. Asserted directly, in test 5 |
| `ingestion-coverage/spec.md:79` — "Both human surfaces return the same ingest result" | **stays true**: `location` is added to the shared `render_report`, so neither surface can drift from the other |
| `schema-migration/spec.md:29-34` — every step additive | **satisfied**: a `CREATE TABLE` and a column with a constant default, both named as permitted. No evidence table rewritten, and the `documents` uniqueness constraint untouched |
| `storage-seam/spec.md:190-192` — derived text is overwritten on reingest, never preserved | **not falsified**: that rule governs text *derived* from a document — a chunk or document summary — which must describe what sits beside it now. A source location is an observation of where the evidence was found, not text derived from it, and its whole value is that it accumulates |
| `storage-seam/spec.md:11` and its scenario at `:42` — the port speaks in domain objects | **satisfied**: `DocumentLocation` and `DocumentLocationSet` are frozen dataclasses with named fields, not mappings |
| `hybrid-search/spec.md` | **not falsified**: search results are deliberately unchanged, per the scope note above |

Because real deltas exist, the `.openspec.yaml` `skip_specs: true` escape is
**not** used.

- **Code:** `src/jackryan/storage/migrations.py`, `src/jackryan/storage/port.py`,
  `src/jackryan/storage/sqlite.py`, `src/jackryan/services/ingestion.py`,
  `src/jackryan/rendering.py`, `src/jackryan/cli.py`, `src/jackryan/server.py`,
  `src/jackryan/interfaces/mcp/fencing.py`,
  `src/jackryan/interfaces/mcp/server.py`.
- **Tests:** fourteen added — thirteen in a new
  `tests/test_document_locations.py`, one in `tests/test_migrations.py` for a
  document carried forward from a v4 baseline. `BASELINE_DOCUMENT_COLUMNS` and
  `test_the_frozen_baseline_is_frozen` are not touched. One existing test was
  re-anchored rather than relaxed: `test_an_older_store_gains_the_ingest_run_record`
  derived its store's version from the top of the ladder, so any new rung made
  it build a store already stamped at the `ingest_runs` version and skip the
  step it exists to exercise. It now keys on the step that creates the table.
  Every new guard is shown red against the defect it exists for.
- **Store:** every existing store pays one full-file backup on first open, which
  `schema-migration/spec.md:77-78` requires before any step runs. No repair or
  reingest of any existing corpus is authorised by this change.
- **Docs:** `docs/functional-review-todo.md` item 5 is ticked with its evidence.
