"""Reading a page-bearing document, escalating only as far as it has to.

A born-digital document has its text on the page and needs nothing else. A scan
has pages with nothing readable on them, and needs recognition. A minority needs
a vision model. The gate tries them in that order and stops at the first reading
that clears a floor, so the common case pays for the cheapest rung and the
expensive ones stay rare.

The rungs are kept here rather than inside an extractor because two extractors
need them — PDFs and page images — and because "how hard did we have to work to
read this" is a policy, where an extractor is a reader.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..errors import JackRyanError

TEXT_LAYER = "text-layer"
OCR = "ocr"
VLM = "vlm"
NATIVE = "native"
"""How a document's text was obtained.

``native`` is for formats with no page images at all — a spreadsheet, a message,
a markup file. There is nothing for recognition to read in one, so it is never
escalated and never carries one of the other three.
"""

TEXT_SOURCES = (TEXT_LAYER, OCR, VLM, NATIVE)


class RecognitionError(JackRyanError):
    """A recognition engine or vision model could not be built or run."""

    code = "recognition_failed"


@dataclass(frozen=True)
class Reading:
    """One rung's attempt at a document."""

    text: str
    source: str
    pages: int

    @property
    def chars_per_page(self) -> float:
        return len(self.text.strip()) / max(self.pages, 1)


# A rung reader turns a file into text and a page count. Injectable so the
# ladder can be tested without a model: what is worth testing here is the
# escalation policy, not docling.
RungReader = Callable[[Path], tuple[str, int]]


class QualityGate:
    """The escalation ladder for one instance's configuration."""

    def __init__(
        self,
        *,
        ocr_engine: str,
        ocr_language: str,
        min_chars_per_page: int,
        vlm_model: str = "",
        readers: dict[str, RungReader] | None = None,
    ) -> None:
        self._engine = ocr_engine
        self._language = ocr_language
        self._floor = min_chars_per_page
        self._vlm_model = vlm_model
        self._readers = readers
        self._converters: dict[str, Any] = {}
        self._verified = False

    @classmethod
    def from_profile(cls, profile, readers: dict[str, RungReader] | None = None) -> QualityGate:
        return cls(
            ocr_engine=profile.ocr_engine,
            ocr_language=profile.ocr_language,
            min_chars_per_page=profile.min_chars_per_page,
            vlm_model=profile.vlm_model,
            readers=readers,
        )

    # -- the ladder ----------------------------------------------------------

    def rungs(self) -> tuple[str, ...]:
        """Which rungs exist, in order.

        The vision rung exists only when a model is configured. Absent, it is
        not a rung that fails — it is a rung that is not there, so nothing loads
        weights to discover that it is switched off.
        """
        if self._vlm_model:
            return (TEXT_LAYER, OCR, VLM)
        return (TEXT_LAYER, OCR)

    def verify(self) -> None:
        """Build the configured engine, once, before any document is read.

        Called at the start of an ingest run rather than at process startup: an
        instance that only searches never needs a recognition engine, and making
        every `jackryan status` load one would cost seconds and a model download
        for nothing. A run is the unit that matters, because a run that stops
        part way has already stored documents, and which ones depends on the
        order the files happened to be walked.

        The vision rung is checked more weakly, and deliberately: its spec name
        is resolved, but its weights are not loaded. They are gigabytes, and the
        rung is reached only by documents that defeated the two above it. So a
        vision model that resolves but cannot run fails on the first document
        that needs it, not here — stated plainly because the recognition engine
        below makes the stronger promise and the difference matters.
        """
        if self._verified:
            return
        if self._readers is None:
            check_engine(self._engine, self._language)
            if self._vlm_model:
                resolve_vlm_spec(self._vlm_model)
        self._verified = True

    def clears_floor(self, reading: Reading) -> bool:
        return reading.chars_per_page >= self._floor

    def read(self, path: Path) -> Reading:
        """Read `path`, escalating until something clears the floor.

        When nothing does, the richest attempt is returned rather than the last
        one: more recovered text is more evidence, and a document that is thin
        on every rung is refused a layer up by the usable-text rule, not here.

        A rung that *raises* fails the whole reading rather than falling back to
        the thin attempt above it. That attempt is below the floor by
        definition — it is why the rung ran — so keeping it would store a
        near-empty document in place of an error, which is the failure this
        whole gate exists to stop. A failed read is retryable; a stored empty
        document is not.
        """
        attempts: list[Reading] = []
        for source in self.rungs():
            text, pages = self._read_at(source, path)
            reading = Reading(text=text, source=source, pages=pages)
            if self.clears_floor(reading):
                return reading
            attempts.append(reading)
        return max(attempts, key=lambda r: len(r.text.strip()))

    def _read_at(self, source: str, path: Path) -> tuple[str, int]:
        if self._readers is not None:
            return self._readers[source](path)
        return self._convert(source, path)

    # -- docling -------------------------------------------------------------

    def _convert(self, source: str, path: Path) -> tuple[str, int]:
        converter = self._converter_for(source)
        try:
            result = converter.convert(str(path))
            document = result.document
            return document.export_to_markdown(), _page_count(document)
        except Exception as exc:
            raise RecognitionError(
                f"could not read {path.name} at the {source} stage: "
                f"{type(exc).__name__}: {exc}"
            ) from exc

    def _converter_for(self, source: str) -> Any:
        """Build one converter per rung, once.

        Cached because constructing a `DocumentConverter` loads layout models,
        and the gate is held for the lifetime of the process.
        """
        converter = self._converters.get(source)
        if converter is None:
            converter = build_converter(
                source,
                engine=self._engine,
                language=self._language,
                vlm_model=self._vlm_model,
            )
            self._converters[source] = converter
        return converter


