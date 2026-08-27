## 1. Configuration

- [x] 1.1 Add extraction settings to `Profile`: `ocr_engine` (default `rapidocr`), `ocr_language` (default `eslav`), `min_chars_per_page` (default 100), `vlm_model` (default empty, meaning the rung is off); verify a test asserts every default and that the full suite passes unchanged
- [x] 1.2 Refuse `auto` as an `ocr_engine` at configuration load, naming the setting and why a host-chosen engine is not acceptable; verify a test asserts the failure and that the message names `ocr_engine`
- [x] 1.3 Refuse a list of `ocr_language` where the engine takes one, at load; verify a test asserts the failure names the setting
- [x] 1.4 Refuse an unknown key in a profile block, naming it; verify `config.yaml.example` still loads and a test asserts a mistyped key is fatal
- [x] 1.5 Verify extraction settings do not enter the corpus fingerprint: a test changes `ocr_language` and asserts corpus identity is unchanged and an existing store still opens

## 2. The quality gate

- [x] 2.1 Create `ingestion/quality_gate.py` with a `Reading` result carrying text and the rung that produced it, and a `QualityGate` that takes the profile's extraction settings; verify it is importable without constructing any model
- [x] 2.2 Implement rung one — convert with recognition disabled — and the floor test `chars/pages < min_chars_per_page`; verify a test with a stand-in reader asserts a text-layer document stops at rung one and that no further rung is attempted
- [x] 2.3 Implement rung two — convert with recognition enabled, engine and language from the profile; verify a test asserts a document below the floor escalates exactly once and reports the recognition rung
- [x] 2.4 Implement rung three — `VlmPipeline` with the configured model spec — attempted only when rung two is below the floor and a model is configured; verify a test asserts it is not attempted when unconfigured, and is attempted when configured
- [x] 2.5 Return the richest attempt when no rung clears the floor; verify a test asserts the longest of several below-floor readings is what comes back
- [x] 2.6 Determine page count for the floor from the converted document, defaulting to one where a format reports none; verify a test asserts a multi-page document and a single-page image are both scored per page

## 3. The extractors

- [x] 3.1 Route `DoclingExtractor` through the gate for PDF only, leaving DOCX, PPTX, HTML and Markdown on a single direct parse; verify a test asserts a Markdown file is never escalated whatever its length
- [x] 3.2 Add image suffixes — `.png`, `.jpg`, `.jpeg`, `.tif`, `.tiff`, `.bmp`, `.webp` — as an extractor that reads through the same gate; verify a test asserts an image is accepted rather than refused as unsupported, and that `supported_suffixes()` reports them
- [x] 3.3 Carry the rung on `Extraction` as `text_source`, set to `native` by every extractor that does not use the gate; verify a test asserts each existing extractor reports `native`
- [x] 3.4 Tighten `FormatRouter.extract`'s usable-text refusal to require a letter or digit in some script; verify a test asserts `'.\n\n:    .'` is refused, and that Cyrillic-only and digit-only text are both accepted

## 4. Startup

- [x] 4.1 Verify the configured engine once at the start of an ingest run, before the first document, with a message naming the setting and how to proceed without it; verify a test asserts an unserviceable language stops the run before anything is stored
- [x] 4.2 Verify the failed engine does not degrade: a test asserts the run fails rather than continuing with recognition disabled, and that nothing was stored
- [x] 4.3 Accept an injected gate in `build_context`, exactly as it accepts an injected embedder, so the suite wires a real instance without loading models; verify searching and reading construct no engine and the suite still runs with no network

## 5. Storage and surface

- [x] 5.1 Add a `text_source` column to `documents` with an additive schema step defaulting to the empty string; verify a test opens a store created before the column and asserts it still reads
- [x] 5.2 Persist and return `text_source` through the document row and the service layer; verify a test asserts it survives reingest and reflects the rung of that ingest
- [x] 5.3 Report `text_source` on passage and citation payloads through the MCP shapes; verify a test asserts both carry it and that the value is fenced like every other corpus-derived value
- [x] 5.4 Verify the sanitisation seam: a test asserts a `text_source` value cannot break the fence, by the same assertion pattern used for `found_at`

## 6. Verification that needs a model

- [x] 6.1 Extend `scripts/verify_model_paths.py` with a check that an image-only PDF of Ukrainian, Russian and English escalates to recognition and recovers all three; verify it fails when the language is forced to `en`
- [x] 6.2 Run the extended script and record the result in `docs/handover.md`, stating what it settles and what it does not
- [x] 6.3 Run the vision rung once against `GRANITEDOCLING_TRANSFORMERS` and record what happened in `docs/handover.md`; if it cannot be run, record that instead rather than leaving it implied
- [ ] 6.4 Add the recognition weights to the Dockerfile's `PREFETCH_MODELS` path; verify by building with the argument and running an OCR extraction inside the container with networking disabled

## 7. Prove the tests can fail

- [x] 7.1 Reintroduce the punctuation-only acceptance and verify the new refusal test goes red with the reported symptom, then restore
- [x] 7.2 Force the gate to stop at rung one and verify the escalation test goes red, then restore
- [x] 7.3 Make the startup engine check non-fatal and verify the startup test goes red, then restore

## 8. Documentation

- [x] 8.1 Record the resolved engine and language decision in `docs/design.md` § 11, moving it out of "still open"
- [x] 8.2 Update `CLAUDE.md`'s pitfalls with the gate's invariants: recognition is never inferred from the host, a failed engine is fatal, and `text_source` is a disclosure rather than a guarantee
- [x] 8.3 Update `docs/handover.md` with what this change verified and what it did not, including that recognition quality on real scans is unmeasured
- [x] 8.4 Record in `docs/implementation-notes.md` anything found and deliberately not fixed
