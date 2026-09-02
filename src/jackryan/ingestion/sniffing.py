"""Identifying a file by its bytes, for names the registry cannot read.

This exists for one failure: a file whose declared type defeats selection. Real
dumps carry them — `'… .docx'` with the shell quotes baked into the name, an
attachment saved with no extension at all — and the registry keys on the
declared type alone, so a perfectly readable document is refused as an
unsupported format.

What this module answers is narrow on purpose: *which declared type does this
file's content positively identify?* It never decides whether a file is worth
reading, and it is consulted only where the registry has already said nothing.

Two rules hold it in place.

**Positive signatures only.** "Decodes as text" is not a signature. Admitting it
would draw every unhandled text-shaped file — batch scripts, calendar invites,
detached signatures — into the corpus as plain-text documents, which is the
failure this project already refuses under a different name when it declines
text carrying no letters or digits. A near miss must return `None` and be
refused, because a facet or a corpus dominated by false matches costs an analyst
more than an absent one.

**Every suffix returned is one a shipped extractor declares.** A signature for a
format nothing can read would turn a clean refusal into a routing loop or a
`KeyError`; a test asserts this against the live registry rather than trusting
this comment.
"""

from __future__ import annotations

import struct
import zipfile
from pathlib import Path

# Every signature here decides on the first few bytes. Only the OLE2 byte scan
# reads further, so the header is what is read first and the larger prefix is
# paid for only when the compound-file magic is actually present. A dump of
# thousands of unroutable media files would otherwise cost a megabyte each to
# refuse.
HEADER_BYTES = 512

# Enough to cover the directory of the small documents the byte scan is for,
# without reading a large file whole to identify it.
PREFIX_BYTES = 1 << 20

# Directory entries are 128 bytes and the sectors holding them begin at a
# multiple of the sector size, itself a multiple of 128. So a genuine stream
# name starts at a file offset divisible by 128 — which is what separates one
# from the same characters appearing in a document's own text.
_ENTRY_BYTES = 128

# The part that says which OOXML format an archive holds. The outer container is
# a plain ZIP for all three, so the name list is what decides. Exact paths, not
# prefixes: an embedded object lives under `word/embeddings/` and must not make a
# document look like a workbook.
_OOXML_PARTS = (
    ("word/document.xml", ".docx"),
    ("xl/workbook.xml", ".xlsx"),
    ("ppt/presentation.xml", ".pptx"),
)

# Entries that say "I am a document of some format" without saying one this
# registry reads: ODF declares `mimetype`, and every OPC package declares
# `[Content_Types].xml`. The three formats above are matched first, so reaching
# these means a zip-based document nothing here can read — OpenDocument, iWork,
# EPUB, `.xlsb`, `.vsdx`. Calling it an archive would store its part list as a
# document's text and send its thumbnails through recognition, which is a corpus
# of false matches rather than a refusal.
_DOCUMENT_PACKAGE_MARKERS = ("mimetype", "[Content_Types].xml")

# Stream names that say which OLE2 format a compound file holds. `__substg1.0_`
# comes first deliberately: an Outlook message can carry an embedded Word
# document in a sub-storage, so testing for Word first would read a message as a
# document. No other ordering here matters.
#
# The flag says whether the name is complete. A message's property streams are
# named `__substg1.0_0037001F` and similar, so that entry is a prefix and only
# the other three can be required to end where they end — which is what lets the
# byte scan demand a NUL terminator for them.
_OLE2_STREAMS = (
    ("__substg1.0_", ".msg", False),
    ("WordDocument", ".doc", True),
    ("Workbook", ".xls", True),
    ("PowerPoint Document", ".ppt", True),
)

# The two suffixes returned from a branch rather than a table. Named so that
# `producible_suffixes` can see them: a literal buried in a function body is a
# signature nothing can enumerate.
_ARCHIVE_SUFFIX = ".zip"
_WEBP_SUFFIX = ".webp"

_ZIP_MAGIC = b"PK\x03\x04"
_OLE2_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"

# Signatures that need no second look. Every one is at least three bytes of
# non-text content: two ASCII letters would match prose, which is why the
# bitmap header is checked structurally below instead of appearing here.
_MAGIC = (
    (b"%PDF-", ".pdf"),
    (b"{\\rtf", ".rtf"),
    (b"\x89PNG\r\n\x1a\n", ".png"),
    (b"\xff\xd8\xff", ".jpg"),
    (b"II*\x00", ".tiff"),
    (b"MM\x00*", ".tiff"),
)

_BITMAP_SUFFIX = ".bmp"


