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

# Enough to hold the header of anything here, and — for the byte scan that backs
# up the OLE2 directory read — enough to cover the directory of the small
# documents this is for, without reading a large file whole to identify it.
PREFIX_BYTES = 1 << 20

# The part that says which OOXML format an archive holds. The outer container is
# a plain ZIP for all three, so the name list is what decides. Exact paths, not
# prefixes: an embedded object lives under `word/embeddings/` and must not make a
# document look like a workbook.
_OOXML_PARTS = (
    ("word/document.xml", ".docx"),
    ("xl/workbook.xml", ".xlsx"),
    ("ppt/presentation.xml", ".pptx"),
)

# Stream names that say which OLE2 format a compound file holds. `__substg1.0_`
# comes first deliberately: an Outlook message can carry an embedded Word
# document in a sub-storage, so testing for Word first would read a message as a
# document. No other ordering here matters.
_OLE2_STREAMS = (
    ("__substg1.0_", ".msg"),
    ("WordDocument", ".doc"),
    ("Workbook", ".xls"),
    ("PowerPoint Document", ".ppt"),
)

_ZIP_MAGIC = b"PK\x03\x04"
_OLE2_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"

# Signatures that need no second look.
_MAGIC = (
    (b"%PDF-", ".pdf"),
    (b"{\\rtf", ".rtf"),
    (b"\x89PNG\r\n\x1a\n", ".png"),
    (b"\xff\xd8\xff", ".jpg"),
    (b"II*\x00", ".tiff"),
    (b"MM\x00*", ".tiff"),
    (b"BM", ".bmp"),
)


def sniff_suffix(path: Path) -> str | None:
    """The declared suffix this file's content identifies, or `None`.

    `None` covers every uncertainty — an unreadable file, an unrecognised
    signature, a container holding nothing known — because the caller's
    alternative is the refusal it would have made anyway. Raising here would
    turn one file's permissions into a failed run.
    """
    try:
        with path.open("rb") as handle:
            prefix = handle.read(PREFIX_BYTES)
    except OSError:
        return None

    if prefix.startswith(_ZIP_MAGIC):
        return _zip_suffix(path)
    if prefix.startswith(_OLE2_MAGIC):
        return _ole2_suffix(path, prefix)

    # WebP carries its marker past the RIFF header, so it cannot be a prefix
    # match like the rest.
    if prefix[:4] == b"RIFF" and prefix[8:12] == b"WEBP":
        return ".webp"

    for magic, suffix in _MAGIC:
        if prefix.startswith(magic):
            return suffix
    return None


def _zip_suffix(path: Path) -> str | None:
    """Which OOXML format the archive holds, or `.zip` if it holds none."""
    try:
        with zipfile.ZipFile(path) as archive:
            names = set(archive.namelist())
    except (zipfile.BadZipFile, OSError):
        # The ZIP magic was there and the archive will not open. Refusing is
        # right: the container extractor would fail on it too, and saying
        # "unsupported format" is more honest than "broken zip" for a file
        # whose name never claimed to be an archive.
        return None

    for part, suffix in _OOXML_PARTS:
        if part in names:
            return suffix
    return ".zip"


def _ole2_suffix(path: Path, prefix: bytes) -> str | None:
    """Which OLE2 format the compound file holds, or `None`.

    The directory is read where the header points, which is exact. The byte scan
    behind it catches a file whose directory is chained beyond the first sector —
    a bounded fallback, so a miss is a refusal rather than a wrong answer.
    """
    names = _ole2_directory_names(path, prefix)
    for stream, suffix in _OLE2_STREAMS:
        if any(name.startswith(stream) for name in names):
            return suffix
    for stream, suffix in _OLE2_STREAMS:
        if stream.encode("utf-16-le") in prefix:
            return suffix
    return None


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
