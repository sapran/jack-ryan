"""Extractors for files that hold other files.

A container extractor reads its entries and nothing more. It does not route
them, does not extract them, and does not know what formats exist — the
pipeline does that, which is what makes a format supported inside an archive
exactly when it is supported outside one.

Entries are yielded one at a time. A container is untrusted input: its entry
count, its entry names, and its declared sizes are all chosen by whoever built
it, so nothing here reads an archive whole or trusts a name.
"""

from __future__ import annotations

import ctypes
import tarfile
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from .extractors import Child, Extraction, ExtractionError

# The literal an operator sees when no archive reader resolves, imported rather
# than restated. Two modules holding the same string is how two adapters end up
# describing one host in two words — the failure the converter's comment argues
# against, which a second copy of its literal would have reintroduced. The
# direction is deliberate: the converter established this vocabulary first, and
# an archive reader borrowing it is cheaper than a third module existing to hold
# one word.
from .legacy_office import UNAVAILABLE as RAR_UNAVAILABLE

# An entry larger than this is refused before it is read. The aggregate budget
# lives in the ingestion service; this is the per-entry floor beneath it, and it
# is what stops one declared-enormous member being read into memory at all.
MAX_ENTRY_BYTES = 512 * 1024 * 1024
# The oldest libarchive whose RAR5 reader this code will hand an archive to.
#
# 3.8.9 is the floor because 3.7.4 carries CVE-2026-14164, a double free in the
# RAR5 reader: `filtered_buf` is left stale when the unpacking state is
# reinitialised and is freed a second time when the next entry is processed.
# That is precisely the loop this extractor drives — the listing pass walks
# every entry, then `iter_children` walks every entry again and reads its
# blocks — and the input is an archive a third party handed the analyst.
#
# It is a floor rather than a warning because the failure is not catchable. A
# glibc double free raises `SIGABRT`, which no `except` sees, and ingestion runs
# in a thread pool inside the API server process, so one crafted archive would
# take the server down with it. Debian marks trixie's 3.7.4 vulnerable with no
# security update planned, so an unpinned `apt-get upgrade` never resolves it.
#
# The consequence is deliberate: on a host below the floor, RAR reading is
# unavailable and says so, and every other format still ingests. A quietly
# vulnerable parser is worse than an absent one, because only one of the two
# tells the operator.
MIN_LIBARCHIVE = 3_008_009


def _resolve_reader() -> tuple[object | None, str | None, str | None]:
    """The libarchive binding, the version it reports, and why it may not be used.

    One probe with two callers whose jobs differ: `rar_status` tells an operator
    what this host offers, and `_libarchive` refuses an extraction. Those were
    two implementations of the same import-probe-and-compare, agreeing only by
    construction — so the status a surface reported and the decision an
    extraction made were two definitions of one fact, and raising the floor in
    one of them would have had `jackryan status` advertise a reader that every
    ingest then declined.

    Imported here rather than at module scope, and probed rather than merely
    imported, because the failure mode is misleading twice over. On a host with
    no system libarchive, `find_library` returns None, `LoadLibrary(None)` loads
    the running executable quite happily, and the first symbol lookup fails with
    `AttributeError: undefined symbol: archive_version_number` — not
    `ImportError`, not `OSError`. A module-level import would therefore take
    down `jackryan status`, which is the command an operator runs to find out
    whether this capability is available.

    Called per extraction rather than cached, for the same reason the converter
    is: an operator who installs the library under a long-running server should
    not have to restart it to be believed.
    """
    try:
        import libarchive
        import libarchive.ffi

        version = libarchive.ffi.version_number()
    except ImportError as exc:
        # A different remedy, so a different message. Telling an operator to
        # install a system library when the Python package is what is missing
        # sends them after the wrong thing.
        return None, None, (
            "reading a rar archive needs the libarchive-c package, which is not "
            f"installed ({exc}); reinstall the project's dependencies"
        )
    except Exception as exc:  # noqa: BLE001 - see above; the type is not knowable
        return None, None, (
            "reading a rar archive needs libarchive, which is unavailable "
            f"({exc}); install the system libarchive library"
        )
    if version < MIN_LIBARCHIVE:
        # Named exactly, with the remedy, because this is the one refusal an
        # operator will want to argue with: the library is present and the
        # archive is readable, and we are declining anyway.
        return None, None, (
            f"reading a rar archive needs libarchive {_version_text(MIN_LIBARCHIVE)} "
            f"or newer; this host has {_version_text(version)}, whose RAR5 reader "
            "carries a double-free (CVE-2026-14164) reachable by a crafted archive "
            "and not catchable in process. Install a newer libarchive, or point "
            "the LIBARCHIVE environment variable at one"
        )
    return libarchive, _version_text(version), None


