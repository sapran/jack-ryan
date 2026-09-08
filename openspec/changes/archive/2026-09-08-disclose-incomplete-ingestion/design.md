## Context

Three coverage facts already exist on `IngestReport` and reach no surface. The
question this design answers is not "how do we compute coverage" — most of it is
computed — but **what a casefile may honestly claim about itself**, and where that
judgement lives.

## Decision 1: three states, not two, and `unknown` is the default

A boolean cannot express this corpus's real situation. Every casefile that exists
today was filled before any run was recorded, so a two-state verdict must call
those either `complete` — a lie about 435 MB of evidence nothing accounts for —
or `incomplete`, which is a claim of a known gap where there is only an unknown
one.

The verdict is therefore **`complete` / `incomplete` / `unknown`**, and the rule
is:

```
recorded.runs_with_limitations   → incomplete
recorded.runs == 0               → unknown
recorded.documents_before_first_run > 0 → unknown
otherwise                        → complete
```

`unknown` is not a degraded `complete`. It says *the record cannot answer*, which
is a different and weaker statement than *there is a gap*, and both are stronger
than the silence that ships today.

**Why a recorded limitation outranks an unaccounted-for corpus.** A known gap is
a fact worth stating; `unknown` only says the record cannot answer. Nothing is
hidden by the ordering, because every surface reports the counts beside the word
— a caller who wants to know both reads
`documents_predating_the_record` and `runs_with_limitations` in the same payload.
Inverting the first two branches is a defensible alternative and costs two test
expectations; it is recorded in the change's contingencies rather than argued
here.

## Decision 2: `documents_before` is the basis for `unknown`

The whole three-state design turns on one recorded integer: how many documents
the casefile held when a run began.

Nothing else can distinguish *"no run has reported a problem"* from *"no run
accounts for this evidence"*. Without it, deleting the `ingest_runs` rows of a
mixed corpus — or simply upgrading an existing instance and running one clean
ingest — produces a casefile that reports `complete` while most of its documents
arrived by a route no record describes. That is a worse failure than the silence
this change removes, because it is a confident wrong answer rather than an absent
one.

It is read **once**, in `ingest`, before the budget is built and before anything
is written. Read anywhere later it would already include the run's own documents.

The aggregate reads it back with an ordered `SELECT … ORDER BY started_at, id
LIMIT 1` rather than `MIN(documents_before)`. Deleting documents makes the
minimum stop being the earliest run's value; the tie-break on `id` keeps it
deterministic, which is the same discipline `retrieval.py` applies to fused ranks
and for the same reason — a value that varies between runs of an unchanged corpus
cannot be reasoned about.

## Decision 3: the verdict is a service rule, the counts are the store's

`IngestionCoverage` (storage) holds counted facts only. `CasefileCoverage`
(service) holds the verdict and the counts behind it.

Two reasons, both already settled precedent in this repository:

- **`storage-seam`** — the store speaks in domain objects and holds no rules. A
  store that computed the verdict would be a second opinion about what its own
  counts add up to, and two opinions can drift.
- **`casefile_statistics`** — the agent surface previously reached the store
  directly for exactly this shape of data, because `CasefileService` had no
  method and nothing forced one to exist. `coverage` is written on
  `CasefileService` for the same reason `statistics` was: it describes a
  casefile, and `test_no_adapter_reaches_the_store` will fail the day a surface
  tries the shortcut instead.

`CasefileCoverage` holds `recorded: IngestionCoverage` rather than a flattened
copy of its fields. Restating the counts would be a second place they could
drift, and there is no readability gain to buy with that risk.

## Decision 4: the per-entry ceiling is reconciled, not re-decided

All three container extractors `continue` past an over-ceiling entry in
`iter_children` with no record, while `extract()` has already listed it. The
container's own searchable text then names a document that never exists.

The obvious fix — refuse in `extract()` on the declared size — is **rejected**:
`container-extraction/spec.md:127-131` requires that decision to rest on bytes
read, because a declared size is chosen by whoever built the archive. Adding a
declared-size refusal would contradict a published requirement to fix a
disclosure gap.