def _page_count(document) -> int:
    """How many pages the reading covered.

    One when the format reports none, so the floor stays a per-page measure for
    a single image as much as for a report.
    """
    try:
        pages = document.num_pages()
    except Exception:
        return 1
    return max(int(pages or 1), 1)


# -- engine construction -----------------------------------------------------
#
# docling is imported inside these functions, not at module scope: it costs
# seconds to import and pulls the whole model stack, and a caller that only
# ingests plain text should never pay for it.


def ocr_options_for(engine: str, language: str):
    """The docling OCR options for one engine and one recognition language.

    Never `auto`. `OcrAutoModel` picks by host operating system, forwards only
    `mode` to whatever it picked — dropping the language entirely — and, with no
    engine importable, logs a warning and yields the pages unchanged. Refused at
    configuration load; refused again here, because this function is reachable
    from tests and from anything that builds a gate directly.
    """
    from docling.datamodel.pipeline_options import (
        EasyOcrOptions,
        OcrMacOptions,
        RapidOcrOptions,
        TesseractCliOcrOptions,
    )

    if engine == "auto":
        raise RecognitionError(
            "the recognition engine must be named, not 'auto': it is chosen by host "
            "operating system and discards the configured language"
        )

    classes = {
        "rapidocr": RapidOcrOptions,
        "easyocr": EasyOcrOptions,
        "tesseract": TesseractCliOcrOptions,
        "ocrmac": OcrMacOptions,
    }
    if engine not in classes:
        raise RecognitionError(
            f"unknown recognition engine {engine!r}; expected one of {', '.join(classes)}"
        )
    return classes[engine](lang=[language])


def resolve_vlm_spec(vlm_model: str):
    """The docling model spec a `vlm_model` name refers to.

    Resolving the name is cheap and loads no weights, which is why `verify` can
    afford it at the start of every ingest run.
    """
    from docling.datamodel import vlm_model_specs

    spec = getattr(vlm_model_specs, vlm_model, None)
    if spec is None:
        raise RecognitionError(
            f"vlm_model names {vlm_model!r}, which is not a docling model spec. "
            "Set vlm_model to a name from docling.datamodel.vlm_model_specs, for "
            "example GRANITEDOCLING_TRANSFORMERS, or leave it empty to switch the "
            "vision rung off."
        )
    return spec


def build_converter(source: str, *, engine: str, language: str, vlm_model: str = ""):
    """A docling converter configured for one rung.

    Both PDF and image inputs are registered, so a page that arrives as a JPEG
    is read by the same ladder as the same page inside a PDF.
    """
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions, VlmPipelineOptions
    from docling.document_converter import (
        DocumentConverter,
        ImageFormatOption,
        PdfFormatOption,
    )

    if source == VLM:
        from docling.pipeline.vlm_pipeline import VlmPipeline

        spec = resolve_vlm_spec(vlm_model)
        pipeline_cls = VlmPipeline
        pipeline_options = VlmPipelineOptions(vlm_options=spec)
    else:
        options = PdfPipelineOptions()
        # Rung one turns recognition off. docling's own default is do_ocr=True,
        # which is why a born-digital PDF pays for recognition it does not need
        # today — and why there is currently no honest way to say whether a
        # document's text came off the page or out of an OCR model.
        options.do_ocr = source == OCR
        if options.do_ocr:
            options.ocr_options = ocr_options_for(engine, language)
        pipeline_cls = None
        pipeline_options = options

    pdf_option = (
        PdfFormatOption(pipeline_cls=pipeline_cls, pipeline_options=pipeline_options)
        if pipeline_cls is not None
        else PdfFormatOption(pipeline_options=pipeline_options)
    )
    # An image needs its own format option, not the PDF one. Both run the same
    # pipeline, but a PdfFormatOption carries a PDF backend, and handing that to
    # an image is deprecated — docling corrects it and warns, which is a
    # correction to stop relying on.
    image_option = (
        ImageFormatOption(pipeline_cls=pipeline_cls, pipeline_options=pipeline_options)
        if pipeline_cls is not None
        else ImageFormatOption(pipeline_options=pipeline_options)
    )
    return DocumentConverter(
        format_options={InputFormat.PDF: pdf_option, InputFormat.IMAGE: image_option}
    )


def check_engine(engine: str, language: str) -> None:
    """Build the configured engine's pipeline, so a misconfiguration fails at startup.

    The pipeline is *initialised*, not merely constructed. A `DocumentConverter`
    builds its pipelines lazily, so constructing one with `ocr_language='klingon'`
    returns an object quite happily and fails on the first scan instead — which is
    the fail-open this whole capability exists to close. `initialize_pipeline`
    builds the recognition model, which is what actually answers whether the
    engine and the language work here; it is also what raises, naming every
    language the backbone serves.

    Raises `RecognitionError` naming the setting. It is never caught into a
    fallback: an instance that quietly reads scans without recognition ingests
    them as empty documents, which is unrecoverable without noticing.
    """
    try:
        from docling.datamodel.base_models import InputFormat

        converter = build_converter(OCR, engine=engine, language=language)
        converter.initialize_pipeline(InputFormat.PDF)
    except RecognitionError:
        raise
    except Exception as exc:
        raise RecognitionError(
            f"the recognition engine ocr_engine={engine!r} with ocr_language={language!r} "
            f"could not be built ({type(exc).__name__}: {exc}). Either fix the setting, or "
            "name an engine this environment can run — recognition is not switched off on "
            "failure, because that would ingest every scan as an empty document."
        ) from exc