def find_rar_reader() -> str | None:
    """The libarchive version this host offers, or None.

    Written the way it is written down — `3.8.9`, not the packed `3008009` the
    library reports — because the refusal message an operator reads next
    formats the same number that way, and one host described by two spellings of
    one version reads as two different facts.
    """
    return _resolve_reader()[1]


def rar_status() -> str:
    """What the operator-facing surfaces report: the libarchive version, or `unavailable`.

    A host below `MIN_LIBARCHIVE` reports `unavailable`, exactly as one with no
    library at all does. An operator does not need to know which of the two it
    is to know that archives will not be read; `jackryan ingest` says which,
    because that is where the remedy belongs.
    """
    return find_rar_reader() or RAR_UNAVAILABLE


def _unsafe_reason(name: str) -> str | None:
    """Why this entry name may not be written, or None if it may.

    Refusing is the spec'd behaviour and is reported. It is not the only
    defence: the pipeline materialises entries under generated names, so a name
    that slipped through here still could not choose its own location on disk.
    """
    if not name or name.endswith("/"):
        return None  # a directory entry, skipped rather than refused
    pure = Path(name)
    if pure.is_absolute() or name.startswith("/") or name.startswith("\\"):
        return "absolute path"
    if ".." in pure.parts:
        return "parent traversal"
    if ":" in name.split("/")[0] and len(name.split("/")[0]) == 2:
        return "drive-relative path"
    return None


class ZipExtractor:
    """ZIP archives."""

    name = "zip"
    suffixes = {".zip": "application/zip"}

    def accepts(self, path: Path) -> bool:
        return path.suffix.lower() in self.suffixes

    def extract(self, path: Path) -> Extraction:
        refusals: list[str] = []
        try:
            with zipfile.ZipFile(path) as archive:
                entries = archive.infolist()
        except (zipfile.BadZipFile, OSError) as exc:
            raise ExtractionError(f"could not read {path.name} as a zip: {exc}") from exc

        listing = []
        for info in entries:
            if info.is_dir():
                continue
            reason = _unsafe_reason(info.filename)
            if reason is not None:
                refusals.append(f"{info.filename}: {reason}")
                continue
            if _is_zip_symlink(info):
                refusals.append(f"{info.filename}: symbolic link")
                continue
            listing.append(info.filename)

        # The container's own text is its listing: an archive an analyst reads
        # tells them what is inside it, and that is worth having searchable.
        text = "\n".join(listing)
        return Extraction(
            text=text,
            media_type="application/zip",
            extractor=self.name,
            metadata={"entries": str(len(listing))},
            is_container=True,
            refusals=tuple(refusals),
        )

    def iter_children(self, path: Path) -> Iterator[Child]:
        with zipfile.ZipFile(path) as archive:
            for info in archive.infolist():
                if info.is_dir() or _unsafe_reason(info.filename) is not None:
                    continue
                if _is_zip_symlink(info):
                    continue
                if info.file_size > MAX_ENTRY_BYTES:
                    continue
                with archive.open(info) as handle:
                    # Read one byte past the bound: a declared size can lie, and
                    # this is how an over-large member is caught rather than
                    # trusted.
                    data = handle.read(MAX_ENTRY_BYTES + 1)
                if len(data) > MAX_ENTRY_BYTES:
                    continue
                yield Child(name=info.filename, data=data)


def _is_zip_symlink(info: zipfile.ZipInfo) -> bool:
    """Whether a zip entry carries unix symlink mode in its external attributes."""
    if info.create_system != 3:  # not unix-created; no mode bits to read
        return False
    return (info.external_attr >> 16) & 0o170000 == 0o120000


