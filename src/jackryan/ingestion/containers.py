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

import tarfile
import zipfile
from collections.abc import Iterator
from pathlib import Path

from .extractors import Child, Extraction, ExtractionError

# An entry larger than this is refused before it is read. The aggregate budget
# lives in the ingestion service; this is the per-entry floor beneath it, and it
# is what stops one declared-enormous member being read into memory at all.
MAX_ENTRY_BYTES = 512 * 1024 * 1024


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
