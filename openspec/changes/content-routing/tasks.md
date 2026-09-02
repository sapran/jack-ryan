# 1. The signature table

- [x] 1.1 CREATE `src/jackryan/ingestion/sniffing.py` with
  `sniff_suffix(path: Path) -> str | None`, returning a declared suffix
  (`".docx"`, `".pdf"`, …) or `None`. Positive signatures only; no text
  fallback. Read a bounded prefix, never the whole file.
- [x] 1.2 Discriminate OOXML by the archive's name list: `word/document.xml` →
  `.docx`, `xl/workbook.xml` → `.xlsx`, `ppt/presentation.xml` → `.pptx`,
  otherwise `.zip`. A `BadZipFile` yields `None`, never an exception out.
- [x] 1.3 Discriminate OLE2 by UTF-16LE stream names in the prefix:
  `WordDocument` → `.doc`, `Workbook` → `.xls`, `PowerPoint Document` → `.ppt`,
  `__substg1.0_` → `.msg`. Unrecognised OLE2 yields `None`.
- [x] 1.4 Add the unambiguous signatures: PDF, RTF, PNG, JPEG, GIF, WebP, TIFF,
  BMP. Every returned suffix MUST be one some shipped extractor declares —
  assert that against the live registry in a test, so adding a signature for a
  format nothing reads cannot ship.
- [x] 1.5 An unreadable file yields `None` rather than raising: sniffing runs
  where the alternative is a refusal, and must not turn one file's permissions
  into a failed run.

# 2. Routing

- [x] 2.1 MODIFY `FormatRouter` with a single private resolution returning the
  extractor and, when the decision came from content, the resolved suffix.
- [x] 2.2 MODIFY `extractor_for` to suffix-first, content-second, so
  `services/ingestion.py:217` and `:292` inherit the fallback unchanged. Leave
  `supported_suffixes()` alone.
- [x] 2.3 MODIFY `extract`: suffix-chosen files pass through exactly as today;
  content-chosen files are copied into a scratch directory as
  `<stem><resolved suffix>`, the delegate reads the copy, and the scratch is
  removed in a `finally` — the `legacy_office._copy_as_target` shape.
- [x] 2.4 Wrap the delegate's result as `content-routed+<delegate>`, carrying
  `media_type`, `metadata`, `refusals` and `text_source` through unchanged.
- [x] 2.5 Keep the existing usable-text and container-exemption check applying
  to both paths, as one check rather than two.
- [x] 2.6 Name the file the operator has, not the scratch copy, in every error
  raised on this path.

# 3. Tests

- [x] 3.1 `sniff_suffix` returns the right suffix for a real DOCX, XLSX, PPTX,
  PDF, RTF, ZIP and PNG, built as fixtures rather than asserted from constants.
- [x] 3.2 `sniff_suffix` returns `None` for a UTF-8 text file, a batch script
  and random bytes — the near misses that must be refused.
- [x] 3.3 Every suffix `sniff_suffix` can return is declared by some extractor
  in `default_extractors()`.
- [x] 3.4 A DOCX named `x.docx'` ingests **through `IngestionService` on a folder
  walk**, and lands as a document with text. This is the tripwire for the
  pre-filter: it MUST be shown to fail with the fallback removed.
- [x] 3.5 A file with a known suffix is never sniffed: a `.docx` whose bytes are
  a PDF is still handed to the extractor claiming `.docx`, and sniffing is not
  consulted. Assert by instrumentation, not by outcome.
- [x] 3.6 A content-routed document records `content-routed+<delegate>` and
  keeps its on-disk filename, quotes included.
- [x] 3.7 An unsignatured file is still refused, and the error names the file
  and its type.
- [x] 3.8 A content-routed container stores and expands: entries become
  children.
- [x] 3.9 A file that sniffs to a format whose extractor then fails raises
  `ExtractionError` naming the operator's filename — not `KeyError`, and not the
  scratch path.
- [x] 3.10 The scratch directory is gone after both success and failure.

# 4. Verification

- [x] 4.1 Run `pytest -q`; the full suite is green.
- [x] 4.2 Show every new test fails without the change: remove the fallback,
  watch each go red with the reported symptom, restore.
- [x] 4.3 Smoke test through the CLI against the five real files, in a scratch
  data directory — never the live corpus. Confirm five documents ingest, each
  with text, and that `.ics`, `.bat`, `.p7s` and `.mp3` siblings are still
  refused.
- [x] 4.4 Confirm corpus identity is unchanged, and that the live store still
  opens under the built stack.
- [x] 4.5 `openspec validate --all --strict`.

# 5. Ship

- [x] 5.1 Update the parked entry in `docs/implementation-notes.md`: the routing
  half is fixed, the invisible-refusal half is not.
- [x] 5.2 Add the `content-routed` lineage and the no-text-fallback rule to the
  pitfalls in `CLAUDE.md`.
- [x] 5.3 `openspec sync` then `openspec archive`, PR, review, merge.
