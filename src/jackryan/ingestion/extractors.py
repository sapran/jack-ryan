"""Extractors and the result they all produce.

An extractor turns one file into text. Which extractor runs is the router's
business; what comes out is the same shape regardless, so nothing downstream
depends on how a given format was read.
"""

from __future__ import annotations

import shutil
import tempfile
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from ..config import Profile
from ..errors import JackRyanError
from .quality_gate import NATIVE, QualityGate


#: The name a file is copied under when it has to be handed to a delegate as
#: something other than what it is called on disk — the content-routing path in
#: `router`, and the legacy-Office conversion path in `legacy_office`.
#:
#: Fixed rather than derived from the operator's filename. Nothing downstream
#: reads it — a delegate keys only off the suffix, and every error on these
#: paths is relabelled with the real `path.name` — while a derived stem lets the
#: input decide the output name: appending a suffix to an extensionless 251-byte
#: name exceeds the 255-byte component limit, and a workbook named `..xlsx` has
#: stem `.`, landing as `..xlsx`, whose suffix openpyxl then refuses.
#:
#: Here rather than in either caller because both need it and neither may import
#: the other: `extractors` is already imported by `router` and by
#: `legacy_office`, while `router` importing `legacy_office` would close a cycle.
#: `router` re-exports the name, which is where the tests read it from.
SCRATCH_STEM = "source"


class ExtractionError(JackRyanError):
    """A file could not be turned into usable text."""

    code = "extraction_failed"


@dataclass(frozen=True)
class Child:
    """One file found inside another.

    Carries bytes rather than a path because it has no path: it exists only
    inside its container until the pipeline materialises it. The name is what
    the container called it, and is attacker-controlled like any other document
    metadata.
    """

    name: str
    data: bytes


@dataclass(frozen=True)
class Extraction:
    """What every extractor returns, whatever it read.

    `is_container` says there is more inside to expand; the entries themselves
    are fetched separately through `iter_children`, one at a time. They are
    deliberately *not* carried here: a container holding ten thousand entries
    would otherwise be fully resident in memory before the expansion budget —
    which lives a layer up, in the service — ever got a chance to refuse it.
    """

    text: str
    media_type: str
    extractor: str
    metadata: dict[str, str] = field(default_factory=dict)
    is_container: bool = False
    refusals: tuple[str, ...] = ()
    text_source: str = NATIVE
    """Which rung produced the text.

    ``native`` for every format with no page images — there is nothing for
    recognition to read in a spreadsheet or a message, so it is never escalated.
    A page-bearing format carries the rung the quality gate stopped at instead.
    """


class Extractor(Protocol):
    """One format family's reader."""

    name: str
    suffixes: Mapping[str, str]

    def accepts(self, path: Path) -> bool:
        """Whether this extractor will take the file."""
        ...

    def extract(self, path: Path) -> Extraction:
        """Read the file, or raise ExtractionError."""
        ...


class ContainerExtractor(Extractor, Protocol):
    """An extractor for a file that holds other files.

    Children are yielded one at a time so that a container's entries are never
    all resident at once, and so the caller can stop partway — which is what
    lets an expansion budget bound a hostile archive instead of discovering it
    too late.

    An implementation reads its entries and nothing more: it never routes or
    extracts what it finds. That is the pipeline's job, and keeping it there is
    what makes a format supported inside a container exactly when it is
    supported outside one.
    """

    def iter_children(self, path: Path) -> Iterator[Child]:
        """Yield the entries this file holds, one at a time."""
        ...


TEXT_SUFFIXES = {".txt": "text/plain", ".text": "text/plain", ".log": "text/plain"}


class PlainTextExtractor:
    """Reads plain text directly.

    Kept separate from the engine below so that the simplest possible file
    never depends on a heavyweight document pipeline being importable.
    """

    name = "plaintext"
    suffixes = TEXT_SUFFIXES

    def accepts(self, path: Path) -> bool:
        return path.suffix.lower() in TEXT_SUFFIXES

    def extract(self, path: Path) -> Extraction:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            raise ExtractionError(f"could not read {path.name}: {exc}") from exc
        return Extraction(
            text=text,
            media_type=TEXT_SUFFIXES[path.suffix.lower()],
            extractor=self.name,
        )


# Formats docling parses structurally. None of them is made of page images, so
# recognition would have nothing to read and they are never escalated.
MARKUP_SUFFIXES = {
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".html": "text/html",
    ".htm": "text/html",
    ".md": "text/markdown",
    ".markdown": "text/markdown",
}

# Formats made of pages, which may or may not carry their own text. These go
# through the quality gate, which decides how hard it has to work to read them.
PAGE_SUFFIXES = {".pdf": "application/pdf"}

