"""Selecting an extractor for a file.

The router owns selection so that no extractor has to know about another, and
so that adding a format is registering an extractor rather than editing a
branch here.
"""

from __future__ import annotations

from pathlib import Path

from .extractors import Extraction, ExtractionError, Extractor, default_extractors


class FormatRouter:
    def __init__(self, extractors: list[Extractor] | None = None) -> None:
        self._extractors = extractors if extractors is not None else default_extractors()

    def extractor_for(self, path: Path) -> Extractor | None:
        for extractor in self._extractors:
            if extractor.accepts(path):
                return extractor
        return None

    def supported_suffixes(self) -> set[str]:
        from .extractors import _DOCLING_SUFFIXES, _TEXT_SUFFIXES

        return set(_TEXT_SUFFIXES) | set(_DOCLING_SUFFIXES)

    def extract(self, path: Path) -> Extraction:
        """Extract, or raise a typed error naming the file and its type."""
        extractor = self.extractor_for(path)
        if extractor is None:
            suffix = path.suffix.lower() or "(no extension)"
            raise ExtractionError(
                f"no extractor accepts {path.name}: nothing handles {suffix}"
            )
        extraction = extractor.extract(path)
        if not extraction.text.strip():
            raise ExtractionError(
                f"{path.name} produced no usable text; refusing to store an empty document"
            )
        return extraction
