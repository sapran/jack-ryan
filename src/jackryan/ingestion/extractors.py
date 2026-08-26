"""Extractors and the result they all produce.

An extractor turns one file into text. Which extractor runs is the router's
business; what comes out is the same shape regardless, so nothing downstream
depends on how a given format was read.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from ..errors import JackRyanError


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


DOCLING_SUFFIXES = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".html": "text/html",
    ".htm": "text/html",
    ".md": "text/markdown",
    ".markdown": "text/markdown",
}


class DoclingExtractor:
    """The default engine, covering PDF, Office, and markup formats.

    Docling is imported lazily: it pulls a large stack, and a caller that only
    ever ingests plain text should not pay for it at import time.

    Markdown, HTML, DOCX and PPTX are parsed structurally and need no model.
    PDF resolves layout with models fetched on first use, which is why an
    offline instance wants them present in the image.
    """

    name = "docling"
    suffixes = DOCLING_SUFFIXES

    def __init__(self) -> None:
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
            media_type=DOCLING_SUFFIXES[path.suffix.lower()],
            extractor=self.name,
        )


def default_extractors() -> list[Extractor]:
    """The registry, in consultation order.

    Plain text first: it is unambiguous and needs no engine, so there is no
    reason to hand it to one. Containers before the document engine, so an
    archive is expanded rather than handed to something that would read it as
    one opaque file.
    """
    from .containers import TarExtractor, ZipExtractor
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
        SpreadsheetExtractor(),
        DoclingExtractor(),
    ]