def producible_suffixes() -> set[str]:
    """Every suffix `sniff_suffix` can return.

    Derived from the tables rather than listed, so a signature added above
    enters it without anyone remembering. That is what makes the module's
    invariant checkable — every suffix returned here must be one some shipped
    extractor will accept, or the fallback resolves to a refusal at best and a
    crash at worst.
    """
    return (
        {suffix for _, suffix in _MAGIC}
        | {suffix for _, suffix in _OOXML_PARTS}
        | {suffix for _, suffix, _exact in _OLE2_STREAMS}
        | {_ARCHIVE_SUFFIX, _WEBP_SUFFIX, _BITMAP_SUFFIX}
    )


def sniff_suffix(path: Path) -> str | None:
    """The declared suffix this file's content identifies, or `None`.

    `None` covers every uncertainty — an unreadable file, an unrecognised
    signature, a container holding nothing known — because the caller's
    alternative is the refusal it would have made anyway.

    **This function is total, and that is a hard requirement rather than
    tidiness.** It is called from `FormatRouter.extractor_for`, which the
    service layer consults in its main ingest loop *outside* the per-document
    error handler. Anything raised here therefore ends the whole run instead of
    failing one file. `zipfile.namelist()` alone raises `NotImplementedError`
    for a declared `extract_version` it does not support and `UnicodeDecodeError`
    for a central-directory name flagged UTF-8 that is not — neither a
    `BadZipFile` nor an `OSError`, both craftable in a hundred bytes, and each
    measured to abort an ingest that `develop` completes.
    """
    try:
        if path.is_symlink():
            # The service refuses a symlink before it would ever be stored, so
            # identifying one buys nothing and reading it means opening a file
            # outside the dump. Declining here keeps that read from happening at
            # all, which is what the pre-filter used to do for a name it could
            # not read. Inside the try because `Path.is_symlink` re-raises
            # `PermissionError` — pathlib swallows only ENOENT/ENOTDIR/EBADF/
            # ELOOP — and a file in an unsearchable directory would otherwise
            # raise straight past the net the docstring promises.
            return None

        with path.open("rb") as handle:
            header = handle.read(HEADER_BYTES)
            # Only the OLE2 byte scan looks past the header, so only it pays
            # for the larger read. A folder of unroutable media files costs
            # half a kilobyte each to refuse rather than a megabyte.
            prefix = (
                header + handle.read(PREFIX_BYTES - HEADER_BYTES)
                if header.startswith(_OLE2_MAGIC)
                else header
            )
    except OSError:
        return None

    try:
        return _identify(path, prefix)
    except Exception:
        # The net the docstring promises. `Exception` rather than
        # `BaseException` so a test gate's sentinel still escapes and still
        # fails loudly. A signature bug surfaces here as a refusal, which is
        # what an unidentifiable file gets anyway — and a test pins each known
        # raising input, so this is not the only thing standing behind them.
        return None


def _identify(path: Path, prefix: bytes) -> str | None:
    """Which format the bytes say this is, raising freely for the net above."""
    if prefix.startswith(_ZIP_MAGIC):
        return _zip_suffix(path)
    if prefix.startswith(_OLE2_MAGIC):
        return _ole2_suffix(path, prefix)

    # WebP carries its marker past the RIFF header, so it cannot be a prefix
    # match like the rest.
    if prefix[:4] == b"RIFF" and prefix[8:12] == b"WEBP":
        return _WEBP_SUFFIX

    if _is_bitmap(path, prefix):
        return _BITMAP_SUFFIX

    for magic, suffix in _MAGIC:
        if prefix.startswith(magic):
            return suffix
    return None


def _is_bitmap(path: Path, prefix: bytes) -> bool:
    """Whether this is a BMP, on more than the two letters `BM`.

    `BM` alone is not a signature — it is two ASCII letters, so a memo opening
    "BMW purchase order" would be routed into the image reader and the
    recognition stack. That is this module's own rule broken by its own table,
    which is why the header is checked structurally: the declared file size must
    be the real one, and the pixel data must start inside the file after a
    header of a size the format defines.
    """
    if not prefix.startswith(b"BM") or len(prefix) < 18:
        return False
    declared, _, _, data_offset, header_bytes = struct.unpack_from("<IHHII", prefix, 2)
    try:
        actual = path.stat().st_size
    except OSError:
        return False
    # 12, 40, 52, 56, 64, 108 and 124 are the DIB header sizes the format
    # defines; anything else is not a bitmap however it opens.
    return (
        declared == actual
        and header_bytes in (12, 40, 52, 56, 64, 108, 124)
        and 14 + header_bytes <= data_offset < actual
    )


