## Context

See `proposal.md` § Why for motivation. Four properties of the code as it stands
shape everything below.

**The seam is duck typing, and it already fits.** An extractor is anything with
`name`, `suffixes`, `accepts()` and `extract()`; it becomes a *container* by
additionally exposing `iter_children(path) -> Iterator[Child]`, which the router
finds with `getattr` (`router.py:78`) and the pipeline with `hasattr`
(`services/ingestion.py:293`). There is no routing branch to edit and no base
class to subclass. Adding a format is a class plus one line in
`default_extractors()` (`extractors.py:333-345`).

**Laziness is a contract, not a style.** `Extraction` deliberately does not
carry children (`extractors.py:44-48`): "a container holding ten thousand
entries would otherwise be fully resident in memory before the expansion budget
— which lives a layer up, in the service — ever got a chance to refuse it." Any
reader that materialises an archive to a directory before yielding breaks that,
which rules out the whole-archive-extraction libraries.

**The budget is charged per child and enforced in exactly two places**
(`services/ingestion.py:295`, `:303`). Exhaustion raises nothing: the generator
is abandoned mid-iteration, a string lands in `refusals`, and what was already
stored stays stored. A reader must therefore tolerate being abandoned partway.

**Two availability policies already exist and disagree on purpose.** The
recognition engine is verified once at the start of every run and a failure is
fatal (`services/ingestion.py:183`). LibreOffice is not verified at all: it is
resolved per extraction and its absence fails one document
(`legacy_office.py:261-266`), because a host that ingests no legacy file must
not be stopped by a converter it will never use. Choosing between these is the
main decision here.

## Decisions

### The reader is libarchive, bound in-process, not a subprocess

Four candidates were measured on this Mac and inside a real `python:3.12-slim`
container before choosing. `python:3.12-slim` is Debian trixie with
`Components: main` only, which decides most of it:

| Option | RAR5 | Cost on trixie | Licence |
|---|---|---|---|
| `libarchive-c` + system `libarchive` | yes, incl. solid + all 4 filters | **2 packages, 902 kB, main** | CC0 / BSD-2 |
| `rarfile` + `unar` | yes, incl. multi-volume | **117 packages** (GNUstep runtime, libicu) | ISC / LGPL-2.1 |
| `rarfile` + `bsdtar` | **broken as shipped** | 3 packages | ISC / BSD-2 |
| `rarfile` + `unrar` or `7zip-rar` | yes | requires enabling **non-free** | unRAR licence |
| `patoolib` | yes | external binaries | **GPL-3** |
| `py7zr` | **no** — 7z only | — | — |

`libarchive-c` wins on every axis that matters and loses on one that does not.
It is the only option that gives lazy per-entry *and* per-byte streaming with no
subprocess, no temp files and no `PATH` dependency: `ArchiveRead.__iter__`
(`libarchive/read.py:19-31`) is a true generator over `archive_read_next_header2`,
and `ArchiveEntry.get_blocks()` (`entry.py:163-178`) "keep[s] only one chunk in
memory at a time". On macOS it needs nothing installed at all —
`/usr/lib/libarchive.dylib` is version 3.7.4 and reads RAR5 today.

The licence position is the reason this is not a close call. libarchive's RAR5
reader (`archive_read_support_format_rar5.c`) is an independent 2-clause-BSD
implementation by Grzegorz Antoniak containing no unRAR code, which is why it is
in Debian main. Every unRAR-derived decoder — `unrar`, `7zip-rar`, `p7zip-rar` —
is non-free, because the UnRAR licence forbids using its source to re-create the
compression algorithm. Reaching for one of those would mean enabling non-free in
the image of a public AGPL project to read one format.

`rarfile` + `bsdtar` looked like the cheap version of the same thing and was
rejected on measurement, not on taste: `ToolSetup.get_cmdline` appends `--`
after bsdtar's `-f` (`rarfile.py:3487`), so bsdtar treats `--` as the archive
name, and because `custom_popen` merges stderr into stdout that error text is
delivered *as file content*. It surfaces only as
`BadRarFile: Failed the read enough data: req=N got=51`. Upstream closed this in
2023 without diagnosis, and `rarfile`'s own `test_bsdtar_tool` cannot catch it
because both files in its fixture are zero bytes. Carrying a patched
`ToolSetup` subclass in this tree to read one format is a worse trade than one
CC0 binding.

**What is given up:** multi-volume archives, which are refused rather than read,
and random access by name — the reader is strictly forward-only. The second
costs nothing, because `iter_children` is already a forward-only generator; it
costs one thing, handled below.

"libarchive cannot read a volume set" was how this was first written, and it is
not what libarchive does. Measured on 3.8.9 against a first volume built to the
format: the volume flag in the main header, one entry flagged as continuing into
the next volume with half its declared bytes present, and an end-of-archive
block flagged "not the last". libarchive listed it cleanly as two entries,
raised nothing, and delivered ten of the split entry's twenty bytes as the
entry. So the refusal cannot be left to the reader, and it cannot be decided on
the filename either — that first volume was named `archive.rar`. It is decided
on the flags the format itself carries, which is the only signal present on
every volume of both generations.

### An absent library is the LibreOffice case, not the recognition engine's

An absent reader fails only the documents that need it, and is reported rather
than enforced. The argument is the one already in the tree: a host ingesting no
archive must not be stopped by a reader it will never call, and an operator
should find out from `jackryan status` rather than 26 files into an hour-long
run. `rar_status()` is defined once and read by both adapters, exactly as
`converter_status()` is, so the CLI and REST cannot drift into describing one
host with two words.

This is a *reported* capability, not a *fail-open* one, and the distinction
matters: an absent library produces a loud `ExtractionError` naming the remedy
on every archive it is asked to read. Nothing is silently skipped, and no
archive is ever stored as though it had been opened.