class RarExtractor:
    """RAR archives, read through libarchive.

    The reader is a library bound in process rather than an archiver invoked as
    a subprocess, and that is a constraint rather than a preference. Every
    subprocess RAR reader available either derives from RARLAB's unRAR source —
    which puts it in non-free — or extracts whole archives to a directory, and
    the second would put an archive's full expansion on disk before the byte
    budget could refuse any of it, leaving the ceiling unreachable in exactly
    the case it exists for. libarchive's RAR5 reader is an independent
    BSD-licensed implementation, which is why it ships where the others do not.

    The cursor is forward-only, so `extract` and `iter_children` each open the
    archive. They cannot share one: the pipeline calls `extract` for the
    container's own listing and `iter_children` on a later pass, and rewinding
    is not offered. The listing pass reads headers only and touches no entry
    data.

    Both passes begin with `_refuse_before_opening`, from that one function
    rather than each restating the tests. Nothing in the types makes the
    pipeline's ordering hold, so a pass that trusted the other to have refused
    already is a pass with no guard at all — which is precisely how an
    encrypted archive expanded directly still handed back its ciphertext.
    """

    name = "rar"
    suffixes = {".rar": "application/vnd.rar"}

    def accepts(self, path: Path) -> bool:
        return path.suffix.lower() in self.suffixes

    def extract(self, path: Path) -> Extraction:
        reader = _libarchive()
        fmt = _rar_format(path)
        _refuse_before_opening(path, fmt)
        refusals: list[str] = []
        listing: list[str] = []
        try:
            with reader.file_reader(str(path), format_name=fmt) as archive:
                for entry in archive:
                    if entry.isdir:
                        continue  # no bytes, so no content identity
                    # libarchive's own verdict, asked of every entry in both
                    # passes. It is the authority the header walk cannot be —
                    # see `_entry_data_encrypted` — and one encrypted entry
                    # refuses the whole archive rather than being reported as a
                    # refused entry, so that this and the pre-open walk cannot
                    # reach two different outcomes on one archive.
                    if _entry_data_encrypted(reader, entry):
                        raise _encrypted_error(path, "libarchive reports encrypted entries")
                    name = _entry_name(entry)
                    reason = _not_a_file_reason(entry) or _unsafe_reason(name)
                    if reason is not None:
                        refusals.append(f"{name}: {reason}")
                        continue
                    listing.append(name)
        except ExtractionError:
            # This loop's own refusal, re-raised with its own message and remedy
            # rather than re-wrapped as "could not read". The split holds by
            # type, so reordering these two clauses cannot turn a named refusal
            # into an anonymous one.
            raise
        except Exception as exc:  # noqa: BLE001 - libarchive raises its own hierarchy
            # An archive that cannot be opened fails as a document. It is never
            # stored as a container with no children: "holds nothing" and "could
            # not be opened" are different claims about evidence, and a container
            # with zero children is indistinguishable from a genuinely empty one.
            # The encrypted archive is the case this exists for.
            raise ExtractionError(f"could not read {path.name} as a rar: {exc}") from exc

        # The container's own text is its listing, exactly as for a zip: an
        # archive an analyst reads tells them what is inside it.
        return Extraction(
            text="\n".join(listing),
            media_type=self.suffixes[".rar"],
            extractor=self.name,
            metadata={"entries": str(len(listing))},
            is_container=True,
            refusals=tuple(refusals),
        )

    def iter_children(self, path: Path) -> Iterator[Child]:
        reader = _libarchive()
        fmt = _rar_format(path)
        _refuse_before_opening(path, fmt)
        with reader.file_reader(str(path), format_name=fmt) as archive:
            for entry in archive:
                if entry.isdir:
                    continue
                if _entry_data_encrypted(reader, entry):
                    raise _encrypted_error(path, "libarchive reports encrypted entries")
                name = _entry_name(entry)
                # The same tests as the listing pass, in the same order and from
                # the same functions, so the two cannot disagree about what an
                # entry is or about whether the archive may be read at all.
                if _not_a_file_reason(entry) is not None or _unsafe_reason(name) is not None:
                    continue
                # Accumulated a block at a time and stopped one block past the
                # bound, never trusted from `entry.size`: a declared size is
                # chosen by whoever built the archive, and checking it alone
                # would make the ceiling advisory. The blocks are consumed
                # before the cursor advances, which is why this reads here
                # rather than yielding a lazy handle — and abandoning one
                # part-read is safe, because libarchive skips any unconsumed
                # remainder when it advances to the next header.
                blocks: list[bytes] = []
                size = 0
                for block in entry.get_blocks():
                    blocks.append(block)
                    size += len(block)
                    if size > MAX_ENTRY_BYTES:
                        break
                if size > MAX_ENTRY_BYTES:
                    continue
                # Joined at the end rather than grown in place. That costs about
                # twice the entry's size for the duration of the join, and there
                # is no shape that avoids it: a `bytearray` grown by `extend`
                # pays the same at the end, because `Child.data` is `bytes` and
                # the conversion copies, and pays reallocation copying on the
                # way as well. Reading into one buffer sized up front would
                # avoid both, and the only size available up front is the one
                # the archive declares, which is exactly the number this loop
                # exists to distrust. So `MAX_ENTRY_BYTES` bounds roughly half
                # the peak, not all of it.
                #
                # What the reset does buy is that the doubling is momentary. The
                # generator is suspended at the `yield` for as long as the
                # pipeline takes to extract, chunk and embed that child, and
                # holding the block list through all of it would keep a second
                # copy of a half-gigabyte entry alive for the whole of it.
                data = b"".join(blocks)
                blocks = []
                yield Child(name=name, data=data)


