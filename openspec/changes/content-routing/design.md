# Context

See proposal.md § Why. Four properties of the code as it stands shape everything
below.

**Every extractor selects on `path.suffix` and nothing else.**
`legacy_office.py:147-153` argues for that deliberately: an `accepts` that opened
the file "would make format support a property of content rather than of the
registry". This change does not touch that. Selection by suffix remains the rule;
content is consulted only where the rule has no answer.

**Every extractor also *reads* `path.suffix` internally**, to key its media type
— `TEXT_SUFFIXES[path.suffix.lower()]` (`extractors.py:123`),
`MARKUP_SUFFIXES[suffix]` (`:237`), `self.suffixes[path.suffix.lower()]`
(`sheets.py:74`), `_TARGET[suffix]` (`legacy_office.py:157`). Handing any of them
a file still named `.docx'` raises `KeyError`, which is not an `ExtractionError`
and therefore aborts the whole ingest run instead of failing one document.

**The precedent for this is already in the tree.** `legacy_office.py:184` meets
the same problem — a file whose real format differs from its name — with
`_copy_as_target`: copy into a scratch directory under the suffix the delegate
expects, delegate, delete the scratch. This change reuses that shape rather than
inventing a second one.

**The pre-filter is where a fix goes inert.** `services/ingestion.py:217` skips
any file for which `extractor_for` returns `None`, before `extract` is called.

# Goals / Non-Goals

- Goal: a file whose name defeats suffix routing is read as what it is.
- Goal: nothing that ingests today changes how it is read.
- Non-goal: new formats. RAR and iCalendar are absent extractors, not routing
  failures, and are not addressed here.
- Non-goal: making refusals visible on the CLI/REST/MCP surfaces. That is a
  separate parked defect with its own scope; this change reduces the number of
  invisible refusals but does not surface the remainder.
- Non-goal: content sniffing as the primary selector.

# Decisions

## The fallback lives at `extractor_for`, not `can_extract`

`extractor_for` becomes suffix-first, content-second. The alternative — leaving
it suffix-only and adding a second predicate for the pre-filter to call — was
rejected: `ingestion.py:217` and `ingestion.py:292` both already ask this one
question, and two predicates answering "can this be read" is two definitions that
can disagree. The router's own docstring states the principle ("One object, one
answer") and this project has already been bitten by a duplicated setting.

`supported_suffixes()` is unchanged and stays derived from the registry: it
answers what the registry *advertises*, which is still exactly the declared
suffixes. Content routing is a recovery path, not an advertised capability.

## Positive signatures only, and no text fallback

A signature must identify a format affirmatively. "Decodes as UTF-8" is not a
signature: admitting it would route a batch script, a detached signature and 29 calendar
files into the corpus as plain text, turning an honest refusal into a document an
analyst has to scroll past. That is the same argument the project already makes
for refusing text that is punctuation alone, and for an extractor earning its
place by precision rather than coverage.

OOXML and OLE2 both need a second step, because the outer container does not say
which format it holds:

- OOXML (`PK\x03\x04`): the archive's name list decides —
  `word/document.xml` → `.docx`, `xl/workbook.xml` → `.xlsx`,
  `ppt/presentation.xml` → `.pptx`, none of them → `.zip`.
- OLE2 (`\xd0\xcf\x11\xe0`): the directory's stream names decide, matched as
  UTF-16LE in the leading bytes — `WordDocument` → `.doc`, `Workbook` → `.xls`,
  `PowerPoint Document` → `.ppt`, `__substg1.0_` → `.msg`.

The OLE2 discrimination is a byte scan rather than a parse, deliberately: it adds
no dependency, and `olefile` is only present transitively under `extract-msg`.
The scan reads a bounded prefix, so a large file is not read whole to be
identified.

## The scratch copy carries the resolved suffix

`extract` asks how the extractor was chosen. Chosen by suffix, the file is passed
through unchanged — today's path exactly. Chosen by content, the file is copied
into a scratch directory as `<stem><resolved suffix>` and the delegate is given
the copy, so no extractor ever sees a suffix it cannot key on. The scratch
directory is removed in a `finally`, as `legacy_office` does.

The copy is a real cost on a large file, and it is accepted rather than optimised
away. A hardlink would avoid the bytes but fails across filesystems; a symlink
risks a delegate resolving the real path and reading the decorated suffix back.
The path is rare by construction — it runs only for a file the registry could not
name — and correctness there is worth more than the copy.

## What the document records

The media type is the delegate's, unmodified: it is what the evidence *is*. The
extractor string becomes `content-routed+<delegate>`, mirroring
`legacy-office+<delegate>`, so the disclosure sits where this project already
puts lineage and an analyst can find every content-routed document with one
query. `text_source`, `refusals` and `metadata` are carried through from the
delegate rather than defaulted — the same lesson `legacy_office.py:228-234`
records.

A file read as something other than its name is a disclosure, not a correction.
The filename on the document stays the name on disk, quotes included, because
that is what the operator has.

## Containers need no special case

Checked rather than assumed: `ZipExtractor.extract` hardcodes
`media_type="application/zip"` and its `iter_children` opens the path with
`zipfile` regardless of suffix, and `TarExtractor` keys its media type with
`.get(..., default)`. So a content-routed container both stores and expands
correctly, and `_expand` reaches it through the same `extractor_for` that found
it. No container-specific refusal is needed.

# Risks

- **The fix could be inert.** Mitigated by a test that drives a folder walk
  through `IngestionService`, not `FormatRouter` — the pre-filter is upstream of
  `extract`, so a router-only test would pass while the feature did nothing.
- **A signature could be wrong and mis-route a file.** Mitigated by requiring a
  positive signature, by discriminating OOXML and OLE2 rather than guessing, and
  by a test asserting that a file with a known suffix is never sniffed.
- **A wrongly-sniffed file fails one document, not the run.** The delegate is
  called inside the same `ExtractionError` discipline the rest of the pipeline
  uses; the scratch copy is what keeps a `KeyError` from escaping.
