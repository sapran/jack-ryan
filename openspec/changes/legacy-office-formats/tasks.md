## 1. The converter dependency

- [x] 1.1 Establish that no new Python package is needed: `docling==2.122.0` already declares the legacy input formats and shells out to LibreOffice for them, so what is missing is the system binary; verify `soffice --version` on the development host and record the version. *LibreOffice 26.8.0.3 via `brew install --cask libreoffice`; neither `soffice` nor `libreoffice` existed on this host before.*
- [x] 1.2 Verify LibreOffice's licence is compatible with this project's AGPL-3.0-or-later position; verify the argument is recorded — MPL-2.0, invoked as a subprocess rather than linked, so no combined work is formed
- [x] 1.3 Prove the converter actually converts before writing any code; verify all four legacy formats reach their modern siblings, and that synthetic HTML and flat-ODF sources reach genuine OLE2 and RTF, so verification needs no committed binary fixture. *Found while doing it: LibreOffice 26.8 rejects a bare `--convert-to doc` with "no export filter"; the legacy export filters have to be named in full (`doc:MS Word 97`). Only the fixture direction is affected — the extractor's own direction takes the plain short form.*

## 2. The extractor

- [x] 2.1 Create `ingestion/legacy_office.py` with `LEGACY_SUFFIXES` mapping `.doc`, `.xls`, `.ppt` and `.rtf` to docling's own media-type strings, and `find_converter()` resolving `libreoffice`, then `soffice`, then the macOS bundle path — the same order docling uses, so a host that satisfies docling satisfies this; verify a test asserts the four suffixes and their media types. *Read from `docling/backend/docx/drawingml/utils.py:33-41` rather than assumed: `libreoffice` is tried first, not `soffice`. The container proves the difference matters — Debian ships `/usr/bin/libreoffice` and it is what resolves there.*
- [x] 2.2 Add `LegacyOfficeExtractor`, subclassing nothing, holding a lazily built DOCX/PPTX delegate and an XLSX delegate; verify `accepts` is suffix-based and a test asserts all four appear in `FormatRouter().supported_suffixes()`
- [x] 2.3 Sniff the first eight bytes and branch on the container rather than the suffix; verify a test asserts an OOXML workbook named `.xls` is read directly with no converter present at all
- [x] 2.4 Refuse a file that is neither the legacy container nor the modern one, naming the file and what was expected; verify a test asserts an HTML file named `.xls` is refused mentioning the file and `OLE2`, and a non-RTF file named `.rtf` is refused mentioning the RTF header
- [x] 2.5 Convert in a per-call scratch directory with its own `-env:UserInstallation` profile and `capture_output=True`; verify the profile is per call because LibreOffice locks its user profile directory and ingestion runs in a thread pool
- [x] 2.6 Locate the output by globbing for the target suffix, never by predicting the name, and treat a count other than one as failure; verify a test with a stub converter that exits 0 and writes nothing asserts the message says no output was produced
- [x] 2.7 Delegate to the extractor that owns the target suffix and re-raise its error naming the *original* file; verify a test asserts the original filename, not the temporary one, appears in the message. *The rewrap prefixes rather than censors: the delegate's own diagnosis is kept behind the original name, because it is the only thing that says what went wrong.*
- [x] 2.8 Return a fresh `Extraction` carrying the delegate's text, the legacy media type, and an extractor of `legacy-office+<delegate>` or `legacy-office-passthrough+<delegate>`; verify a test asserts both literals and that `Extraction` is not mutated, being frozen
- [x] 2.9 Converge every failure path on `ExtractionError` — absent converter, non-zero exit carrying LibreOffice's stderr, timeout, unusable binary; verify tests with a stub converter cover the exit, timeout and empty-output paths, because `_ingest_work` catches only `(ValidationError, ExtractionError)` and anything else ends the run
- [x] 2.10 Leave `text_source` at its default and do not inherit `_GatedReader`; verify a test asserts a passthrough `.xls` reports `native`
- [x] 2.11 **Added during implementation.** Copy a passthrough file into the scratch directory under its true modern suffix before delegating. The plan called for delegating on the original path; that would hand `SpreadsheetExtractor` a `.xls`, which is not in its `suffixes` map, so `sheets.py:74` would raise a **`KeyError`** — not an `ExtractionError`, and therefore a whole-run abort rather than one failed document, in exactly the case this change adds. Verify the passthrough test asserts the workbook rendering and the `legacy-office-passthrough+spreadsheet` extractor.

## 3. Registration