def _entry_name(entry) -> str:  # noqa: ANN001 - libarchive's own type
    """The entry's name as text, whatever encoding the archive used.

    `libarchive-c` hands back `bytes` when a stored name is not valid UTF-8,
    keeping the raw bytes rather than guessing. `str()` on that yields the
    Python *repr* — `b'\\xe4\\xee...\\xf2.pdf'` — whose suffix is `.pdf'` with a
    trailing quote, which matches no extractor. The child is then refused as
    unroutable and the container's listing carries a repr as searchable text.

    This is not a hypothetical for this corpus: a RAR3 archive written on
    Windows with Cyrillic names and no Unicode flag is exactly that shape, and
    it is the same class of defect as the filename-ending-in-a-quote routing bug
    already parked. `replace` rather than `surrogateescape`, because the result
    is stored in SQLite and a surrogate would fail to encode there.
    """
    raw = entry.pathname
    if isinstance(raw, bytes):
        return raw.decode("utf-8", errors="replace")
    return str(raw)


def _libarchive():  # noqa: ANN202 - the module type is not importable when absent
    """The libarchive binding, or an `ExtractionError` naming the remedy.

    Absence fails the documents that need it and nothing else, and is reported
    by `rar_status` before a run starts. It is deliberately not verified at the
    start of an ingest, unlike the recognition engine: every page-bearing
    document needs that engine, whereas a host ingesting no archive must not be
    stopped by a reader it will never call.

    The reason is composed by `_resolve_reader`, which is also what `rar_status`
    reads, so what an operator is told and what an extraction decides come from
    one comparison against one floor.
    """
    module, _, reason = _resolve_reader()
    if module is None:
        raise ExtractionError(reason)
    return module


@lru_cache(maxsize=1)
def _data_encrypted_probe(ffi):  # noqa: ANN001,ANN202 - libarchive's own module
    """`archive_entry_is_data_encrypted`, declared because nothing wraps it.

    `libarchive-c` binds neither this symbol nor `archive_entry_is_metadata_encrypted`,
    so the argument and return types are declared here. That mutates a function
    pointer the CDLL caches and hands to everyone, which is why it is done once
    and the result kept: nothing else in this process uses the symbol, and two
    callers declaring it differently would be a genuine hazard.
    """
    probe = ffi.libarchive.archive_entry_is_data_encrypted
    probe.restype = ctypes.c_int
    probe.argtypes = [ctypes.c_void_p]
    return probe


def _entry_data_encrypted(reader, entry) -> bool:  # noqa: ANN001 - libarchive's own types
    """Whether libarchive says this entry's data is encrypted.

    The header walk cannot be the only check, and a RAR 2.9/3.x archive is what
    proved it: `FHD_PASSWORD` lives in a RAR3 file header, the walk that read
    headers understood only RAR5 blocks, and it was reached only for RAR5 — so
    nothing examined such an archive at all. libarchive then set this flag, said
    nothing, and delivered raw ciphertext through `read_data`, which was stored
    as the document's text.

    Measured on both libraries in scope, on fixtures built in the test module.
    For RAR3 the flag is 1 on 3.7.4 and on 3.8.9, so this is the reliable answer
    for that generation. For RAR5 it is 1 only from 3.8.9; on 3.7.4 the reader
    skips the per-entry crypt record as an unsupported attribute and answers 0.
    That is why both checks exist and why neither can be dropped in favour of
    the other — the walk covers the version this reader may still be pointed at,
    and this covers the generation the walk's format does not describe.

    Any failure answers False rather than raising: this may add a refusal and
    must never be the reason a readable archive is rejected, which is the same
    stance the walk takes. `entry._entry_p` is `libarchive-c`'s private handle
    to the C struct; there is no public accessor, and the alternative is not
    asking libarchive at all.
    """
    try:
        return _data_encrypted_probe(reader.ffi)(entry._entry_p) == 1
    except Exception:  # noqa: BLE001 - a missing symbol or a changed binding; see above
        return False


def _version_text(number: int) -> str:
    """libarchive's packed version number as it is written down."""
    return f"{number // 1_000_000}.{number // 1_000 % 1_000}.{number % 1_000}"


def _encrypted_error(path: Path, reason: str) -> ExtractionError:
    """The one message for every way an archive turns out to be locked.

    Header encryption, data-only encryption, RAR3 and RAR5, the pre-open walk
    and libarchive's own per-entry verdict all arrive here. Four detections and
    one sentence: an analyst holding a password-protected archive needs the same
    remedy whichever mode WinRAR wrote it in, and the mode is a detail carried
    in the parenthesis for whoever is debugging.
    """
    return ExtractionError(
        f"{path.name} is encrypted ({reason}); it cannot be read "
        "without its password — supply the decrypted archive"
    )