IMAGE_SUFFIXES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
    ".bmp": "image/bmp",
    ".webp": "image/webp",
}

DOCLING_SUFFIXES = {**MARKUP_SUFFIXES, **PAGE_SUFFIXES}


class _GatedReader:
    """Shared machinery for the two extractors that read pages.

    Both hold a quality gate and report the rung it stopped at. Kept in one
    place so the two cannot drift into reading pages differently: the same page
    should extract the same way whether it arrived inside a PDF or as a
    photograph of it.
    """

    def __init__(self, gate: QualityGate | None = None) -> None:
        self._gate = gate or QualityGate(
            ocr_engine=Profile.ocr_engine,
            ocr_language=Profile.ocr_language,
            min_chars_per_page=Profile.min_chars_per_page,
        )

    def _read_pages(self, path: Path, media_type: str, name: str) -> Extraction:
        try:
            reading = self._gate.read(path)
        except ExtractionError:
            raise
        except Exception as exc:
            raise ExtractionError(
                f"could not extract {path.name} with docling: {type(exc).__name__}: {exc}"
            ) from exc
        return Extraction(
            text=reading.text,
            media_type=media_type,
            extractor=name,
            text_source=reading.source,
        )


class DoclingExtractor(_GatedReader):
    """The default engine, covering PDF, Office, and markup formats.

    Docling is imported lazily: it pulls a large stack, and a caller that only
    ever ingests plain text should not pay for it at import time.

    Markdown, HTML, DOCX and PPTX are parsed structurally and need no model, so
    they are read once and report ``native``. A PDF is made of pages, so it goes
    through the quality gate: its text layer is read first, and recognition is
    reached only when there is nothing on it.
    """

    name = "docling"
    suffixes = DOCLING_SUFFIXES

    def __init__(self, gate: QualityGate | None = None) -> None:
        super().__init__(gate)
        self._converter = None

    def accepts(self, path: Path) -> bool:
        return path.suffix.lower() in DOCLING_SUFFIXES

    def _get_converter(self):
        if self._converter is None:
            try:
                from docling.document_converter import DocumentConverter
            except ImportError as exc:  # pragma: no cover - packaging failure
                raise ExtractionError(
                    "the docling extraction engine is not installed"
                ) from exc
            self._converter = DocumentConverter()
        return self._converter

    def extract(self, path: Path) -> Extraction:
        suffix = path.suffix.lower()
        if suffix in PAGE_SUFFIXES:
            return self._read_pages(path, PAGE_SUFFIXES[suffix], self.name)
        try:
            result = self._get_converter().convert(str(path))
            text = result.document.export_to_markdown()
        except ExtractionError:
            raise
        except Exception as exc:
            raise ExtractionError(
                f"could not extract {path.name} with docling: {type(exc).__name__}: {exc}"
            ) from exc
        return Extraction(
            text=text,
            media_type=MARKUP_SUFFIXES[suffix],
            extractor=self.name,
        )


# A ceiling on how large a picture may be once decoded. Roughly an A4 page at
# 1000 dpi, so far above any real scan and far below what exhausts a host.
#
# It is a separate bound because every other limit in this pipeline is measured
# in *file* bytes — MAX_FILE_BYTES, the expansion budget's byte ceiling — and
# file bytes are exactly what a decompression bomb makes meaningless. A 60KB PNG
# can declare 60000x60000 pixels and cost 10GB to decode, which no byte ceiling
# anywhere would refuse. Images became ingestable in this change, so the
# quantity that matters became reachable for the first time.
MAX_IMAGE_PIXELS = 80_000_000


class ImageExtractor(_GatedReader):
    """A page that arrived as an image rather than inside a document.

    A photographed or scanned page is how a large share of real evidence
    arrives, and until now no extractor accepted one. It reads through the same
    gate as a PDF page, so what a page yields does not depend on the wrapper it
    turned up in.
    """

    name = "image"
    suffixes = IMAGE_SUFFIXES

    def accepts(self, path: Path) -> bool:
        return path.suffix.lower() in IMAGE_SUFFIXES

    def extract(self, path: Path) -> Extraction:
        self._refuse_a_bomb(path)
        return self._read_pages(path, IMAGE_SUFFIXES[path.suffix.lower()], self.name)

    def _refuse_a_bomb(self, path: Path) -> None:
        """Refuse a picture whose declared size would cost too much to decode.

        Read from the header, which is cheap: Pillow's `open` is lazy and gives
        the dimensions without decoding a single pixel. The check happens before
        the gate rather than inside it because the gate would otherwise decode
        the same file once per rung.
        """
        try:
            from PIL import Image
        except ImportError:  # pragma: no cover - packaging failure
            raise ExtractionError(
                "the image reader is not installed"
            ) from None

        try:
            # Pillow raises its own bomb error at a lower default; ours is the
            # number this project stands behind, so set it aside and decide here.
            previous = Image.MAX_IMAGE_PIXELS
            Image.MAX_IMAGE_PIXELS = None
            try:
                with Image.open(path) as image:
                    width, height = image.size
            finally:
                Image.MAX_IMAGE_PIXELS = previous
        except ExtractionError:
            raise
        except Exception as exc:
            raise ExtractionError(
                f"could not read the image header of {path.name}: "
                f"{type(exc).__name__}: {exc}"
            ) from exc

        pixels = width * height
        if pixels > MAX_IMAGE_PIXELS:
            raise ExtractionError(
                f"{path.name} declares {width}x{height} = {pixels} pixels, over the "
                f"{MAX_IMAGE_PIXELS}-pixel limit. A small file can declare a very large "
                "picture, and decoding it is what costs the memory, so this is bounded "
                "separately from the file size."
            )


