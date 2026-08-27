## Context

See `proposal.md` — Why. Three constraints shape the approach.

**Extraction already goes through one object.** `DoclingExtractor` holds a lazily
built `DocumentConverter` and every PDF, DOCX, PPTX, HTML and Markdown file goes
through it. The gate has one place to live, and adding it does not require
touching the router, the pipeline or the service.

**The heavy machinery is already installed.** The pinned `docling==2.122.0` is a
meta-package that pulls `docling-slim` with the `feat-ocr-*` and
`models-vlm-inline` extras. In a fresh `uv pip install -e ".[dev]"` that
resolves to `rapidocr 3.9.2`, `torch 2.13.0`, `transformers 5.8.1` and
`accelerate 1.14.0` — all present today, none of them added by this change.
`docling.pipeline.vlm_pipeline.VlmPipeline` imports with no further install.
This change therefore adds no dependency; it adds model weights fetched on first
use, and the choice of when to spend them.

**Corpus identity deliberately excludes extraction.** `pyproject.toml` records
the reasoning at the `docling` pin: what the extractor produces becomes the
chunks, but a change there produces visibly different *text*, unlike a change of
embedding pooling which produces invisible mismatched *vectors*. This change
does not reopen that decision, and the per-document record of which rung ran is
the compensating control for living with it.

## Goals / Non-Goals

**Goals:**

- One escalation path, decided in one place, that a reader can follow top to
  bottom.
- A born-digital document costs less than it does today, not more.
- Every extraction says which rung produced it, all the way out to the agent.
- A misconfiguration is fatal before any document is read, never a quiet
  degradation.

**Non-Goals:**

- Measuring recognition quality on real scans. The spike settles which model can
  read which script; it is not a benchmark and this change does not claim one.
- Per-region or per-page rung selection. The rung is a property of the document.
  A page-level gate is a larger design and buys nothing until there is evidence
  that mixed documents are common.
- Reprocessing what is already ingested. There is no corpus outside development,
  so no migration is owed. The per-document record is what makes a future
  re-extraction possible.
- PST, which `docs/design.md` § 10 keeps last.

## Decisions

### The gate lives beside the extractor, not inside it

A new `ingestion/quality_gate.py` owns the ladder and the docling pipeline
options for each rung. `DoclingExtractor` asks it for a reading and reports what
came back.

*Why:* the extractor's job in this codebase is "turn one file into text", and
every other extractor is a thin reader. Putting a three-rung escalation policy
inside one of them would make that extractor the exception, and would put the
policy out of reach of the image extractor, which needs the same ladder.

*Alternative rejected:* three registered extractors, one per rung, selected by
the router. The router selects on what a file *is*, not on how well a previous
attempt went; escalation is a loop over one file, which is not what a registry
expresses.

### The first rung turns recognition off

Rung one sets `do_ocr=False`. Today's bare `DocumentConverter()` runs with
docling's default `do_ocr=True`, so a born-digital PDF currently pays for
recognition it does not need.

*Why:* this is both the correctness fix and a speed improvement for the common
case. It is also what makes the rung recorded on the document meaningful — with
recognition folded into the first pass there is no honest way to say whether a
given document's text came off the page or out of an OCR model.

*Cost:* a scan is converted twice. The first conversion of a scan is the cheap
one — there is no text layer to parse — and the alternative is being unable to
distinguish a text layer from recognition at all.

### The floor is characters per page

`min_chars_per_page`, default 100, on the profile. Escalate when
`len(text.strip()) / pages < floor`.

*Why:* absolute character counts do not survive a mixed corpus — 400 characters
is a full page of a letter and nothing at all in a 200-page report. The observed
gap is wide: the probe's English scan recovered 128 characters per page with
recognition and 0 without, while a born-digital page runs to thousands. Any
threshold in the low hundreds separates them; the value is configurable because
that claim is from one fixture.

*Alternative rejected:* asking the PDF backend whether a text layer exists. It
is a docling-internal detail, it does not generalise to images, and a PDF with a
partial or junk text layer would answer "yes" and defeat the gate.

### `eslav` on RapidOCR is the default

Settled by the spike in `proposal.md`. RapidOCR is already installed, needs no
system package and no torch build, and one `eslav` recognition model reads
Ukrainian, Russian and English from one page.

*Why not EasyOCR*, which `docs/design.md` § 5 names as the intended default: it
is not installed by the current pin, so it would be a new dependency, and the
spike shows the installed engine already covers all three working languages. The
design document names EasyOCR in the same paragraph that calls the engine
pluggable, and § 11 leaves the choice open until M3 precisely so it could be
decided on evidence. It remains selectable.

*Why not Tesseract:* a system package the image must install, for no measured
gain over an engine already present.

*One language, not a list.* docling's RapidOCR adapter reduces a language list
to its first element and logs the rest away. An operator who writes three
languages would have two silently dropped, which is the failure this whole
change is about, so the configuration takes exactly one and refuses a list.

### `auto` is refused rather than defaulted away from

`OcrAutoModel` picks by platform: `ocrmac` on darwin, `nemotron` on linux, then
rapidocr, then easyocr. It also forwards only `mode` to the engine it builds, so
a language set under `auto` is silently ignored, and with no engine importable
it logs a warning and yields pages unchanged.