def _volume_error(path: Path, reason: str) -> ExtractionError:
    """Refused before opening rather than after failing.

    libarchive reads the first volume's entries and only then raises — and on a
    first volume that ends with a well-formed end-of-archive block it does not
    raise at all, listing the volume as a whole archive and delivering a split
    entry's first fragment as the entry. Its own message when it does raise
    ("Too small block encountered") names neither the cause nor a remedy.
    """
    return ExtractionError(
        f"{path.name} is one volume of a multi-volume archive ({reason}), which "
        "cannot be read; join the volumes and ingest the result"
    )


def _unreadable_error(path: Path, reason: str) -> ExtractionError:
    """An archive whose own headers do not account for the file it is in.

    Worded like the failure libarchive would have produced, because that is what
    it stands in for: the RAR5 reader answers an unparseable or truncated header
    with end-of-archive rather than an error, so a cut file lists zero entries
    and raises nothing, and "zero entries" is what a genuinely empty archive
    looks like too. Storing the second as the first is the falsehood the spec's
    second requirement forbids.
    """
    return ExtractionError(f"could not read {path.name} as a rar: {reason}")


def _not_a_file_reason(entry) -> str | None:  # noqa: ANN001 - libarchive's own type
    """Why this entry is not a regular file, or None if it is.

    `entry.isreg` alone is not the test, and this was found by a security review
    rather than by reading the format. RAR5 carries redirections in a file
    header's extra area, and libarchive's RAR5 reader sets `AE_IFREG` on a
    **hardlink** unconditionally — so a hardlink entry arrives with
    `isreg=True`, `islnk=True` and an attacker-chosen `linkpath` such as
    `../../etc/passwd`, and an `isreg` test admits it as a zero-byte file. A
    symlink arrives as `AE_IFLNK` and is excluded by `isreg`, but silently,
    where `TarExtractor` reports the same thing as a refusal.

    The tar reader behaves differently here, which is why a test built on a tar
    fixture proves nothing about this: it promotes a hardlink to `AE_IFREG` only
    when the entry has a non-zero size.

    Nothing downstream would follow such a link — `_expand` writes the child's
    bytes under a generated name and never creates a link — so the consequence
    was a phantom empty document rather than a traversal. It is still an entry
    reported as a file when the archive says it is a pointer, and the corpus
    should say so.
    """
    if entry.issym or entry.islnk:
        return "not a regular file"
    if not entry.isreg:
        return "not a regular file"
    return None


_RAR5_SIGNATURE = b"Rar!\x1a\x07\x01\x00"
_RAR3_SIGNATURE = b"Rar!\x1a\x07\x00"
# The two RAR generations, and the libarchive reader each needs. RAR5's
# signature extends RAR3's, so the longer one is tested first.
_RAR_MAGIC = ((_RAR5_SIGNATURE, "rar5"), (_RAR3_SIGNATURE, "rar"))


def _rar_format(path: Path) -> str:
    """Which libarchive reader this file needs, decided on its signature.

    Naming the format is not a micro-optimisation, it is the correctness of the
    stored media type. `file_reader` defaults to `format_name="all"`, which makes
    libarchive try every format it knows — so a ZIP or a tar named `.rar` is read
    quite happily by this extractor and stored asserting `application/vnd.rar`.
    That is a false statement about evidence, and it also routes a ZIP around
    `ZipExtractor`, whose symlink refusal and rendering this extractor does not
    reproduce. One corpus would then hold two renderings of the same kind of
    archive, which surfaces as retrieval quality rather than as an error.

    So the file is handled on what it is rather than on what it is named, and a
    file that is neither generation is refused naming what was expected — the
    same rule, for the same reason, as the legacy Office formats.
    """
    with path.open("rb") as handle:
        head = handle.read(8)
    for magic, fmt in _RAR_MAGIC:
        if head.startswith(magic):
            return fmt
    raise ExtractionError(
        f"{path.name} is not a RAR archive: expected a RAR signature, found "
        f"{head[:8]!r}"
    )


# What the walks below establish, and the three stances they establish it with.
#
# `encrypted` and `volume` are positive detection only: any byte a walk does not
# understand leaves them None and hands the file to libarchive. A hand-written
# parser that guessed wrong would refuse real evidence, so a walk may add a
# refusal and must never be the reason a readable archive is rejected.
#
# `unreadable` is the opposite claim and needs the opposite discipline, so it is
# made only from arithmetic: a block declaring more bytes than the file holds, a
# header that cannot be read at all, or a file carrying no main archive header.
# It exists because libarchive's RAR5 reader answers a truncated or unparseable
# header with end-of-archive rather than an error, so a cut archive lists zero
# entries and raises nothing — indistinguishable, downstream, from an archive
# that was genuinely empty.
#
# They are three fields rather than one reason because they are answered
# independently and reported in a fixed order: encryption first, since it is the
# most useful thing to tell an analyst holding the file; then the volume, which
# has a remedy; then unreadability, which has none.
@dataclass(frozen=True)
class _Survey:
    encrypted: str | None = None
    volume: str | None = None
    unreadable: str | None = None