- [x] 3.1 Add the lazy import and one registry entry in `default_extractors`, after `SpreadsheetExtractor()` and before `ImageExtractor(gate)`; verify a test asserts the router selects `legacy-office` for all four suffixes
- [x] 3.2 Verify registration is the whole wiring change: `supported_suffixes()` is derived from the registry and the service takes only the suffix from a container entry, so the four formats work inside ZIP, TAR and MBOX with no further edit

## 4. Operator surfaces

- [x] 4.1 Add `legacy_office` to the `jackryan status` payload, holding the resolved absolute path or the literal `unavailable`; verify running the command shows the path. *Observed: `"legacy_office": "/opt/homebrew/bin/soffice"`.*
- [x] 4.2 Add the same key, with the same vocabulary, to `GET /health`; verify a test asserts both surfaces use the same two-valued vocabulary. *Both read one `converter_status()`, so there is one definition rather than two agreeing ones.*
- [x] 4.3 Verify an absent converter is *not* fatal at startup: a test asserts a non-legacy ingest succeeds with the converter unresolvable. *Also proven through the shipped CLI with LibreOffice genuinely removed from the host: `status` read `"unavailable"` and a `.md` ingest reported 1 ingested, 0 failed.*

## 5. Container

- [x] 5.1 Extend the Dockerfile's single `apt-get install` line with `libreoffice-writer libreoffice-calc libreoffice-impress`, keeping `--no-install-recommends`; verify `docker run --rm <image> soffice --version` prints a version. *LibreOffice 25.2.3.2. The three component packages were enough; `libreoffice-core` was not needed.*
- [x] 5.2 Verify a real conversion works inside the container, not only that the binary exists. *Run with `--network none`: manufactured a genuine `.xls`, extracted it through the real router, and recovered both a Cyrillic and a Latin sentinel — `legacy-office+spreadsheet`, `application/vnd.ms-excel`, `native`.*
- [x] 5.3 Re-measure the image size and replace the Dockerfile's measured-size comment with the observed number; verify the figure comes from `docker images --format '{{.Size}}'` and is not adjusted by arithmetic

## 6. Verification that needs the binary

- [x] 6.1 Add `scripts/verify_legacy_office.py`, fully synthetic, which manufactures genuine OLE2 and RTF files from HTML and flat-ODF sources and runs the real router over each; verify it asserts both a Cyrillic and a Latin sentinel survive, `text_source` is `native`, the media type is the legacy one, and the extractor starts with `legacy-office+`
- [x] 6.2 Run it and record the result in `docs/handover.md`, stating what it settles and what it does not. *5 passed, 0 failed, including the `.ppt` case the plan expected to be uncorroborated.*
- [x] 6.3 Ingest the real dump end to end and record the document count and media-type breakdown; verify the count rises against the 1502 the same dump produced before, since the legacy files were previously invisible rather than failed

## 7. Prove the tests can fail

- [x] 7.1 Remove the OOXML-magic branch and verify the mislabel-rescue test goes red with the reported symptom, then restore. *Red with `book.xls is named .xls but is neither an OLE2 nor an OOXML container` — the workbook is refused instead of read.*
- [x] 7.2 Let a subprocess failure escape as itself, and verify the two stub-converter tests that depend on the `except` clauses go red, then restore. *Amended: the task was written as "widen to bare `Exception` returning an empty `Extraction`" and as covering all three stub tests. Neither was right. An empty `Extraction` would be refused by the usable-text rule, so the test would go red for the wrong reason; and the empty-output test does not reach an `except` clause at all, which is why it is now 7.4. Re-raising is the exact defect the clauses exist to prevent, and it reproduced it: `subprocess.CalledProcessError` and `subprocess.TimeoutExpired` escaped uncaught, which is what would end a 1922-file run.*
- [x] 7.3 Drop the delegate-error rewrap and verify the original-filename assertion goes red, then restore. *Red: the message named only the scratch copy.*
- [x] 7.4 **Added during implementation.** Trust the converter's exit status instead of the glob, and verify the empty-output test goes red, then restore. *Red with `IndexError`, which is itself the point: without the length check the code indexes an empty list, and an `IndexError` is not an `ExtractionError`.*

## 8. Documentation

- [x] 8.1 Record in `CLAUDE.md`'s pitfalls that a legacy format is converted and delegated so the corpus holds one rendering, and that the stored media type is the legacy one
- [x] 8.2 Update `docs/handover.md` with what this change verified and what it did not
- [x] 8.3 Record in `docs/implementation-notes.md` anything found and deliberately not fixed
