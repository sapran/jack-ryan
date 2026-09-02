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

import re
import tarfile
import zipfile
from collections.abc import Iterator
from pathlib import Path

from .extractors import Child, Extraction, ExtractionError

# An entry larger than this is refused before it is read. The aggregate budget
# lives in the ingestion service; this is the per-entry floor beneath it, and it
# is what stops one declared-enormous member being read into memory at all.
MAX_ENTRY_BYTES = 512 * 1024 * 1024

# The literal an operator sees when no archive reader resolves. Defined once and
# read by every surface that reports the capability, so the two adapters cannot
# drift into describing the same host with two different words. Same reasoning,
# and deliberately the same vocabulary, as the document converter's.
RAR_UNAVAILABLE = "unavailable"


def find_rar_reader() -> str | None:
    """The libarchive version this host offers, or None.

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
        import libarchive.ffi

        return str(libarchive.ffi.version_number())
    except Exception:  # noqa: BLE001 - see the docstring; the type is not knowable
        return None


def rar_status() -> str:
    """What the operator-facing surfaces report: the libarchive version, or `unavailable`."""
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
    """

    name = "rar"
    suffixes = {".rar": "application/vnd.rar"}

    def accepts(self, path: Path) -> bool:
        return path.suffix.lower() in self.suffixes

    def extract(self, path: Path) -> Extraction:
        # Refused before opening rather than after failing: libarchive reads the
        # first volume's entries and then raises, so letting it try would yield a
        # partial listing that reads like a whole archive. Its own message
        # ("Too small block encountered") names neither the cause nor a remedy.
        if _is_multi_volume(path):
            raise ExtractionError(
                f"{path.name} is one volume of a multi-volume archive, which cannot be "
                "read; join the volumes and ingest the result"
            )

        reader = _libarchive()
        fmt = _rar_format(path)
        if fmt == "rar5":
            encrypted = _rar5_encrypted_reason(path)
            if encrypted is not None:
                raise ExtractionError(
                    f"{path.name} is encrypted ({encrypted}); it cannot be read "
                    "without its password — supply the decrypted archive"
                )
        refusals: list[str] = []
        listing: list[str] = []
        try:
            with reader.file_reader(str(path), format_name=fmt) as archive:
                for entry in archive:
                    if entry.isdir:
                        continue  # no bytes, so no content identity
                    name = _entry_name(entry)
                    reason = _not_a_file_reason(entry) or _unsafe_reason(name)
                    if reason is not None:
                        refusals.append(f"{name}: {reason}")
                        continue
                    listing.append(name)
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
        with reader.file_reader(str(path), format_name=_rar_format(path)) as archive:
            for entry in archive:
                if entry.isdir:
                    continue
                name = _entry_name(entry)
                # The same two tests as the listing pass, in the same order, so
                # the two cannot disagree about what an entry is.
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
                # Joined once rather than grown then copied: an entry near the
                # ceiling would otherwise cost twice its size in transient
                # memory.
                yield Child(name=name, data=b"".join(blocks))


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
    """
    try:
        import libarchive
        import libarchive.ffi

        libarchive.ffi.version_number()
    except ImportError as exc:
        # A different remedy, so a different message. Telling an operator to
        # install a system library when the Python package is what is missing
        # sends them after the wrong thing.
        raise ExtractionError(
            "reading a rar archive needs the libarchive-c package, which is not "
            f"installed ({exc}); reinstall the project's dependencies"
        ) from exc
    except Exception as exc:  # noqa: BLE001 - see `find_rar_reader`
        raise ExtractionError(
            "reading a rar archive needs libarchive, which is unavailable "
            f"({exc}); install the system libarchive library"
        ) from exc
    return libarchive


_VOLUME_SUFFIX = re.compile(r"\.part\d+$", re.IGNORECASE)


def _is_multi_volume(path: Path) -> bool:
    """Whether this names one volume of a split archive."""
    return _VOLUME_SUFFIX.search(path.stem) is not None


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


# The two RAR generations, and the libarchive reader each needs.
_RAR_MAGIC = ((b"Rar!\x1a\x07\x01\x00", "rar5"), (b"Rar!\x1a\x07\x00", "rar"))


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


# RAR5 block and record types, and how far into a file the walk below will look.
_RAR5_HEAD_CRYPT = 4
_RAR5_HEAD_FILE = 2
_RAR5_EXTRA_CRYPT = 1
_RAR5_HAS_EXTRA = 0x0001
_RAR5_HAS_DATA = 0x0002
_RAR5_SCAN_BYTES = 1024 * 1024


def _rar5_encrypted_reason(path: Path) -> str | None:
    """Why this RAR5 archive's contents cannot be read, or None.

    Positive detection only, and deliberately so: any malformed or unfamiliar
    byte makes this return None and hand the file to libarchive, which refuses
    it properly. This function may add a refusal; it must never be the reason a
    readable archive is rejected.

    It exists because libarchive cannot answer the question on the version that
    ships. WinRAR's *default* password mode encrypts entry data and leaves the
    headers readable — the mode you get without ticking "encrypt file names" —
    and libarchive 3.7.4's RAR5 reader skips the per-entry `EX_CRYPT` record as
    an unsupported attribute. Measured on 3.7.4, which is both this host and
    Debian trixie: `archive_entry_is_data_encrypted` returns 0 for such an entry
    and `archive_read_has_encrypted_entries` never leaves "don't know". So the
    listing pass succeeds, the container is stored, and `iter_children` hands
    back **ciphertext as document content** — which is then chunked, embedded and
    indexed as though it were the document's text. Nothing downstream can detect
    that, which makes it worse than the empty container it was mistaken for.

    Header encryption is checked here too, though libarchive does refuse that
    one, so that both password modes produce the same message rather than two.
    """
    try:
        with path.open("rb") as handle:
            blob = handle.read(_RAR5_SCAN_BYTES)
    except OSError:
        return None

    at = len(_RAR_MAGIC[0][0])

    def vint(pos: int) -> tuple[int, int]:
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

    try:
        while at < len(blob):
            _crc, at = at + 4, at + 4  # the header CRC, not verified here
            header_size, at = vint(at)
            if header_size <= 0:
                return None
            header_end = at + header_size
            kind, at = vint(at)
            if kind == _RAR5_HEAD_CRYPT:
                return "the archive header is encrypted"
            flags, at = vint(at)
            extra_size = 0
            data_size = 0
            if flags & _RAR5_HAS_EXTRA:
                extra_size, at = vint(at)
            if flags & _RAR5_HAS_DATA:
                data_size, at = vint(at)
            if kind == _RAR5_HEAD_FILE and extra_size:
                # The extra area sits at the end of the header, so it is found
                # from the header's end rather than by walking the body's fields
                # — which differ between block types and are not needed here.
                pos = header_end - extra_size
                while pos < header_end:
                    record_size, after = vint(pos)
                    if record_size <= 0:
                        break
                    record_type, _ = vint(after)
                    if record_type == _RAR5_EXTRA_CRYPT:
                        return "its entries are encrypted"
                    # The size vint counts the record's content, which starts
                    # where the vint ended.
                    pos = after + record_size
            at = header_end + data_size
    except (ValueError, IndexError):
        return None
    return None


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