# The reasons a walk reports. Fixed strings rather than composed ones, so the
# same condition reads the same way whichever generation found it.
_CUT = "a header or entry declares more bytes than the file contains"
_MALFORMED = "its block headers could not be read"
_NO_MAIN = "it carries no main archive header"
_HEADER_ENCRYPTED = "the archive header is encrypted"
_ENTRIES_ENCRYPTED = "its entries are encrypted"
_MAIN_VOLUME_FLAG = "its main header carries the volume flag"
_ENTRY_SPLIT = "an entry's data continues in another volume"

# At most this many headers are walked, which is what bounds a hostile file: a
# block chain can be made to loop back on itself, and every other guard here is
# arithmetic on declared sizes rather than a step count.
_MAX_HEADERS = 4096

# RAR5 block and record types, and the header flags each walk reads.
_RAR5_HEAD_MAIN = 1
_RAR5_HEAD_FILE = 2
_RAR5_HEAD_ENDARC = 5
_RAR5_HEAD_CRYPT = 4
_RAR5_EXTRA_CRYPT = 1
_RAR5_HAS_EXTRA = 0x0001
_RAR5_HAS_DATA = 0x0002
# An entry whose data began in the previous volume, or continues in the next.
_RAR5_SPLIT_BEFORE = 0x0008
_RAR5_SPLIT_AFTER = 0x0010
# In the main header's own archive-flags field: this archive is part of a set.
_RAR5_ARCHIVE_VOLUME = 0x0001
# One header is read at a time into a window this big. A fixed prefix read
# cannot work: an entry's data sits between headers, so a first entry larger
# than the prefix would push every later header out of view and a crypt record
# behind it would be missed. The walk therefore seeks past each data area.
_RAR5_HEADER_WINDOW = 64 * 1024

# RAR3 block types and header flags. The 7-byte base header is generic across
# every block type — CRC, type, flags, size — and a block carrying data declares
# it in a 4-byte ADD_SIZE immediately after, so this walk never has to know a
# body's layout. That is why it can read both signals it needs from flags alone.
_RAR3_HEAD_MAIN = 0x73
_RAR3_HEAD_FILE = 0x74
_RAR3_HEAD_ENDARC = 0x7B
_RAR3_BASE_HEADER = 7
_RAR3_LONG_BLOCK = 0x8000
_RAR3_MAIN_VOLUME = 0x0001
_RAR3_MAIN_PASSWORD = 0x0080
_RAR3_FILE_SPLIT_BEFORE = 0x0001
_RAR3_FILE_SPLIT_AFTER = 0x0002
_RAR3_FILE_PASSWORD = 0x0004
# 64-bit sizes: the high half of PACK_SIZE lives in the body, so ADD_SIZE alone
# understates the data area and the walk would seek short. It stops instead.
_RAR3_FILE_LARGE = 0x0100


def _vint(blob: bytes, pos: int) -> tuple[int, int]:
    """RAR5's variable-length integer: seven bits a byte, high bit continues."""
    value = shift = 0
    while pos < len(blob):
        byte = blob[pos]
        value |= (byte & 0x7F) << shift
        pos += 1
        if not byte & 0x80:
            return value, pos
        shift += 7
        if shift > 63:
            raise ValueError("vint too long")
    raise ValueError("truncated vint")


def _refuse_before_opening(path: Path, fmt: str) -> None:
    """Raise unless this file may be handed to libarchive at all.

    The single place both passes ask the question. It was two places — a name
    test and a RAR5-only encryption scan in `extract`, and nothing whatever in
    `iter_children` — and the two disagreeing is not a hypothetical: an
    encrypted archive expanded without its listing pass first yielded its
    ciphertext, because the pass that refused was not the pass that read.
    """
    survey = _survey(path, fmt)
    if survey.encrypted is not None:
        raise _encrypted_error(path, survey.encrypted)
    if survey.volume is not None:
        raise _volume_error(path, survey.volume)
    if survey.unreadable is not None:
        raise _unreadable_error(path, survey.unreadable)


def _survey(path: Path, fmt: str) -> _Survey:
    """What this archive's own headers say about itself, per generation.

    Both generations are walked, which the RAR5-only scan this replaces was the
    argument for: a RAR3 archive reached no check at all, so its
    password-protected entries were read and stored as ciphertext. The signals
    are the format's own — a crypt block or record, a password flag, the main
    header's volume flag, an entry's split flag — because a filename cannot
    carry any of them. The name heuristic this replaced matched `.partN` and so
    read a renamed or old-style first volume as a whole archive.
    """
    if fmt == "rar5":
        return _survey_rar5(path)
    return _survey_rar3(path)


