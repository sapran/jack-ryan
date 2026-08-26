"""Selecting an extractor for a file.

The router owns selection so that no extractor has to know about another, and
so that adding a format is registering an extractor rather than editing a
branch here.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from .extractors import (
    Child,
    Extraction,
    ExtractionError,
    Extractor,
    default_extractors,
)


class FormatRouter:
    def __init__(self, extractors: list[Extractor] | None = None) -> None:
        self._extractors = extractors if extractors is not None else default_extractors()

    def extractor_for(self, path: Path) -> Extractor | None:
        for extractor in self._extractors:
            if extractor.accepts(path):
                return extractor
        return None

    def supported_suffixes(self) -> set[str]:
        # Derived from the registry rather than listed here, so registering an
        # extractor stays the only step needed to add a format.
        return {suffix for e in self._extractors for suffix in e.suffixes}

    def iter_children(self, path: Path) -> Iterator[Child]:
        """Yield what a container holds, one entry at a time.

        Empty for anything that is not a container, so a caller may ask without
        first working out what kind of file it has.
        """
        extractor = self.extractor_for(path)
        opener = getattr(extractor, "iter_children", None)
        if opener is None:
            return iter(())
        return opener(path)

    def extract(self, path: Path) -> Extraction:
        """Extract, or raise a typed error naming the file and its type."""
        extractor = self.extractor_for(path)
        if extractor is None:
            suffix = path.suffix.lower() or "(no extension)"
            raise ExtractionError(
                f"no extractor accepts {path.name}: nothing handles {suffix}"
            )
        extraction = extractor.extract(path)
        if not extraction.text.strip() and not extraction.is_container:
            # A container is exempt: an archive's value is in its entries, and
            # refusing it would leave those entries with no parent to hang from.
            # Everything else with no text is an empty document, which is worse
            # than a failure because it looks ingested.
            raise ExtractionError(
                f"{path.name} produced no usable text; refusing to store an empty document"
            )
        return extraction
