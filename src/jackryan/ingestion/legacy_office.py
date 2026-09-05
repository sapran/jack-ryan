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
import signal
import subprocess
from collections.abc import Callable
from pathlib import Path

from .extractors import (
    SCRATCH_STEM,
    DoclingExtractor,
    Extraction,
    ExtractionError,
    deliver_via_scratch_directory,
)
# Imported rather than redeclared, so the bytes have one owner. The names
# land in this module's namespace, which is what `_OLE2_MAGIC` and its
# siblings are read as from the tests.
from .sniffing import _OLE2_MAGIC, _RTF_MAGIC, _ZIP_MAGIC
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


# A ceiling on what the converter may *write*. Every other byte limit in this
# pipeline measures input the caller supplied — `MAX_FILE_BYTES` for a file on
# disk, the expansion budget for a container entry — and input size is exactly
# what a converted artefact is not bounded by. A legacy file well inside
# `MAX_FILE_BYTES` can convert into something far larger, and the converted file
# is the one a delegate loads whole. Kept here rather than imported from the
# service so an extractor does not depend on a service, and separate for the
# same reason `MAX_IMAGE_PIXELS` is separate: the quantity that costs the memory
# is not the quantity any input ceiling measures.
MAX_CONVERTED_BYTES = 512 * 1024 * 1024


