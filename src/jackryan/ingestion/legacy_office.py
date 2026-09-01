"""Legacy binary Office formats, read by converting them to modern ones.

Word 97 `.doc`, Excel 97 `.xls`, PowerPoint 97 `.ppt` and RTF have no Python
reader worth having. They are read by converting the file to its modern sibling
and handing the result to the extractor that already owns that suffix, so a
corpus never holds two renderings of the same kind of document — a `.xls` reads
exactly as an `.xlsx` does, sheet by sheet and row by row.

That is the whole reason this is an extractor of its own rather than three more
entries in `MARKUP_SUFFIXES`: the document engine would read a legacy workbook
with its own spreadsheet backend, whose output has a different shape from the
one `SpreadsheetExtractor` produces. Two shapes in one corpus is not an error
anywhere — it is a quiet loss of retrieval quality, which is worse.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from .extractors import DoclingExtractor, Extraction, ExtractionError
from .quality_gate import QualityGate

# The media types are docling's own, from its `FormatToMimeType` mapping, so a
# corpus records the same string whichever engine grows to read these next.
LEGACY_SUFFIXES = {
    ".doc": "application/msword",
    ".xls": "application/vnd.ms-excel",
    ".ppt": "application/vnd.ms-powerpoint",
    ".rtf": "application/rtf",
}

# Which modern format each converts to, and therefore which extractor reads the
# result. RTF goes to `.docx` because it is a word-processor document; nothing
# reads RTF directly.
_TARGET = {".doc": "docx", ".rtf": "docx", ".xls": "xlsx", ".ppt": "pptx"}

# A ceiling on one conversion, so a hung converter cannot stall an ingest
# indefinitely. Deliberately a constant rather than a profile setting: the
# profile layer is for what an operator tunes per deployment, and a safety bound
# that stops a wedged subprocess is not tuning. It also overrides no
# operator-supplied value.
CONVERSION_TIMEOUT_S = 120

# Enough to tell the three containers apart. OLE2 is the legacy compound file
# every Office 97 format is wrapped in; ZIP is what an OOXML file really is.
_OLE2_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_ZIP_MAGIC = b"PK\x03\x04"
_RTF_MAGIC = b"{\\rtf"

_MACOS_BUNDLE = "/Applications/LibreOffice.app/Contents/MacOS/soffice"


def find_converter() -> str | None:
    """The LibreOffice binary, or None.

    Resolved in the same order docling resolves it, so a host that satisfies
    docling satisfies this. Called per extraction rather than cached: an
    operator who installs the binary while a long-running server is up should
    not have to restart it to be believed.
    """
    return (
        shutil.which("libreoffice")
        or shutil.which("soffice")
        or (_MACOS_BUNDLE if os.path.isfile(_MACOS_BUNDLE) else None)
    )


# The literal an operator sees when no converter resolves. Defined once and
# read by every surface that reports the capability, so the two adapters cannot
# drift into describing the same host with two different words.
UNAVAILABLE = "unavailable"


def converter_status() -> str:
    """What the operator-facing surfaces report: the resolved path, or `unavailable`."""
    return find_converter() or UNAVAILABLE


class LegacyOfficeExtractor:
    """Converts a legacy Office file, then delegates to the modern format's reader.

    Subclasses nothing on purpose. Extractor selection is duck typing — the
    router calls `accepts`, reads `suffixes`, and asks for `iter_children` with
    `getattr` — so a base class would buy nothing and couple this to the two
    extractors that read pages, which this one never does.
    """

    name = "legacy-office"
    suffixes = LEGACY_SUFFIXES

    def __init__(self, gate: QualityGate | None = None) -> None:
        # Imported here for the same reason `default_extractors` imports its
        # siblings lazily: `sheets` imports from `extractors`, which imports
        # this module, and a module-level import would close that ring.
        from .sheets import SpreadsheetExtractor

        # The gate is threaded through even though nothing here reaches a rung:
        # a converted `.docx` or `.pptx` is not a page-bearing format. Passing
        # it keeps the test suite's gate — whose rung readers raise — able to
        # prove that, rather than leaving the claim untested.
        self._documents = DoclingExtractor(gate)
        self._workbooks = SpreadsheetExtractor()

    def accepts(self, path: Path) -> bool:
        # Suffix only. `supported_suffixes()` is derived from `suffixes` and has
        # to keep advertising all four, and an `accepts` that opened the file
        # would make format support a property of content rather than of the
        # registry. What the file really is decides how it is read, in
        # `extract`, not whether it is claimed.
        return path.suffix.lower() in LEGACY_SUFFIXES

    def extract(self, path: Path) -> Extraction:
        suffix = path.suffix.lower()
        target = _TARGET[suffix]

        try:
            with path.open("rb") as handle:
                head = handle.read(8)
        except OSError as exc:
            raise ExtractionError(f"could not read {path.name}: {exc}") from exc

        work = Path(tempfile.mkdtemp(prefix="jackryan-legacy-"))
        try:
            if suffix == ".rtf":
                if not head.startswith(_RTF_MAGIC):
                    raise ExtractionError(
                        f"{path.name} is named .rtf but does not begin with an RTF header"
                    )
                source = self._convert(path, target, work)
                lineage = "legacy-office"
            elif head.startswith(_ZIP_MAGIC):
                # Already the modern format under a legacy name. The dump this
                # change answers held two such workbooks. Converting one would
                # be a lossy round trip for no reason.
                source = self._rename_to_target(path, target, work)
                lineage = "legacy-office-passthrough"
            elif head.startswith(_OLE2_MAGIC):
                source = self._convert(path, target, work)
                lineage = "legacy-office"
            else:
                raise ExtractionError(
                    f"{path.name} is named {suffix} but is neither an OLE2 nor an "
                    "OOXML container"
                )

            delegate = self._workbooks if target == "xlsx" else self._documents
            try:
                delegated = delegate.extract(source)
            except ExtractionError as exc:
                # Named for the file the operator has, not for the scratch copy
                # they will never see.
                raise ExtractionError(f"{path.name}, read as .{target}: {exc}") from exc

            return Extraction(
                text=delegated.text,
                # The legacy type, because that is what the evidence is. The
                # conversion is how the text was obtained, not what was stored.
                media_type=LEGACY_SUFFIXES[suffix],
                extractor=f"{lineage}+{delegated.extractor}",
                metadata=delegated.metadata,
            )
        finally:
            shutil.rmtree(work, ignore_errors=True)

    def _rename_to_target(self, path: Path, target: str, work: Path) -> Path:
        """Copy the file under the suffix its content actually is.

        A delegate keys its media type off the path's suffix, so handing it the
        original `.xls` would raise a `KeyError` — which is not an
        `ExtractionError`, and would therefore end the whole ingest run rather
        than fail one document.
        """
        destination = work / f"{path.stem}.{target}"
        try:
            shutil.copyfile(path, destination)
        except OSError as exc:
            raise ExtractionError(f"could not read {path.name}: {exc}") from exc
        return destination

    def _convert(self, path: Path, target: str, work: Path) -> Path:
        converter = find_converter()
        if converter is None:
            raise ExtractionError(
                f"reading {path.name} needs LibreOffice to convert {path.suffix.lower()} "
                f"to .{target}; install it and put soffice on PATH"
            )

        out_dir = work / "out"
        profile = work / "profile"
        out_dir.mkdir(exist_ok=True)
        profile.mkdir(exist_ok=True)

        try:
            subprocess.run(
                [
                    converter,
                    # Per call, not shared: LibreOffice takes an exclusive lock
                    # on its user profile, and ingestion runs in a thread pool.
                    f"-env:UserInstallation={profile.as_uri()}",
                    "--headless",
                    "--convert-to",
                    target,
                    "--outdir",
                    str(out_dir),
                    str(path.resolve()),
                ],
                # Captured rather than discarded, so a failure carries
                # LibreOffice's own diagnosis instead of a bare exit code.
                capture_output=True,
                check=True,
                timeout=CONVERSION_TIMEOUT_S,
            )
        except subprocess.TimeoutExpired as exc:
            raise ExtractionError(
                f"converting {path.name} to .{target} exceeded {CONVERSION_TIMEOUT_S}s"
            ) from exc
        except subprocess.CalledProcessError as exc:
            detail = (exc.stderr or b"").decode("utf-8", "replace").strip()[:300]
            raise ExtractionError(
                f"could not convert {path.name} to .{target}: {detail}"
            ) from exc
        except OSError as exc:
            raise ExtractionError(
                f"could not run the converter for {path.name}: {exc}"
            ) from exc

        # The glob, not the exit status, is the real gate: LibreOffice exits 0
        # in some cases having written nothing at all.
        produced = sorted(out_dir.glob(f"*.{target}"))
        if len(produced) != 1:
            raise ExtractionError(
                f"converting {path.name} to .{target} produced no output"
            )
        return produced[0]