def _zip_suffix(path: Path) -> str | None:
    """Which OOXML format the archive holds, or `.zip` if it holds none."""
    try:
        with zipfile.ZipFile(path) as archive:
            names = set(archive.namelist())
    except (zipfile.BadZipFile, OSError):
        # The ZIP magic was there and the archive will not open. Refusing is
        # right: the container extractor would fail on it too, and saying
        # "unsupported format" is more honest than "broken zip" for a file
        # whose name never claimed to be an archive. The stranger failures
        # `namelist` can raise are named in `sniff_suffix` and caught there.
        return None

    for part, suffix in _OOXML_PARTS:
        if part in names:
            return suffix

    if any(marker in names for marker in _DOCUMENT_PACKAGE_MARKERS):
        # A zip-based document of a format nothing here reads. Refusing is the
        # near-miss rule: calling it an archive stores its part list as the
        # document's text, sends its preview thumbnail through recognition, and
        # files a refusal for every XML part inside. Measured on an ODT-shaped
        # fixture — four refusals and an OCR'd thumbnail stored as a document.
        # A dump of institutional OpenDocument files would fill a casefile with
        # exactly the false matches this module exists to refuse.
        return None

    return _ARCHIVE_SUFFIX


def _ole2_suffix(path: Path, prefix: bytes) -> str | None:
    """Which OLE2 format the compound file holds, or `None`.

    The directory is read where the header points, which is exact. The byte scan
    behind it catches a file whose directory is chained beyond the first sector —
    a bounded fallback, so a miss is a refusal rather than a wrong answer.

    That fallback masks its own partner: with the scan in place, a broken offset
    still returns the right suffix from here, so nothing asserted through
    `sniff_suffix` can detect one. Three mutations of the arithmetic in
    `_ole2_directory_names` left the composed tests entirely green. Test that
    function directly, and place the stream past the first 512 bytes of the
    sector — a wrong offset reads 3584 bytes low on a 4096-byte sector, which is
    a whole number of 128-byte entries and therefore still overlaps a stream
    sitting at offset 0.
    """
    names = _ole2_directory_names(path, prefix)
    for stream, suffix, _exact in _OLE2_STREAMS:
        if any(name.startswith(stream) for name in names):
            return suffix
    for stream, suffix, exact in _OLE2_STREAMS:
        if _names_a_stream(prefix, stream, exact):
            return suffix
    return None


def _names_a_stream(prefix: bytes, stream: str, exact: bool) -> bool:
    """Whether these bytes hold `stream` as a directory entry, not as prose.

    A bare substring search is not enough, and the difference is a wrong answer
    rather than a miss: Word and Excel store text as UTF-16LE too, so a
    document containing the words "see the Workbook tab" would be identified as
    a workbook and handed to the converter as one. Measured on a Visio-shaped
    fixture, which sniffed as `.xls`.

    A genuine entry begins at a multiple of 128 — entries are that size and the
    sectors holding them start at a multiple of the sector size, itself a
    multiple of 128. A complete name is NUL-terminated as well; a prefix entry
    such as a message's property streams is not, and gets alignment alone.
    """
    needle = stream.encode("utf-16-le")
    position = prefix.find(needle)
    while position != -1:
        if position % _ENTRY_BYTES == 0:
            if not exact:
                return True
            after = position + len(needle)
            if prefix[after : after + 2] == b"\x00\x00":
                return True
        position = prefix.find(needle, position + 1)
    return False


def _ole2_directory_names(path: Path, prefix: bytes) -> list[str]:
    """The stream names in the first directory sector, or empty if unreadable.

    A compound file's header gives the sector size and the first directory
    sector; each 128-byte entry there opens with a UTF-16LE name and its length
    in bytes. Only the first sector is read: this is discriminating a format,
    not enumerating a file, and walking the allocation table to find the rest
    would be a parser where a fingerprint was asked for.
    """
    try:
        (sector_shift,) = struct.unpack_from("<H", prefix, 30)
        (first_directory,) = struct.unpack_from("<I", prefix, 48)
    except struct.error:
        return []
    # 512 and 4096 are the only sizes the format defines. Anything else is a
    # malformed header, and computing an offset from it would seek to nonsense.
    if sector_shift not in (9, 12) or first_directory in (0xFFFFFFFF, 0xFFFFFFFE):
        return []

    sector_size = 1 << sector_shift
    # Sectors are numbered from the end of the header, which occupies the first
    # one whatever its size.
    offset = (first_directory + 1) * sector_size

    if offset + sector_size <= len(prefix):
        sector = prefix[offset : offset + sector_size]
    else:
        try:
            with path.open("rb") as handle:
                handle.seek(offset)
                sector = handle.read(sector_size)
        except OSError:
            return []

    names = []
    for start in range(0, len(sector) - 127, 128):
        entry = sector[start : start + 128]
        (name_bytes,) = struct.unpack_from("<H", entry, 64)
        if not 2 <= name_bytes <= 64:
            continue
        try:
            # The length counts the trailing NUL that terminates the name.
            names.append(entry[: name_bytes - 2].decode("utf-16-le"))
        except UnicodeDecodeError:
            continue
    return names