def deliver_via_scratch_directory(
    path: Path,
    *,
    prefix: str,
    produce: Callable[[Path], Path],
    delegate: Extractor,
    read_as: str,
) -> Extraction:
    """Hand a delegate a file it can read, from a directory that always goes away.

    Two paths need this and had written it twice: `router` when a file's name
    defeats the registry and its content says what it is, and `legacy_office`
    when a binary Office file has to be converted before anything can read it.
    Both make a scratch directory, put a file in it under a name the delegate
    will accept, delegate, relabel the failure with the name the operator
    actually has, and remove the directory whatever happened.

    `produce` is the caller's, and that is the whole reason this takes a callable
    rather than a source path. The two do genuinely different work inside the
    directory: one copies a file into it, the other runs a converter that writes
    an output directory and a private profile directory beside the result. A
    helper that took a finished path could serve only the first.

    `prefix` stays the caller's too. `tests/test_content_routing.py` globs
    `jackryan-routed-*` to prove cleanup and separately asserts that string never
    reaches an error message, so the two prefixes are load-bearing in opposite
    directions and must not be unified.

    The teardown is the point. `docs/handover.md` records two defects found in
    exactly this shape — a `mkdtemp` outside every `try`, and a converter still
    writing into the directory after the `finally` had removed it — which is the
    argument for one implementation rather than two.

    `tempfile.mkdtemp` is called through the module, not imported by name, so a
    test that patches `tempfile.mkdtemp` still observes the directory this
    allocates.
    """
    try:
        work = Path(tempfile.mkdtemp(prefix=prefix))
    except OSError as exc:
        raise ExtractionError(
            f"could not make a scratch directory for {path.name}: {exc}"
        ) from exc

    try:
        source = produce(work)
        try:
            return delegate.extract(source)
        except ExtractionError as exc:
            # Named for the file the operator has, not the scratch copy they
            # will never see.
            raise ExtractionError(f"{path.name}, read as {read_as}: {exc}") from exc
        except Exception as exc:
            # A delegate is supposed to raise only `ExtractionError`, and not all
            # of them honour it: `SpreadsheetExtractor`'s lazy row iteration
            # surfaces a bare `ParseError` on a workbook truncated mid-sheet,
            # which would leave `_ingest_work` and end the run. Narrowed to
            # `Exception` rather than `BaseException` so the test gate's rung
            # sentinel still escapes and can still fail a test loudly.
            raise ExtractionError(
                f"{path.name}, read as {read_as}: {type(exc).__name__}: {exc}"
            ) from exc
    finally:
        shutil.rmtree(work, ignore_errors=True)


def default_extractors(gate: QualityGate | None = None) -> list[Extractor]:
    """The registry, in consultation order.

    Plain text first: it is unambiguous and needs no engine, so there is no
    reason to hand it to one. Containers before the document engine, so an
    archive is expanded rather than handed to something that would read it as
    one opaque file.

    The gate is passed to the two extractors that read pages. Absent, they build
    one from the profile defaults, so a router constructed with no arguments
    still works — which is what the tests and any direct caller rely on.
    """
    from .containers import RarExtractor, TarExtractor, ZipExtractor
    from .legacy_office import LegacyOfficeExtractor
    from .mail import EmlExtractor, MboxExtractor, MsgExtractor
    from .sheets import DelimitedExtractor, SpreadsheetExtractor

    return [
        PlainTextExtractor(),
        DelimitedExtractor(),
        EmlExtractor(),
        MboxExtractor(),
        MsgExtractor(),
        ZipExtractor(),
        TarExtractor(),
        RarExtractor(),
        SpreadsheetExtractor(),
        LegacyOfficeExtractor(gate),
        ImageExtractor(gate),
        DoclingExtractor(gate),
    ]
