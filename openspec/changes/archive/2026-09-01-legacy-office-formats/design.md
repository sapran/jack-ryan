## Context

See proposal.md § Why for motivation.

Four properties of the code as it stands shape everything below.

`Extraction` is a **frozen** dataclass (`ingestion/extractors.py`). A result is
built, never adjusted. An extractor that wants a delegate's text under its own
media type constructs a new one.

Extractor selection is **duck typing, not inheritance**. Neither `Extractor` nor
`ContainerExtractor` is `@runtime_checkable`, and nothing performs an
`isinstance` against them: `router.extractor_for` calls `accepts`,
`router.supported_suffixes` reads `suffixes`, and both the router and the
ingestion service test for container behaviour with `getattr`/`hasattr`. A new
extractor subclasses nothing.

`IngestionService._ingest_work` catches exactly `(ValidationError,
ExtractionError)`. Anything else propagates out of the loop and ends the run.
For a 1922-file ingest that means one malformed legacy file could discard an
hour of work — so every failure path here converges on `ExtractionError` and
nothing else escapes.

`router.supported_suffixes()` is derived from the registry, and the ingestion
service materialises a container entry as `<workspace>/<doc-id>/000003.doc`,
taking only the suffix from the entry's name and re-routing it. Registration is
therefore the entire wiring change: the four formats work inside ZIP, TAR and
MBOX with no further edit.

## Goals / Non-Goals

**Goals:**

- One rendering per kind of document in one corpus, whatever era the file is
  from.
- A stored media type that describes the file on disk, not the pipeline that
  read it.
- Per-file failure with an actionable message, never a run-ending exception.
- The capability visible before a long run rather than discovered 256 times
  during one.

**Non-Goals:**

- Concurrency. Conversions run one at a time. Making them parallel needs the
  per-call LibreOffice profile proven safe under load first, which is a separate
  argument with its own evidence.
- A pure-Python reader. See § Decision 1.
- Registering legacy template and show suffixes (`.dot`, `.xlt`, `.pot`,
  `.pps`). None appears in the dump this change is answering, so none can be
  demonstrated.

## Decisions

### 1. LibreOffice, not a pure-Python reader

`xlrd` reads `.xls` and nothing else — 82 of 256 files. There is no maintained
pure-Python reader for Word 97 `.doc` or PowerPoint 97 `.ppt`; `olefile` and
`oletools` are already installed but inspect OLE structure and macros, not
document body text.

A partial path is worse than none here, because covering `.xls` alone means
adding a *second* spreadsheet rendering to sit beside `SpreadsheetExtractor`'s —
the precise outcome § Decision 2 exists to prevent.

Verified on the development host: LibreOffice 26.8.0.3 converts all four legacy
formats to their modern siblings, and converts synthetic HTML and flat-ODF
sources *into* genuine OLE2 and RTF files, which is what makes an out-of-suite
verification script possible with no committed binary fixture.

*Contingency.* If the container size increase proves unacceptable, ship the
extractor and leave the binary out of the image: every legacy file then fails
with the "install LibreOffice" message and the other 1599 files are unaffected.
Do not substitute the partial pure-Python path.

### 2. Convert and delegate, rather than let docling read the legacy file

`docling==2.122.0` already maps `InputFormat.DOC/XLS/PPT` to its Word, Excel and
PowerPoint format options, so adding the three suffixes to `MARKUP_SUFFIXES`
would appear to work. It is rejected for three reasons, each independently
sufficient:

- **It would produce two spreadsheet renderings.** docling's `msexcel_backend`
  emits a different text shape from the 227 `.xlsx` documents already in this
  corpus, which `SpreadsheetExtractor` renders as `## sheet: <name>` /
  `row N: a | b | c`. `openspec/specs/container-extraction/spec.md` requires
  that a spreadsheet be rendered so each sheet is identified and each row is
  recoverable. Two renderings in one corpus breaks it — and breaks it invisibly,
  in retrieval quality, not in an error.
- **It would discard the diagnostic.** docling's `convert_to_modern_format`
  sends LibreOffice's stdout and stderr to `DEVNULL`, so a failed conversion
  arrives as a bare `CalledProcessError` with no text an operator could act on.
- **It does not cover `.rtf` at all.** docling's `InputFormat` has no RTF member,
  so that format needs its own route regardless — and one mechanism for four
  formats beats two mechanisms for three and one.

So: convert to the modern sibling, then hand the converted file to the extractor
that already owns that suffix. `.doc` and `.rtf` → `.docx` → `DoclingExtractor`;
`.xls` → `.xlsx` → `SpreadsheetExtractor`; `.ppt` → `.pptx` → `DoclingExtractor`.

### 3. Sniff the container, and act on what it is

The dump proves suffix and content disagree in practice: two `.xlsx` files
misnamed `.xls`, and one `text/html` file misnamed `.xls`. Reading the first
eight bytes costs nothing and separates three outcomes:

