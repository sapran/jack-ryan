## Why

An assistant working this corpus cannot tell an empty search result from missing
evidence. That is the one wrong answer this tool must not give, and the surface
currently gives it no way to avoid.

`openspec/specs/analyst-pack/spec.md` already obliges the assistant to qualify
every coverage claim and forbids reporting absence of evidence as evidence of
absence. **The surface gives it nothing to qualify with.** `case_casefile_overview`
returns counts and no statement about how completely the casefile was filled, so
an agent asked "does this casefile mention Northgate?" has only two honest moves:
answer from the counts as though they were complete, or refuse. It takes the
first.

The service layer is closer than the surfaces are, but not close enough:

| Already there | Not there |
|---|---|
| `IngestReport.refusals`, `.exhausted_by`, `.complete` (`services/ingestion.py:48-75`) | no adapter renders any of the three |
| `Extraction.refusals`, set for traversal, symlinks and non-regular files (`ingestion/containers.py:180,183,278,887,891`) | **never read by the service** — `grep '\.refusals'` under `services/` finds only `IngestReport`'s own field |
| `metadata={"entries": …}`, published by all three container extractors (`containers.py:194,301,901`) | nothing reconciles it against what the reader delivered |
| a folder-walk file no extractor accepts | passed over in silence (`services/ingestion.py:217-227`) |
| nothing at all | no record of any run survives it |

And `complete` was weaker than its name: it meant *"expansion was not cut
short"*, so a run in which three of five documents failed reported itself
**complete**. `failed` being counted separately does not help a caller who read
`complete` and stopped reading.

**This is not deferred work pulled forward.** `docs/design.md:110` makes the
prototype loop *"ingest documents → the AI works the corpus over MCP and answers
with resolvable citations"*, and an answer whose coverage cannot be stated does
not close that loop. `docs/design.md` §5 defers a per-document *failure and retry
ledger* to M4, and the store-versus-disk *doctor* with it; neither is this. This
change records what a run reported about itself and discloses it. It does not
make a failure retryable, does not reconcile the store against the filesystem,
and adds no per-document record beyond the `text_source` disclosure that already
ships.

## What Changes

**Current behaviour.** An ingest run computes three coverage facts, shows none of
them, drops the extractors' own refusals on the floor, silently omits both
unroutable folder files and container entries its reader never delivered, records
nothing, and reports itself `complete` whenever no bound was hit.

**Desired behaviour.**

- **One definition of incompleteness.** `IngestReport.limitations` derives the
  reasons; `complete` derives from `limitations`. The verdict and its reasons can
  no longer disagree, and a failed document now makes a run incomplete.
- **A new `skipped` list** for files a folder walk offered that no extractor
  accepts — counted apart from `refusals` because the two want different words,
  but no longer silent.
- **The extractors' refusals reach the report**, prefixed with the container's
  own path so a refusal reads as the chain a person would follow.
- **Listed entries are reconciled against delivered ones**, against the count the
  extractor already publishes rather than by re-deciding the per-entry ceiling —
  and not reported at all where a bound or a raised expansion already said so.
- **Schema step 8, `ingest_runs`**: one row per completed run, carrying
  `documents_before` — how many documents the casefile already held when the run
  began. No row is backfilled, which is the point.
- **`StorePort.record_ingest_run` and `.ingestion_coverage`**: one write, one
  aggregate read, both in domain objects.
- **`CasefileService.coverage`** returns a three-state verdict —
  `complete` / `incomplete` / `unknown`. A casefile with no record, or holding
  documents that predate its earliest record, reads `unknown` and never
  `complete`.
- **One shared `render_report`** in `rendering.py`, returned by both human
  surfaces, carrying `complete`, `limitations`, `skipped`, `refusals` and
  `exhausted_by` beside the counts.
- **The CLI's human summary** names each limitation under a plain sentence.
- **`case_casefile_overview` gains one `ingestion` key** and one `formatted` line
  chosen by verdict, and the tool description and instructions tell the agent to
  read it before treating an empty result as absence.

**Deliberately not in scope.**

- **No declared-size refusal anywhere.** `container-extraction/spec.md:127-131`
  requires an oversized entry to be judged *"by what was read rather than by the
  size the archive declares"*. The shortfall is disclosed; which entry and why is
  not, and the honest fix — moving the ceiling into `_expand`, where
  `budget.take_child` already measures the bytes — changes zip, tar and RAR
  behaviour and wants its own change. Parked in
  `docs/implementation-notes.md`.
- **No new REST route.** A run's coverage belongs in the ingest response.
- **`analyst/role.md` untouched.**
- **The folder-walk path still does not fail** on an unroutable file, which is a
  pre-existing divergence from `document-ingestion/spec.md:66-68`. Neither
  created nor widened here; disclosure is what changes.

**A consequence worth stating.** The CLI's `--json` ingest payload gains
`casefile_id`, which only REST carried before. That is the two surfaces agreeing,
not a new field.

## Impact

**Specs: one new capability, `ingestion-coverage`, and no `MODIFIED` block
anywhere.** Established by falsification against the published set rather than by
topic, and re-checked against the files this session:

| Published text | Verdict |
|---|---|
| `container-extraction/spec.md:106-107` — "the ingest reports itself as incomplete rather than failing wholesale" | still true, more strongly |
| `container-extraction/spec.md:36-37` — an unaccepted entry "is skipped and reported" | still true |
| `container-extraction/spec.md:127-131` — an oversized entry is judged "by what was read rather than by the size the archive declares" | **untouched on purpose** — no declared-size refusal is added anywhere |
| `document-ingestion/spec.md:66-68` — an unaccepted file fails with a typed error | pre-existing divergence on the folder-walk path, neither created nor widened here |
| `document-hierarchy/spec.md:79-81` + its scenario — a count states what it counted | unchanged; the new counts each say what they count |
| `mcp-tool-surface/spec.md` | no requirement asserts a closed payload key set; the tool's own key-set test is extended, not relaxed |
| `schema-migration/spec.md:27-37` | the new step satisfies it — additive, a `CREATE TABLE` and an index, nothing rewritten |

Because real deltas exist, the `.openspec.yaml` `skip_specs: true` escape is
**not** used.

- **Code:** `src/jackryan/services/ingestion.py`, `src/jackryan/services/casefiles.py`,
  `src/jackryan/storage/port.py`, `src/jackryan/storage/sqlite.py`,
  `src/jackryan/storage/migrations.py`, `src/jackryan/rendering.py`,
  `src/jackryan/cli.py`, `src/jackryan/server.py`,
  `src/jackryan/interfaces/mcp/server.py`.
  **`src/jackryan/ingestion/containers.py` is not edited** — it already publishes
  the count the reconciliation reads.
- **Tests:** fifteen added across `test_ingestion.py`, `test_containers.py`,
  `test_migrations.py`, `test_store.py`, `test_mcp_surface.py`,
  `test_result_shape.py` and `test_cli.py`. One existing assertion extended —
  the overview's exact key set — never relaxed. Every new guard is shown red
  against the defect it exists for.
- **Store:** every existing store pays one full-file backup on first open, which
  `schema-migration/spec.md:77-78` requires before any step runs. No repair or
  reingest of any existing corpus is authorised by this change.
- **Docs:** `docs/implementation-notes.md` gains one parked entry;
  `docs/functional-review-todo.md` item 1 is ticked with its evidence.
