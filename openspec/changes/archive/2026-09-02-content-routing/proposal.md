# Why

Five documents in the first real dump are named `'… .docx'` and `'… .doc'` — the
shell-style quotes are part of the filename, baked in by whatever exported them.
`Path.suffix` reads `.docx'`, no extractor claims that, and the files are refused
as an unknown format. Four are ordinary OOXML Word documents and one is an OLE2
Word document; all five are readable, and all five are absent from the corpus.

The cost is larger than five files. Routing is the one refusal that says nothing
about what the file *is*: an unreadable PDF is reported with a reason, but a
readable DOCX under a decorated name is dropped as though the format were
unsupported. `docs/implementation-notes.md` records that these five vanished from
the 2026-09-02 reingest without appearing in its report at all, so the corpus
under-reported its own coverage by exactly the documents it could have read.

Trimming punctuation off the name is the obvious fix and the wrong one: it is a
guess about which characters are decoration, and it does nothing for a file
carrying no extension at all — 25 such entries sit inside the archives in this
same dump.

# What changes

Selection stays the registry's job and stays suffix-first. What is added is a
**fallback consulted only when no registered extractor claims the file's
suffix**: the file's leading bytes are read, and if they positively identify a
format the registry already handles, the file is routed to that format's
extractor.

- Positive signatures only — OOXML (discriminated by the part it carries: Word,
  workbook, or deck), OLE2 (discriminated by its stream names), PDF, RTF, ZIP,
  and the image formats. No text fallback, so `.bat`, `.ics`, `.p7s` and `.mp3`
  stay honestly refused rather than being swept in as plain text.
- A file with a suffix the registry knows is **never** sniffed. Content routing
  cannot change how any file that ingests today is read.
- The route is disclosed on the document, so an analyst can tell that a file was
  read as something other than what it was named.

The fallback lives at `FormatRouter.extractor_for`, not at `FormatRouter.extract`.
`services/ingestion.py:217` asks `extractor_for(...) is None` and skips the file
before `extract` is ever called, so a fallback added only to `extract` would be
inert for every folder walk — the exact case this change exists for.

# Impact

- Affected specs: `document-ingestion` (MODIFIED)
- Affected code: `src/jackryan/ingestion/sniffing.py` (new),
  `src/jackryan/ingestion/router.py`
- No change to any extractor, to `supported_suffixes()`, or to the corpus
  contract. Routing settles which extractor reads a file; it writes no vector,
  no chunk and no stored text of its own, so corpus identity is untouched and no
  existing store is refused.
- Recovers the five known documents, and any future file whose name is decorated
  or absent. Does not address the 26 RAR archives (no extractor exists for RAR)
  or the 29 `.ics` calendar files (no extractor exists for iCalendar); both are
  separate gaps, recorded separately.