def _survey_rar5(path: Path) -> _Survey:
    """Walk a RAR5 block chain.

    Stops at the end-of-archive block, which is what makes the truncation
    finding safe: a RAR archive may legitimately carry appended bytes, and
    parsing them as a further block would refuse a readable file. Everything
    before that block, on the other hand, is structure the archive declared and
    must therefore be present.
    """
    encrypted: str | None = None
    volume: str | None = None
    seen_main = False
    # Whether the window that failed to parse had reached the end of the file.
    # That is what separates "the file ran out inside a header" from "this
    # header is larger than the window I read", and only the second defers.
    at_eof = False
    try:
        with path.open("rb") as handle:
            size = handle.seek(0, 2)
            handle.seek(len(_RAR5_SIGNATURE))
            for _ in range(_MAX_HEADERS):
                base = handle.tell()
                if base >= size:
                    break  # ended on a block boundary, which is well-formed
                window = handle.read(_RAR5_HEADER_WINDOW)
                at_eof = base + len(window) >= size
                if len(window) < 5:
                    return _Survey(encrypted, volume, _CUT)
                at = 4  # the header CRC, not verified here
                header_size, at = _vint(window, at)
                if header_size <= 0:
                    return _Survey(encrypted, volume, _MALFORMED)
                header_end = at + header_size
                if base + header_end > size:
                    return _Survey(encrypted, volume, _CUT)
                kind, at = _vint(window, at)
                if kind == _RAR5_HEAD_CRYPT:
                    return _Survey(encrypted=_HEADER_ENCRYPTED)
                flags, at = _vint(window, at)
                extra_size = 0
                data_size = 0
                if flags & _RAR5_HAS_EXTRA:
                    extra_size, at = _vint(window, at)
                if flags & _RAR5_HAS_DATA:
                    data_size, at = _vint(window, at)
                if kind == _RAR5_HEAD_ENDARC:
                    break
                if kind == _RAR5_HEAD_MAIN:
                    seen_main = True
                    # The archive flags are the main header's whole body, so
                    # they sit exactly where the common fields ended.
                    archive_flags, _ = _vint(window, at)
                    if archive_flags & _RAR5_ARCHIVE_VOLUME:
                        volume = _MAIN_VOLUME_FLAG
                elif kind == _RAR5_HEAD_FILE:
                    # The per-entry split flags are a second, independent signal
                    # and are read rather than ignored: they say this entry is a
                    # fragment, which is the harm the volume refusal exists to
                    # prevent, and they still say it on an archive whose main
                    # header was rewritten to drop the volume flag. The main
                    # header's own statement wins where both are present, so
                    # what an operator is told does not depend on how many
                    # entries happened to be split.
                    if volume is None and flags & (_RAR5_SPLIT_BEFORE | _RAR5_SPLIT_AFTER):
                        volume = _ENTRY_SPLIT
                    if extra_size:
                        # The extra area ends the header, so it is found from the
                        # header's end rather than by walking the body's fields,
                        # which differ between block types and are not needed
                        # here.
                        pos = header_end - extra_size
                        if pos < 0 or header_end > len(window):
                            return _Survey(encrypted, volume)  # defer
                        while pos < header_end:
                            record_size, after = _vint(window, pos)
                            if record_size <= 0:
                                break
                            record_type, _ = _vint(window, after)
                            if record_type == _RAR5_EXTRA_CRYPT:
                                return _Survey(encrypted=_ENTRIES_ENCRYPTED)
                            # The size vint counts the record's content, which
                            # starts where the vint ended.
                            pos = after + record_size
                if base + header_end + data_size > size:
                    return _Survey(encrypted, volume, _CUT)
                # Seek rather than index: the data area may be gigabytes, and
                # this is the step a prefix read cannot take.
                handle.seek(base + header_end + data_size)
    except (OSError, ValueError, IndexError):
        return _Survey(encrypted, volume, _MALFORMED if at_eof else None)
    if not seen_main:
        return _Survey(encrypted, volume, _NO_MAIN)
    return _Survey(encrypted, volume)