Setting a different default would leave `auto` reachable by anyone who writes it
in a profile, and it would do all three of those things. It is refused at
configuration load, naming the setting.

### The vision rung is implemented and off

Rung three uses docling's `VlmPipeline` with a model spec named in the profile;
absent, the rung does not exist. `GRANITEDOCLING_TRANSFORMERS` is the reference
spec — 258M parameters, small enough to actually run.

*Why implement it now rather than leave a seam:* the seam is the expensive part
to get right, and the dependency is already installed. Shipping the rung unbuilt
would mean designing the ladder twice.

*Why off by default:* it downloads model weights and is slower by a large factor.
A deployment must choose to spend that, and the two rungs above it handle the
documents that are not hard.

### The rung is a new column, not a reinterpretation of `extractor`

`documents.extractor` names which extractor ran (`docling`, `plaintext`, …). The
rung is orthogonal: `docling` covers all three rungs and `plaintext` covers
none. A new `text_source` column takes `text-layer | ocr | vlm | native`.

*Why not overload `extractor`:* it is already surfaced and already means
something; two facts in one column is how the `contract`-versus-corpus-identity
naming drift in `docs/implementation-notes.md` started.

### The check builds the engine, and runs once per ingest

`IngestionService.ingest` verifies the engine before it reads the first
document, and the verification *builds* the recognition pipeline rather than
looking anything up.

*Why build it:* `docs/handover.md` records this repository hitting the same
lesson four times — a stored value says what *should* load, not what *does*. It
bites here in a specific way: a `DocumentConverter` builds its pipelines lazily,
so constructing one with `ocr_language='klingon'` returns an object quite
happily and fails on the first scan instead. `initialize_pipeline` builds the
recognition model, which is what actually answers whether the engine and the
language work here, and it raises naming every language the backbone serves.

*Why per run and not at process start:* an instance that only searches never
needs a recognition engine, and building one costs seconds plus a possible model
download — a cost `jackryan status` and every other read should not pay. The run
is the unit that matters, because a run that stops part way has already stored
documents, and which ones depends on the order the files happened to be walked.

*Alternative rejected:* checking on the first document that needs recognition.
By then the run has stored whatever came before it in the walk.

*Accepted weakness:* the vision model is resolved by name, not built. Its
weights are gigabytes and the rung is reached rarely, so charging every run for
it would be worse than the gap. A vision model that resolves but cannot run
fails on the first document that needs it, and the specification says so rather
than implying the same guarantee as the recognition engine.

## Risks / Trade-offs

**A scan is converted twice.** → Accepted. The wasted pass is the cheap one, and
it buys the distinction between a text layer and recognition, which is the whole
provenance claim.

**The floor is one number from one fixture.** → It is configurable, its default
sits in a gap the probe measured as roughly 0-versus-thousands, and a document
that falls the wrong side escalates or does not — it is never dropped, because
the richest attempt is always the result.

**Recognition weights are fetched from ModelScope, not Hugging Face.** RapidOCR
downloads from `modelscope.cn`, a different host from the one the embedder and
the docling layout models use. → The Dockerfile's existing `PREFETCH_MODELS`
build argument gains the recognition weights, so an offline image can OCR from
its first run; the differing host is recorded in `docs/handover.md` because an
air-gapped deployment must allow or mirror it. This change adds no runtime
egress that a first-use model download did not already imply.

**Recognition output is fluent and can be wrong.** A misread word reads as a real
word, and nothing downstream can detect it. → This is why `text_source` reaches
the agent surface rather than stopping at the database. It is a disclosure, not a
fix; the spec says so and the handover will too.

**A born-digital PDF's text may change**, because it is no longer OCR'd on the
first pass. → No corpus exists outside development, and the fingerprint does not
guard the extractor by an existing deliberate decision. Stated in the proposal
rather than enforced by a refusal.

**Tests cannot run the models.** CI has no weights and no network guarantee. →
The ladder is tested against a stand-in reader, the same way the embedder is
tested against a deterministic stand-in: the gate's escalation logic, the floor,
the refusal and the recorded rung are all exercised without a model. What only a
real model can settle is verified by hand and written into `docs/handover.md`,
which is where this repository already keeps that distinction.

## Migration Plan

`documents` gains a `text_source` column and `SCHEMA_VERSION` goes from 4 to 5.

There is no in-place migration, because this store has never had one: `_SCHEMA`
is `CREATE TABLE IF NOT EXISTS`, there is no `ALTER TABLE` anywhere, and
`_verify_meta` refuses a store whose recorded `schema_version` differs from the
running one. So an existing store is **refused until it is recreated**, which is
the same outcome the two fingerprint changes already produced, and it is stated
plainly rather than described as an additive step.

That is acceptable for exactly one reason, and it is worth being precise about
it: no corpus exists outside development. Once one does, this store will need a
real migration path, and that is a larger piece of work than any single change
should smuggle in.

No backfill would have been possible anyway: a document ingested before this
change has no honest value to record, and inventing one would put a false
provenance on evidence.

## Open Questions

None that change the specs, the approach or the tasks. Recognition quality on
real scans stays unmeasured, and is recorded as such — the same open item
`docs/handover.md` already carries for retrieval quality.
