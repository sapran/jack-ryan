## Why

The dump this workbench was built against holds 1922 files. After the legacy
Office slice it stores 1760 of them; 98 fail with a reason, and 64 are refused
by routing because no extractor accepts them. Twenty-six of those 64 are `.rar`.

They are not a marginal tail. Measured with libarchive before any code was
written, the 26 archives hold **406 files, 272 MB uncompressed**: 83 PDF, 55
DOCX, 19 XLSX, 11 DOC, 4 PPTX and 2 TXT — **174 documents in formats this
pipeline already reads** — plus 187 images the recognition ladder handles and 45
`.db` files nothing reads. So the archives are not full of some exotic format
awaiting a new reader. They are full of exactly the institutional formats the
rest of the dump is made of, and the only reason none of it is searchable is
that the wrapper around it is unopened.

Worse than absent is absent and quiet. A routing refusal is recorded in
`IngestReport.refusals` and printed by no surface, so the 26 archives produced
no line in the ingest report — a defect established and parked separately. The
consequence for an analyst is the most damaging answer this tool can give: a
`case_search` that finds nothing reads as "the casefile does not mention that",
when the passage may be sitting inside an archive that was never opened.

This is the fifth slice of **M3** and pulls nothing forward. Hard formats and
container recursion were deferred behind the prototype (`docs/design.md` § 10);
the prototype shipped, and `docs/design.md` § 5 already names the container set
as "(ZIP, mailboxes, PST)". RAR was never in that set — this is a genuine design
gap in a capability that already exists, not a new capability.

## What Changes

**Current behaviour.** `.rar` is in no extractor's suffix map.
`FormatRouter.extractor_for` returns `None`, and the ingest loop drops the file.
Because a folder walk marks what it found itself as not named directly, the
refusal is recorded but never surfaced.

**Desired behaviour.** `.rar` is a container like `.zip`: expanded through the
same router, bounded by the same budget, guarded by the same path rules.

- **RAR is read by libarchive**, through `libarchive-c`. Entries are iterated one
  at a time and each entry's bytes are streamed a block at a time, so no archive
  is ever wholly resident and the expansion budget can still refuse one partway.
- **A container extractor still knows nothing about what it holds.** The 174
  readable documents inside are read by the extractors that already own their
  suffixes, and the 45 `.db` entries are refused individually — which is what
  makes a format supported inside an archive exactly when it is supported
  outside one.
- **An encrypted archive fails that document, naming encryption.** One of the 26
  is header-encrypted. It must not present as an empty archive: "this archive
  holds nothing" and "this archive could not be opened" are different claims,
  and only one of them is true. This holds for both generations of the format
  and both of WinRAR's password modes, and for the expansion pass as well as
  the listing pass — libarchive delivers a data-encrypted RAR3 entry as
  ciphertext without an error, which is worse than the empty container it would
  otherwise be mistaken for, because nothing downstream can detect it.
- **An archive that cannot be accounted for fails rather than reading as
  empty.** The RAR5 reader answers a truncated header with end-of-archive, so a
  cut archive arrives as zero entries and no exception. An archive that opens
  and genuinely holds nothing is still stored as a container with no children;
  that is the claim being protected.
- **An absent library fails only the RAR documents**, with a message naming the
  remedy, and the capability is reported on `jackryan status` and `GET /health`
  in one vocabulary on both. This follows the LibreOffice precedent rather than
  the recognition engine's: a host that ingests no archive must not be stopped
  by a reader it will never call.

**Not in this slice.** `.ics` (29 files in that dump) and the five files whose
names end in an apostrophe are in the unsupported tail and stay there — the
first is a different format family, the second a filename-routing defect already
parked. Multi-volume RAR is not supported and the dump contains none; a volume
is refused on the flag its own header carries — not on its name, and not by
leaving it to libarchive, which lists a first volume as a whole archive and
delivers a split entry's first fragment as the entry. The invisibility of
`refusals` on all three surfaces is a separate parked defect and is not fixed
here; this change is verified against the store directly, not against the report.

## Capabilities

### Modified Capabilities

- `container-extraction`: RAR joins the container set, read by a library rather
  than a subprocess, with the rules for an encrypted archive and for an absent
  reader.

## Impact

- `src/jackryan/ingestion/containers.py` — new `RarExtractor` beside
  `ZipExtractor`, and the reader lookup and status function.
- `src/jackryan/ingestion/extractors.py` — one lazy import and one registry
  entry in `default_extractors`.
- `src/jackryan/cli.py`, `src/jackryan/server.py` — a `rar` key on the two
  capability payloads, from one shared function.
- `Dockerfile` — `libarchive13t64`, and a re-measured image size.
- `pyproject.toml` — **one new Python dependency**, `libarchive-c`.
- Dependencies and licence: `libarchive-c` is **CC0-1.0**; the system
  `libarchive` it binds is **BSD-2-clause**, and its RAR5 reader is an
  independent clean-room implementation carrying no unRAR code — which is
  precisely why it ships in Debian **main** while every unRAR-derived decoder
  sits in non-free. Neither disturbs this project's AGPL-3.0-or-later position.
  The rejected alternatives are recorded in `design.md`; both would have cost
  either a non-free package or 117 apt packages.
