"""Extractors and the result they all produce.

An extractor turns one file into text. Which extractor runs is the router's
business; what comes out is the same shape regardless, so nothing downstream
depends on how a given format was read.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from ..errors import JackRyanError


class ExtractionError(JackRyanError):
    """A file could not be turned into usable text."""

    code = "extraction_failed"


@dataclass(frozen=True)
class Extraction:
    """What every extractor returns, whatever it read."""

    text: str
    media_type: str
    extractor: str
    metadata: dict[str, str] = field(default_factory=dict)


class Extractor(Protocol):
    """One format family's reader."""

    name: str

    def accepts(self, path: Path) -> bool:
        """Whether this extractor will take the file."""
        ...

    def extract(self, path: Path) -> Extraction:
        """Read the file, or raise ExtractionError."""
        ...


_TEXT_SUFFIXES = {".txt": "text/plain", ".text": "text/plain", ".log": "text/plain"}


class PlainTextExtractor:
    """Reads plain text directly.

    Kept separate from the engine below so that the simplest possible file
    never depends on a heavyweight document pipeline being importable.
    """

    name = "plaintext"

    def accepts(self, path: Path) -> bool:
        return path.suffix.lower() in _TEXT_SUFFIXES

    def extract(self, path: Path) -> Extraction:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            raise ExtractionError(f"could not read {path.name}: {exc}") from exc
        return Extraction(
            text=text,
            media_type=_TEXT_SUFFIXES[path.suffix.lower()],
            extractor=self.name,
        )


_DOCLING_SUFFIXES = {
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

    def __init__(self) -> None:
        self._converter = None

    def accepts(self, path: Path) -> bool:
        return path.suffix.lower() in _DOCLING_SUFFIXES

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
            media_type=_DOCLING_SUFFIXES[path.suffix.lower()],
            extractor=self.name,
        )


def default_extractors() -> list[Extractor]:
    """The registry, in consultation order.

    Plain text first: it is unambiguous and needs no engine, so there is no
    reason to hand it to one.
    """
    return [PlainTextExtractor(), DoclingExtractor()]
