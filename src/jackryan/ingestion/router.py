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
from .quality_gate import QualityGate


def has_usable_text(text: str) -> bool:
    """Whether `text` carries anything a reader could use.

    At least one letter or digit, in any script — so Cyrillic-only text and a
    page of figures both count, and whitespace with punctuation does not.

    The punctuation case is not hypothetical: an unconfigured recognition engine
    returns exactly that for a scan it cannot read. Nine characters of `.` and
    `:` pass an emptiness check, store, chunk and embed, and leave a document an
    analyst can list and can never find — which is worse than the extraction
    having failed outright.
    """
    return any(character.isalnum() for character in text)


class FormatRouter:
    def __init__(
        self,
        extractors: list[Extractor] | None = None,
        gate: QualityGate | None = None,
    ) -> None:
        self._extractors = (
            extractors if extractors is not None else default_extractors(gate)
        )

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
        if not has_usable_text(extraction.text) and not extraction.is_container:
            # A container is exempt: an archive's value is in its entries, and
            # refusing it would leave those entries with no parent to hang from.
            # Everything else with no text is an empty document, which is worse
            # than a failure because it looks ingested.
            raise ExtractionError(
                f"{path.name} produced no usable text; refusing to store an empty document"
            )
        return extraction