def _kill_group(process: subprocess.Popen) -> None:
    """Kill the converter's whole process group, tolerating a race with its exit."""
    try:
        os.killpg(os.getpgid(process.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        # Already gone, or never made it into its own group. Fall back to the
        # single pid so a timeout never leaves the direct child behind either.
        process.kill()


def _diagnosis(returncode: int, stderr: bytes | None, stdout: bytes | None) -> str:
    """The most useful thing that can be said about a failed conversion.

    LibreOffice's stderr opens with fontconfig and dbus noise and ends with the
    actual complaint, so the *tail* is kept rather than the head. Some builds
    write the diagnosis to stdout instead, and some say nothing at all — hence
    the fallbacks, so an operator is never handed a message that trails off
    after a colon.
    """
    for stream in (stderr, stdout):
        text = (stream or b"").decode("utf-8", "replace").strip()
        if text:
            return text[-300:]
    return f"the converter exited {returncode} without saying why"


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

        # What the bytes are decides both how the file is produced for the
        # delegate and what lineage the result records. Decided before any
        # scratch directory exists, so a file this extractor will refuse costs
        # no directory at all — and so the two outcomes cannot drift apart, the
        # way they could when each branch assigned them separately.
        if suffix == ".rtf":
            if not head.startswith(_RTF_MAGIC):
                raise ExtractionError(
                    f"{path.name} is named .rtf but does not begin with an RTF header"
                )
            lineage, produce = "legacy-office", self._converted_to(path, target)
        elif head.startswith(_ZIP_MAGIC):
            # Already the modern format under a legacy name. The dump this
            # change answers held two such workbooks. Converting one would
            # be a lossy round trip for no reason.
            lineage, produce = "legacy-office-passthrough", self._copied_to(path, target)
        elif head.startswith(_OLE2_MAGIC) or (
            # RTF under a `.doc` name is ordinary Word and mail-merge
            # output, and LibreOffice converts it without complaint. Only
            # word-processor targets are widened: an RTF payload really is
            # unreadable as a workbook or a deck, so the refusal below stays
            # accurate for `.xls` and `.ppt`.
            target == "docx" and head.startswith(_RTF_MAGIC)
        ):
            lineage, produce = "legacy-office", self._converted_to(path, target)
        else:
            raise ExtractionError(
                f"{path.name} is named {suffix} but is neither an OLE2 nor an "
                "OOXML container"
            )

        delegated = deliver_via_scratch_directory(
            path,
            prefix="jackryan-legacy-",
            produce=produce,
            delegate=self._workbooks if target == "xlsx" else self._documents,
            read_as=f".{target}",
        )
        return Extraction(
            text=delegated.text,
            # The legacy type, because that is what the evidence is. The
            # conversion is how the text was obtained, not what was stored.
            media_type=LEGACY_SUFFIXES[suffix],
            extractor=f"{lineage}+{delegated.extractor}",
            metadata=delegated.metadata,
            # Carried rather than defaulted. Neither delegate sets either
            # today, so nothing changes now — but `refusals` is how this
            # project carries "what I could not read" upward, and silently
            # dropping it the day a delegate starts setting it would lose
            # exactly the disclosure it exists for.
            refusals=delegated.refusals,
            text_source=delegated.text_source,
        )

    def _converted_to(self, path: Path, target: str) -> Callable[[Path], Path]:
        """A producer that converts, deferred until a scratch directory exists.

        The conversion needs that directory for three things — the output, a
        per-call LibreOffice profile, and the result itself — which is why the
        shared helper hands one over rather than taking a finished file.
        """
        return lambda work: self._convert(path, target, work)

    def _copied_to(self, path: Path, target: str) -> Callable[[Path], Path]:
        """A producer that copies, for a file already in the modern format."""
        return lambda work: self._copy_as_target(path, target, work)

    def _copy_as_target(self, path: Path, target: str, work: Path) -> Path:
        """Copy the file under the suffix its content actually is.

        A delegate keys its media type off the path's suffix, so handing it the
        original `.xls` would raise a `KeyError` — which is not an
        `ExtractionError`, and would therefore end the whole ingest run rather
        than fail one document.

        The scratch name is `SCRATCH_STEM`, shared with the content-routing path
        in `router`, which needs it for the same reason and once spelled it out
        in a comment claiming "the same constant" while hardcoding its own copy.
        The argument for a fixed name is recorded where the constant lives.
        """
        destination = work / f"{SCRATCH_STEM}.{target}"
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
        try:
            out_dir.mkdir(exist_ok=True)
            profile.mkdir(exist_ok=True)
        except OSError as exc:
            raise ExtractionError(
                f"could not prepare a conversion directory for {path.name}: {exc}"
            ) from exc

        argv = [
            converter,
            # Per call, not shared: LibreOffice takes an exclusive lock on its
            # user profile, and ingestion runs in a thread pool.
            f"-env:UserInstallation={profile.as_uri()}",
            "--headless",
            "--convert-to",
            target,
            "--outdir",
            str(out_dir),
            # Absolute, and load-bearing: LibreOffice has no `--` end-of-options
            # marker, so a file named `--convert-to` or `-env:x` would otherwise
            # arrive as an option. `resolve()` guarantees a leading `/`, which
            # makes it an operand. Never pass a bare or relative name here.
            str(path.resolve()),
        ]
        try:
            completed = self._run_converter(argv)
        except subprocess.TimeoutExpired as exc:
            raise ExtractionError(
                f"converting {path.name} to .{target} exceeded {CONVERSION_TIMEOUT_S}s"
            ) from exc
        except OSError as exc:
            raise ExtractionError(
                f"could not run the converter for {path.name}: {exc}"
            ) from exc

        if completed.returncode != 0:
            raise ExtractionError(
                f"could not convert {path.name} to .{target}: "
                f"{_diagnosis(completed.returncode, completed.stderr, completed.stdout)}"
            )

        # The glob, not the exit status, is the real gate: LibreOffice exits 0
        # in some cases having written nothing at all.
        produced = sorted(out_dir.glob(f"*.{target}"))
        if not produced:
            raise ExtractionError(
                f"converting {path.name} to .{target} produced no output"
            )
        if len(produced) > 1:
            raise ExtractionError(
                f"converting {path.name} to .{target} produced {len(produced)} files "
                "where one was expected"
            )

        # The one artefact in this pipeline that no existing ceiling covers.
        # `MAX_FILE_BYTES` bounds what the caller handed us and the expansion
        # budget bounds container entries; both measure input. This measures what
        # the converter *wrote*, which is what the delegate then loads whole — a
        # bounded `.xls` can expand without bound. It is a separate constant for
        # the same reason `MAX_IMAGE_PIXELS` is: the quantity that costs the
        # memory is not the quantity any input ceiling measures.
        size = produced[0].stat().st_size
        if size > MAX_CONVERTED_BYTES:
            raise ExtractionError(
                f"converting {path.name} to .{target} produced {size} bytes, over the "
                f"{MAX_CONVERTED_BYTES}-byte limit; a small legacy file can expand "
                "without bound and the converted file is what gets loaded whole"
            )
        return produced[0]

    def _run_converter(self, argv: list[str]) -> subprocess.CompletedProcess[bytes]:
        """Run the converter in its own process group, and kill the group on timeout.

        `subprocess.run`'s own timeout kills a single pid, and the pid it holds is
        not the worker: `soffice` execs a launcher that spawns `soffice.bin`, and
        Debian's `libreoffice` goes through `oosplash`. Killing the launcher
        leaves the worker running — still burning CPU, still holding the profile
        lock, and still able to write into the scratch directory *after* the
        `finally` has removed it, which would leave converted evidence on disk.
        `start_new_session` puts the whole tree in one group so it dies together.
        """
        with subprocess.Popen(
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            # LibreOffice must never reach the parent's stdin: under
            # `jackryan serve-mcp` that channel belongs to the protocol.
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        ) as process:
            try:
                stdout, stderr = process.communicate(timeout=CONVERSION_TIMEOUT_S)
            except subprocess.TimeoutExpired:
                _kill_group(process)
                process.communicate()
                raise
        return subprocess.CompletedProcess(argv, process.returncode, stdout, stderr)