| bytes | action |
|---|---|
| OOXML (`PK\x03\x04`) under a legacy suffix | skip conversion, delegate on the original |
| OLE2 (`\xd0\xcf\x11\xe0…`) under `.doc`/`.xls`/`.ppt` | convert |
| `{\rtf` under `.rtf` | convert |
| anything else | refuse, naming what was expected |

The passthrough case is the one that changes an outcome rather than a message:
those two workbooks become real documents instead of a LibreOffice error.

`accepts()` stays **suffix-based** and does not sniff. `supported_suffixes()` is
derived from `suffixes` and must keep advertising all four, and a router that
answered "supported" only after opening the file would make support a property
of content rather than of the registry.

### 4. Failure vocabulary

The `extractor` column is where a reader learns which path produced the text.
Two literals, and no others:

- `legacy-office+<delegate>` — a conversion ran.
- `legacy-office-passthrough+<delegate>` — the file was already modern.

A delegate's own `ExtractionError` is re-raised naming the **original** file. The
temporary converted file's name is meaningless to whoever reads the ingest
report.

`CONVERSION_TIMEOUT_S` is a module constant, not a profile setting. The profile
layer is for what an operator tunes per deployment; a ceiling that stops a hung
`soffice` is a safety bound, not tuning. It also overrides no operator-supplied
value, which is the objection recorded against `WINDOW_MAX_CHUNKS_EITHER_SIDE`
in `docs/implementation-notes.md`.

### 5. A per-call LibreOffice user profile

LibreOffice takes an exclusive lock on its user profile directory. Two
conversions sharing one profile collide — and the ingestion service already runs
in a thread pool from M1. Each conversion therefore gets
`-env:UserInstallation=file://<tempdir>/profile`, removed with the rest of the
scratch directory in a `finally`.

`capture_output=True` rather than docling's `DEVNULL`, so LibreOffice's own
stderr reaches the error message. Arguments are passed as a list with an
absolute resolved path, so the dump's Cyrillic filenames with spaces need no
quoting.

### 6. The output is found by globbing, not by predicting its name

LibreOffice exits 0 in some cases while writing nothing. `sorted(out_dir.glob(
f"*.{target}"))` returning exactly one entry — not the exit status — is the real
gate on whether a conversion happened. Each conversion gets a fresh scratch
directory, so exactly one output is the correct expectation.

### 7. Reported as a capability, not enforced at startup

`QualityGate.verify()` runs before the first file of an ingest and aborts the
run. That is right for the recognition engine, which every page-bearing document
needs. It is wrong here: a host ingesting no legacy file must not be stopped by
a converter it will never use.

Instead the resolved absolute path — or the literal `"unavailable"` — appears
under `legacy_office` on `jackryan status` and `GET /health`. One vocabulary on
both surfaces, as `extraction-quality-gate` requires of `text_source`.

### 8. `text_source` is left at its default

None of these formats is made of page images. A converted `.docx` or `.pptx` is
not in `PAGE_SUFFIXES` and never reaches a rung, and `Extraction.text_source`
already defaults to `native`. The quality gate is nevertheless threaded through
to the DOCX delegate rather than dropped, so the test suite's gate fixture —
whose rung readers raise a `BaseException` subclass — stays able to prove that
no legacy format reaches recognition.

`extraction-quality-gate` needs no change: its scenario "A format without pages
is never escalated" already covers "a word-processor, spreadsheet, message or
markup document", and `.pptx` is governed by that clause today without being
named.

## Risks / Trade-offs

- **Image size.** The Dockerfile's measured comment (5.81 GB without weights,
  10.2 GB with, arm64, 2026-08-27) is invalidated by this change. It is
  re-measured from the built image, not adjusted by arithmetic.
- **`libreoffice-writer libreoffice-calc libreoffice-impress` may not be the
  minimal Debian set.** Unverified until the container builds. If `soffice
  --version` works but a conversion fails inside the container, add
  `libreoffice-core`; if that fails, use the `libreoffice` metapackage and
  re-measure.
- **Conversion cost.** 256 conversions at up to 120 s worst case, against a full
  1922-file ingest that took 1 h 6 m without them. Measured in verification. If
  it makes a run impractical, lower `CONVERSION_TIMEOUT_S`; do not add
  concurrency without first proving the per-call profile safe under load.
- **A LibreOffice-converted document may read worse than a native one.** If a
  converted `.ppt` yields no usable text, the existing usable-text rule refuses
  it per file with a named reason. Do not add rung escalation to compensate — a
  presentation carries no page images and escalating it is what
  `extraction-quality-gate` forbids.

## Migration Plan

None. No schema change, no contract change, no corpus invalidation: extraction
settings are profile, not contract, and this adds no setting at all. An existing
store opens unchanged. Legacy files in an already-ingested casefile were never
stored, so re-running an ingest over the same folder adds them as new documents
and leaves every existing document's identifier intact.
