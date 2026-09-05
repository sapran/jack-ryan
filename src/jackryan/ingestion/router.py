"""Selecting an extractor for a file.

The router owns selection so that no extractor has to know about another, and
so that adding a format is registering an extractor rather than editing a
branch here.

Selection is by the file's declared type first. Where the registry claims that
type, nothing else is consulted — content routing cannot change how a file that
ingests today is read. Where it claims nothing, the file's bytes are read, and a
format they positively identify is routed to its extractor rather than refused.
That fallback exists because a real dump carries names that defeat the registry:
quotes baked into a filename, or no extension at all.
"""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path

from .extractors import (
    Child,
    Extraction,
    ExtractionError,
    Extractor,
    deliver_via_scratch_directory,
    # Re-exported: this module's callers and its tests read the name from
    # here, and it is shared with `legacy_office`, which may not import it
    # from here without closing a cycle.
    SCRATCH_STEM,
    default_extractors,
)
from ..config import Profile
from .quality_gate import QualityGate, content_of
from .sniffing import sniff_suffix

#: Lineage marker for a document read as something other than its name, joined
#: to the delegate's own name as `content-routed+docling`. Mirrors
#: `legacy-office+<delegate>`, so every route a document could have taken is
#: legible in one field and content-routed documents are one query away.
CONTENT_ROUTED = "content-routed"



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
    return any(character.isalnum() for character in content_of(text))


class FormatRouter:
    def __init__(
        self,
        extractors: list[Extractor] | None = None,
        gate: QualityGate | None = None,
    ) -> None:
        # The router owns the gate, and anything that needs to verify the
        # engine asks the router for it. One object, one answer: a service
        # holding its own copy could verify one engine while the extractors
        # read with another.
        self._gate = gate or QualityGate.from_profile(Profile(name="default"))
        self._extractors = (
            extractors if extractors is not None else default_extractors(self._gate)
        )

    @property
    def gate(self) -> QualityGate:
        """The quality gate this router's extractors read through."""
        return self._gate

    def _resolve(self, path: Path) -> tuple[Extractor | None, str | None]:
        """The extractor that will read this file, and the type it resolved as.

        The resolved type is `None` whenever selection came from the file's own
        name, which is the ordinary case and the signal to `extract` that the
        file may be handed over untouched. It is a suffix only when the registry
        claimed nothing and the content decided instead.

        One resolution, used by everything that asks. `extractor_for` and
        `extract` are both callers, and the service layer skips a file whose
        `extractor_for` is `None` before `extract` is ever reached — so a
        fallback known to one and not the other would be a fallback that never
        runs on a folder walk, which is the case it exists for.
        """
        for extractor in self._extractors:
            if extractor.accepts(path):
                return extractor, None

        sniffed = sniff_suffix(path)
        if sniffed is None:
            return None, None
        # Asked about the name the delegate is actually about to be handed — the
        # scratch copy — rather than about membership of its declared mapping.
        # The two diverge: `TarExtractor` declares `.gz`, `.bz2` and `.xz` but
        # its `accepts` refuses them unless a `.tar` sits underneath. Membership
        # would hand it a file it had already said it would not take, and the
        # failure would arrive as a per-document error instead of the honest
        # refusal below.
        candidate = Path(f"{SCRATCH_STEM}{sniffed}")
        for extractor in self._extractors:
            if extractor.accepts(candidate):
                return extractor, sniffed
        # A signature no extractor will take. A test forbids this combination
        # existing at all; refusing here keeps it a refusal rather than a crash
        # if one is ever added.
        return None, None

    def extractor_for(self, path: Path) -> Extractor | None:
        """Which extractor will read this file, by name or by content."""
        return self._resolve(path)[0]

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
        extractor, resolved = self._resolve(path)
        if extractor is None:
            suffix = path.suffix.lower() or "(no extension)"
            raise ExtractionError(
                f"no extractor accepts {path.name}: nothing handles {suffix}"
            )
        if resolved is None:
            extraction = extractor.extract(path)
        else:
            extraction = self._extract_as(extractor, path, resolved)
        if not has_usable_text(extraction.text) and not extraction.is_container:
            # A container is exempt: an archive's value is in its entries, and
            # refusing it would leave those entries with no parent to hang from.
            # Everything else with no text is an empty document, which is worse
            # than a failure because it looks ingested.
            raise ExtractionError(
                f"{path.name} produced no usable text; refusing to store an empty document"
            )
        return extraction

    def _extract_as(
        self, extractor: Extractor, path: Path, suffix: str
    ) -> Extraction:
        """Read a file as the type its content identified, not as it is named.

        Every extractor keys its media type off `path.suffix` — a `KeyError`
        that is not an `ExtractionError`, so it would end the whole run instead
        of failing one document. The file is therefore copied into a scratch
        directory under the resolved suffix and the copy is handed over.

        The scratch directory, the delegation and the relabelling are
        `deliver_via_scratch_directory`, shared with the legacy-Office path,
        which needs the same shape for the same reason. What stays here is what
        is actually this path's: the copy, and the lineage marker.
        """

        def copy_into(work: Path) -> Path:
            # One definition of the scratch name, shared with the `accepts`
            # probe in `_resolve` — so the extractor chosen is the one asked
            # about the exact name it is handed.
            source = work / f"{SCRATCH_STEM}{suffix}"
            try:
                shutil.copy2(path, source)
            except OSError as exc:
                raise ExtractionError(
                    f"could not copy {path.name} to read it as {suffix}: {exc}"
                ) from exc
            return source

        delegated = deliver_via_scratch_directory(
            path,
            prefix="jackryan-routed-",
            produce=copy_into,
            delegate=extractor,
            read_as=suffix,
        )
        # `replace` rather than a fresh `Extraction`: every other field —
        # media type, metadata, refusals, `text_source`, `is_container` —
        # is the delegate's answer and is carried rather than defaulted.
        # The media type especially: it is what the evidence is, and routing
        # is only how it was found.
        return replace(delegated, extractor=f"{CONTENT_ROUTED}+{delegated.extractor}")
