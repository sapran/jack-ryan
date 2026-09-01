## Why

A real dump is older than the tooling that reads it. The first substantial dump
put through this workbench held 1922 files; 1502 became documents. Of the 323
files no extractor accepted, 256 were legacy binary Office — 168 `.doc`, 82
`.xls`, 8 `.ppt`, 1 `.rtf` — and they did not fail. They were dropped silently:
a folder walk marks a file it found itself as not named directly, and the
pre-filter in the ingestion service skips such a file with no outcome record at
all. An analyst reading the ingest report sees 1502 ingested, 0 failed, and no
indication that a sixth of the material never entered the corpus.

These are not marginal files. Cross-checked with macOS `textutil` on samples
before any code was written: 11 of 12 `.doc` files yielded over 200 characters
(median 3350), and 12 of 12 `.xls` yielded text (median 81 841 characters). The
material an older case turns on is exactly the material stored in the formats of
its own era.

This is the fourth slice of **M3** and pulls nothing forward. Hard formats were
deferred behind the prototype (design.md § 10) and the prototype has shipped;
the previous three slices delivered containers, the quality gate, and retrieval
measurement.

## What Changes

**Current behaviour.** `.doc`, `.xls`, `.ppt` and `.rtf` are not in any
extractor's suffix map. `FormatRouter.extractor_for` returns `None`, and a file
found by a directory walk is dropped without an outcome.

**Desired behaviour.** The four formats are registered, ingest through the
existing pipeline, and render text identically to their modern equivalents.

- **A legacy format is read by converting it to its modern sibling** and handing
  the converted file to the extractor that already owns that suffix — `.doc` and
  `.rtf` to the DOCX reader, `.xls` to the XLSX reader, `.ppt` to the PPTX
  reader. One corpus therefore never holds two renderings of the same kind of
  document.
- **The stored media type is the legacy type the file actually is**, not the
  type it was converted to. Recording the converted type would assert something
  the corpus does not hold.
- **A file whose container contradicts its suffix is handled on what it is.** An
  OOXML file misnamed `.xls` — the dump held two — is read directly with no
  conversion. A file that is neither OLE2 nor OOXML is refused naming what was
  found, rather than handed to a converter that would fail obscurely.
- **An absent converter fails that document, not the run.** The message names
  the remedy. A host that ingests no legacy file is never stopped by a converter
  it will not use, which is why this is not a startup check like the recognition
  engine.
- **The capability is reported before an operator starts an hour-long run**, on
  `jackryan status` and `GET /health`, in one vocabulary on both.

**Not in this slice.** `.rar` (26 files in that dump) and `.ics` (29) are in the
unsupported tail but are not legacy Office and stay unsupported. `.dot`, `.xlt`,
`.pot` and `.pps` are absent from the dump and are deliberately not registered:
a suffix nobody can demonstrate is a claim nobody can check. The five files
whose names end in an apostrophe are a filename-routing defect already parked in
`docs/implementation-notes.md`, not a format.

## Capabilities

### Modified Capabilities

- `document-ingestion`: a format whose reader does not exist may be read by
  converting it to one that does, with the rules that keep the corpus
  single-rendered and the stored type honest.

## Impact

- `src/jackryan/ingestion/legacy_office.py` — new: the converting extractor and
  the converter lookup.
- `src/jackryan/ingestion/extractors.py` — one lazy import and one registry
  entry in `default_extractors`.
- `src/jackryan/cli.py`, `src/jackryan/server.py` — a `legacy_office` key on the
  two capability payloads.
- `Dockerfile` — LibreOffice's Writer, Calc and Impress packages, and a
  re-measured image size.
- Dependencies: **no new Python package.** `docling==2.122.0` already declares
  the legacy input formats and shells out to LibreOffice for them; what is
  missing is the system binary. LibreOffice is MPL-2.0 and is invoked as a
  subprocess rather than linked, so it does not disturb this project's
  AGPL-3.0-or-later position.