### The import is lazy, and its failure mode has to be converted

`import libarchive` on a host without the system library does **not** raise
`ImportError` or `OSError`. `find_library('archive')` returns `None`,
`LoadLibrary(None)` loads the main executable, and the first symbol lookup fails
with `AttributeError: python: undefined symbol: archive_version_number`. A
module-level import would therefore crash `jackryan status` — the command an
operator runs to find out whether the capability is available — with an error
naming neither the cause nor the remedy.

So the import happens inside the functions that need it, and any exception from
loading or probing becomes `ExtractionError` naming `libarchive`. The probe is
`libarchive.ffi.version_number()` rather than a bare import, because the import
is what succeeds misleadingly.

### An encrypted archive fails the document; it never reads as empty

`rarfile`, the reader not chosen, gets this wrong in a way that would have been
invisible: it opens a header-encrypted archive *successfully*, reports
`needs_password() == True`, and returns an **empty** `namelist()`. Through this
pipeline that would have produced a stored container document with zero children
and no error — indistinguishable from an empty archive, and a false statement
about evidence.

libarchive does better, but not well enough to be trusted with the question on
its own, and the shape of what it answers is what the two checks are built
around. Measured on both 3.7.4 and 3.8.9, on fixtures built in the test module:

| archive | `archive_entry_is_data_encrypted` | reading the entry |
|---|---|---|
| RAR3, header-encrypted (`MHD_PASSWORD`) | n/a | raises "RAR encryption support unavailable" |
| RAR3, data-encrypted (`FHD_PASSWORD`) | `1` on both versions | **delivers ciphertext, silently** |
| RAR5, header-encrypted (`HEAD_CRYPT`) | n/a | raises |
| RAR5, data-encrypted (`EX_CRYPT`) | `0` on 3.7.4, `1` on 3.8.9 | 3.7.4 delivers ciphertext; 3.8.9 raises |

Two rows deliver ciphertext, and no one check covers both. The per-entry flag is
the authority for RAR3 and is asked of every entry in both passes; the pre-open
header walk is what covers RAR5 on the version Debian trixie still ships, and it
covers RAR3's header mode as well so that all four rows reach one sentence an
analyst can act on. Neither can be dropped in favour of the other, and both are
positive detection only — a walk may add a refusal and must never be the reason
a readable archive is rejected.

`extract()` therefore raises `ExtractionError` on an unreadable archive, which
`_ingest_work` turns into a failed document carrying the reason
(`services/ingestion.py:426-436`). A failed document is counted and reported;
this is the same reasoning that refuses text consisting only of punctuation
rather than storing it as empty.

### One guard, called by both passes

The two passes open the archive separately, so each must decide separately
whether it may — and deciding separately is how they came to disagree.
`extract()` refused an encrypted archive; `iter_children()` repeated neither
that refusal nor the volume one while its comment claimed parity, so an archive
expanded without its listing pass still yielded ciphertext, and a volume still
yielded a truncated entry as though it were whole. Nothing in the types makes
the pipeline's ordering hold. Both now call one function, and the per-entry
encryption verdict is one call in both loops.

### A truncated archive is not an empty one

libarchive's RAR5 reader answers an unparseable or truncated header with
end-of-archive rather than an error. Measured: a signature alone, a signature
plus four bytes, an archive cut inside its first file header, and a 24-byte file
whose header-size vint is ten bytes long all returned zero entries and raised
nothing — stored as ingested containers with no children, indistinguishable from
an archive that was genuinely empty. An archive cut inside its *second* entry's
header was worse: stored as complete, with only the first entry.

The header walk already sees every block boundary, so it answers this too — but
from arithmetic rather than from interpretation, which is the opposite stance to
the one it takes on encryption. A block declaring more bytes than the file holds,
or a file carrying no main header, is a fact about declared sizes against
`st_size`; nothing is inferred. The walk stops at the end-of-archive block, so a
`.rar` carrying appended bytes is still read.

### `extract()` and `iter_children()` each open the archive

The reader is forward-only, and the pipeline calls `extract()` first (for the
container's own listing text) and `iter_children()` later, on the next queue
pass. They cannot share a cursor, so each opens its own `file_reader`. The
listing pass reads headers only and touches no entry data, so the cost is a
header scan — measured at well under a second across all 26 archives.

### A declared size is over-read by one byte

`ZipExtractor` reads `MAX_ENTRY_BYTES + 1` and drops the entry if it got more
than the bound, with the reason at the site: "a declared size can lie, and this
is how an over-large member is caught rather than trusted"
(`containers.py:99-105`). The same applies to a RAR header, so the streaming
loop stops accumulating once it passes the bound rather than trusting
`entry.size`. Checking `entry.size` alone would make the ceiling advisory.

### The path guard is shared, not reimplemented

`_unsafe_reason` already refuses absolute paths, parent traversal and
drive-relative paths, and `document-ingestion`'s spec requires those rules to
hold "for an entry inside a container as strictly as for a file on disk". The
RAR extractor calls the same function. Writing a second copy would be a second
definition of the rule — the failure the service-layer convention exists to
prevent. Measured against the real archives, none of the 406 entries trips it;
that is the reason to share the guard rather than to skip it.

### What is deliberately not touched

The published scenario "An oversized entry inside a container is refused"
(`document-ingestion/spec.md:141`) has no test, and the existing ZIP and tar
paths drop such an entry with a bare `continue` and no refusal string. That is a
real gap, it predates this change, and fixing it would change ZIP and tar
behaviour under a proposal about RAR. It is recorded in
`docs/implementation-notes.md` instead. The RAR path matches the existing
behaviour rather than inventing a third one.