def _survey_rar3(path: Path) -> _Survey:
    """Walk a RAR 2.9/3.x/4.x block chain.

    Reads flags and sizes only. The per-file `FHD_PASSWORD` is here as well as
    in libarchive's own verdict, deliberately: the verdict is the authority, and
    this is what refuses the archive before it is opened at all, so the two
    passes reach the same answer from the same call rather than from whichever
    of them happened to run.
    """
    encrypted: str | None = None
    volume: str | None = None
    seen_main = False
    try:
        with path.open("rb") as handle:
            size = handle.seek(0, 2)
            handle.seek(len(_RAR3_SIGNATURE))
            for _ in range(_MAX_HEADERS):
                base = handle.tell()
                if base >= size:
                    break
                head = handle.read(_RAR3_BASE_HEADER + 4)
                if len(head) < _RAR3_BASE_HEADER:
                    return _Survey(encrypted, volume, _CUT)
                kind = head[2]
                flags = int.from_bytes(head[3:5], "little")
                head_size = int.from_bytes(head[5:7], "little")
                if head_size < _RAR3_BASE_HEADER:
                    return _Survey(encrypted, volume, _MALFORMED)
                add_size = 0
                if flags & _RAR3_LONG_BLOCK:
                    if len(head) < _RAR3_BASE_HEADER + 4:
                        return _Survey(encrypted, volume, _CUT)
                    add_size = int.from_bytes(head[7:11], "little")
                if kind == _RAR3_HEAD_ENDARC:
                    break
                if kind == _RAR3_HEAD_MAIN:
                    seen_main = True
                    if flags & _RAR3_MAIN_PASSWORD:
                        # Every header after this one is encrypted too, so the
                        # walk cannot continue — and does not need to.
                        return _Survey(encrypted=_HEADER_ENCRYPTED)
                    if flags & _RAR3_MAIN_VOLUME:
                        volume = _MAIN_VOLUME_FLAG
                elif kind == _RAR3_HEAD_FILE:
                    if flags & _RAR3_FILE_PASSWORD:
                        return _Survey(encrypted=_ENTRIES_ENCRYPTED)
                    if volume is None and flags & (
                        _RAR3_FILE_SPLIT_BEFORE | _RAR3_FILE_SPLIT_AFTER
                    ):
                        volume = _ENTRY_SPLIT
                    if flags & _RAR3_FILE_LARGE:
                        # A >4 GB entry: ADD_SIZE holds only the low half, so
                        # seeking by it would land inside the data and read
                        # payload bytes as a header. Stopping here reports what
                        # was found and claims nothing about the rest, which is
                        # the walk's whole stance.
                        return _Survey(encrypted, volume)
                if base + head_size + add_size > size:
                    return _Survey(encrypted, volume, _CUT)
                handle.seek(base + head_size + add_size)
    except OSError:
        return _Survey(encrypted, volume)
    if not seen_main:
        return _Survey(encrypted, volume, _NO_MAIN)
    return _Survey(encrypted, volume)


class TarExtractor:
    """TAR archives, plain or compressed."""

    name = "tar"
    suffixes = {
        ".tar": "application/x-tar",
        ".gz": "application/gzip",
        ".tgz": "application/gzip",
        ".bz2": "application/x-bzip2",
        ".tbz2": "application/x-bzip2",
        ".xz": "application/x-xz",
    }

    def accepts(self, path: Path) -> bool:
        suffix = path.suffix.lower()
        if suffix in (".tar", ".tgz", ".tbz2"):
            return True
        # `.gz`, `.bz2` and `.xz` are compression, not format: only claim them
        # when a `.tar` sits underneath, so a lone `notes.txt.gz` is not
        # mistaken for an archive.
        if suffix in (".gz", ".bz2", ".xz"):
            return Path(path.stem).suffix.lower() == ".tar"
        return False

    def extract(self, path: Path) -> Extraction:
        refusals: list[str] = []
        listing: list[str] = []
        try:
            with tarfile.open(path) as archive:
                for member in archive:
                    if member.isdir():
                        continue
                    if not member.isfile():
                        # Links, devices, and fifos. A tar may contain them; a
                        # corpus has no use for them and following one is how a
                        # tar escapes its extraction root.
                        refusals.append(f"{member.name}: not a regular file")
                        continue
                    reason = _unsafe_reason(member.name)
                    if reason is not None:
                        refusals.append(f"{member.name}: {reason}")
                        continue
                    listing.append(member.name)
        except (tarfile.TarError, OSError) as exc:
            raise ExtractionError(f"could not read {path.name} as a tar: {exc}") from exc

        return Extraction(
            text="\n".join(listing),
            media_type=self.suffixes.get(path.suffix.lower(), "application/x-tar"),
            extractor=self.name,
            metadata={"entries": str(len(listing))},
            is_container=True,
            refusals=tuple(refusals),
        )

    def iter_children(self, path: Path) -> Iterator[Child]:
        with tarfile.open(path) as archive:
            for member in archive:
                if not member.isfile():
                    continue
                if _unsafe_reason(member.name) is not None:
                    continue
                if member.size > MAX_ENTRY_BYTES:
                    continue
                handle = archive.extractfile(member)
                if handle is None:
                    continue
                with handle:
                    data = handle.read(MAX_ENTRY_BYTES + 1)
                if len(data) > MAX_ENTRY_BYTES:
                    continue
                yield Child(name=member.name, data=data)