So the service reconciles instead, against `metadata["entries"]` — the count all
three extractors already publish, already read by six tests. This is the weaker
report (a shortfall, not which entry or why) and the stronger seam: it catches
every silent skip in that pass, **including ones added later**, without a second
definition of what is too large living in the service.

`listed.isdigit()` guards the parse, so the mail extractors — which publish no
`entries` — are skipped rather than compared against zero, which would
manufacture a refusal for every message in an `.mbox`.

**Not reported when a bound stopped the container or its expansion raised.** Both
already appended a refusal naming the cause; the shortfall is that cause's
consequence, and reporting it separately would count one event twice and read as
two independent findings.

The honest fix is to move the ceiling into `_expand`, where `budget.take_child`
already measures `len(child.data)`. That changes zip, tar and RAR behaviour and
one existing test, so it is parked rather than smuggled in here.

## Decision 5: the run row is written after the loop, and its absence is made detectable

A run that raised part way is **deliberately left unrecorded**.

Recording it would require deciding what a half-run covered, and any answer is a
guess. `finally` would instead record a row asserting the run finished, which is
the one thing known to be false.

**Corrected after review, because the original form of this decision was
wrong.** It claimed that leaving a raised run unrecorded "makes the next
reader's verdict `unknown`". That is true only of a *first* run. Three reviewers
independently reproduced the consequence by execution: a run that aborts after
any clean recorded run leaves the documents it already wrote in the corpus, the
earliest recorded run still began against an empty casefile, every recorded run
is clean — and the verdict read `complete` with offered files missing. Measured
at four documents held against six offered. That is the one answer this whole
capability exists to prevent, and absence of a record could not detect it.

So absence is kept, and made **detectable**: each row records the casefile's
document count both before and after its run, and a gap between one run's
`documents_after` and the next run's `documents_before` is a continuity break
that forces `unknown`. Chosen over marking an aborted run, because a marker
cannot be written by a process that was killed, nor by a run whose own record
write failed; the gap catches both. Chosen over an unfinished-row scheme because
`delete_document` is exposed on no surface in this repository, so continuity
chaining has no reachable false positive from legitimate curation.

**The write itself is allowed to raise.** An insert of eleven values that fails
means the store is broken, and a caller who ingested a folder needs to hear that
rather than receive a clean-looking report. There is no logger anywhere in
`src/jackryan`, so a swallow would leave no artifact at all — and that failure is
the one the gap catches for free, since the next run finds documents this one
never accounted for.

## Decision 6: `limitations` derives, `complete` derives from it

The previous shape computed the verdict alongside the reasons, which permits a
run reported `complete` while carrying a reason. Deriving `complete` from
`limitations` makes that unreachable rather than merely untrue today.

It also **strengthens `complete`**: it previously meant "expansion was not cut
short", which reported a run where three of five documents failed as complete.
Every existing assertion on `complete` in the suite is negative
(`test_containers.py:93`, `test_expansion_budget.py:104`, `:122`), so widening it
breaks none of them — which is a fact about the suite, checked, not a hope.

## Decision 7: one renderer for both human surfaces

`cli.py` and `server.py` already built the same five-key payload twice, and
`rendering.py` exists precisely because such copies drifted before. The fields
added here are the ones a caller decides whether to trust the corpus on, so two
copies of that answer is one too many.

The agent surface is absent from `render_report` for the same reason it is absent
from every other renderer in that module: it does not ingest. It reads the
casefile's accumulated verdict instead, which is a different question — *what may
be claimed about this corpus* rather than *what did this run do*.

## Risks

- **Every existing store pays a full-file backup** on first open, which
  `schema-migration/spec.md:77-78` requires before any step runs. Expected; the
  435 MB corpus will copy once.
- **Every existing casefile reads `unknown`** after this ships, and will keep
  reading `unknown` however many clean runs follow, because `documents_before`
  for its first recorded run will be non-zero. That is correct, and it is the
  design working rather than a migration gap — but it means the `complete`
  verdict is unreachable for any casefile that predates this change without a
  reingest into a fresh one. Stated here so nobody later "fixes" it.
- **The reconciliation is a count, not an explanation.** An analyst learns that
  two of five entries never arrived, not which. Parked with the ceiling.
