"""The router selects an extractor; extractors normalise what they read."""

from __future__ import annotations

from pathlib import Path

import pytest

from jackryan.ingestion.extractors import (
    DoclingExtractor,
    ExtractionError,
    PlainTextExtractor,
)
from jackryan.ingestion.router import FormatRouter


def test_plain_text_needs_no_engine(tmp_path):
    path = tmp_path / "note.txt"
    path.write_text("Plain content.", encoding="utf-8")
    result = PlainTextExtractor().extract(path)
    assert result.text == "Plain content."
    assert result.extractor == "plaintext"
    assert result.media_type == "text/plain"


@pytest.mark.parametrize(
    "name,expected",
    [
        ("a.txt", "plaintext"),
        ("a.log", "plaintext"),
        ("a.pdf", "docling"),
        ("a.docx", "docling"),
        ("a.pptx", "docling"),
        ("a.html", "docling"),
        ("a.md", "docling"),
    ],
)
def test_router_selects_the_right_extractor(name, expected):
    chosen = FormatRouter().extractor_for(Path(name))
    assert chosen is not None and chosen.name == expected


def test_unsupported_format_has_no_extractor():
    assert FormatRouter().extractor_for(Path("archive.xyz")) is None


def test_unsupported_format_is_refused_with_its_type(tmp_path):
    path = tmp_path / "data.xyz"
    path.write_text("content", encoding="utf-8")
    with pytest.raises(ExtractionError) as exc:
        FormatRouter().extract(path)
    assert "data.xyz" in str(exc.value) and ".xyz" in str(exc.value)


def test_a_file_with_no_usable_text_is_refused(tmp_path):
    path = tmp_path / "blank.txt"
    path.write_text("   \n\n  ", encoding="utf-8")
    with pytest.raises(ExtractionError, match="no usable text"):
        FormatRouter().extract(path)


def test_adding_a_format_is_registering_an_extractor(tmp_path):
    class SpreadsheetExtractor:
        name = "spreadsheet"

        def accepts(self, path: Path) -> bool:
            return path.suffix == ".xyz"

        def extract(self, path: Path):
            from jackryan.ingestion.extractors import Extraction

            return Extraction(text="from the new extractor", media_type="x/xyz", extractor=self.name)

    path = tmp_path / "sheet.xyz"
    path.write_text("raw", encoding="utf-8")
    router = FormatRouter([SpreadsheetExtractor()])
    assert router.extract(path).text == "from the new extractor"


# Docling parses these structurally, with no model and no network. PDF is
# excluded on purpose: it needs layout models fetched on first use.
@pytest.mark.parametrize("suffix,writer", [("md", "markdown"), ("html", "html")])
def test_docling_reads_markup_offline(tmp_path, suffix, writer):
    path = tmp_path / f"sample.{suffix}"
    if writer == "markdown":
        path.write_text("# Harbour Lease\n\nAwarded to Northgate.\n", encoding="utf-8")
    else:
        path.write_text("<html><body><h1>Harbour Lease</h1><p>Awarded.</p></body></html>", encoding="utf-8")
    text = DoclingExtractor().extract(path).text
    assert "Harbour Lease" in text


# --- The quality gate at the extraction seam ---------------------------------


def test_markup_is_never_escalated_however_thin(tmp_path):
    # A one-word Markdown file is far below any per-page floor, and must still
    # not reach recognition: there are no page images in it to read, so
    # escalating would spend the cost and change the text for no possible gain.
    from jackryan.ingestion.quality_gate import NATIVE, QualityGate

    def explode(path):
        raise AssertionError("markup must not reach a recognition rung")

    gate = QualityGate(
        ocr_engine="rapidocr",
        ocr_language="eslav",
        min_chars_per_page=10_000,
        readers={"text-layer": explode, "ocr": explode},
    )
    path = tmp_path / "tiny.md"
    path.write_text("Awarded.\n", encoding="utf-8")
    result = DoclingExtractor(gate).extract(path)
    assert result.text_source == NATIVE


def test_every_extractor_that_does_not_read_pages_reports_native(tmp_path):
    from jackryan.ingestion.quality_gate import NATIVE

    path = tmp_path / "note.txt"
    path.write_text("Plain content.", encoding="utf-8")
    assert PlainTextExtractor().extract(path).text_source == NATIVE


def test_a_pdf_reports_the_rung_the_gate_stopped_at(tmp_path):
    # The gate's readers are injected, so this asserts the wiring — that the
    # extractor reports what the gate decided — without loading a model.
    from jackryan.ingestion.quality_gate import OCR, QualityGate

    gate = QualityGate(
        ocr_engine="rapidocr",
        ocr_language="eslav",
        min_chars_per_page=100,
        readers={
            "text-layer": lambda path: (".\n\n:    .", 1),
            "ocr": lambda path: ("Правління передало оренду компанії " * 6, 1),
        },
    )
    path = tmp_path / "scan.pdf"
    path.write_bytes(b"%PDF-1.4 not really a pdf; the gate is stubbed")
    result = DoclingExtractor(gate).extract(path)
    assert result.text_source == OCR
    assert result.media_type == "application/pdf"


def test_a_page_image_is_accepted_rather_than_refused(tmp_path):
    from jackryan.ingestion.quality_gate import OCR, QualityGate

    gate = QualityGate(
        ocr_engine="rapidocr",
        ocr_language="eslav",
        min_chars_per_page=100,
        readers={
            "text-layer": lambda path: ("", 1),
            "ocr": lambda path: ("Board minutes recovered from a photograph " * 4, 1),
        },
    )
    path = tmp_path / "page.jpg"
    path.write_bytes(b"not really a jpeg; the gate is stubbed")
    result = FormatRouter(gate=gate).extract(path)
    assert result.extractor == "image"
    assert result.text_source == OCR


@pytest.mark.parametrize("name", ["p.png", "p.jpg", "p.jpeg", "p.tif", "p.tiff", "p.bmp", "p.webp"])
def test_image_suffixes_are_routed_and_reported_as_supported(name):
    router = FormatRouter()
    chosen = router.extractor_for(Path(name))
    assert chosen is not None and chosen.name == "image"
    assert Path(name).suffix in router.supported_suffixes()


def test_punctuation_only_text_is_refused(tmp_path):
    # Exactly what the shipped extractor returns today for a Ukrainian scan.
    # It is not empty, so the old emptiness check passed it, and it stored,
    # chunked and embedded as a document nobody could ever find.
    from jackryan.ingestion.quality_gate import QualityGate

    gate = QualityGate(
        ocr_engine="rapidocr",
        ocr_language="eslav",
        min_chars_per_page=100,
        readers={
            "text-layer": lambda path: (".\n\n:    .", 1),
            "ocr": lambda path: (".\n\n:    .", 1),
        },
    )
    path = tmp_path / "scan.pdf"
    path.write_bytes(b"%PDF-1.4 stub")
    with pytest.raises(ExtractionError, match="no usable text"):
        FormatRouter(gate=gate).extract(path)


@pytest.mark.parametrize(
    "text",
    [
        "Правління передало оренду",  # Cyrillic only, no Latin letter anywhere
        "1 234,00",  # digits only
        "李四",  # neither Latin nor Cyrillic
    ],
)
def test_text_without_latin_letters_is_still_usable(tmp_path, text):
    # The refusal must be "no letters or digits in any script", not "no ASCII".
    # A corpus in Ukrainian is the point of this workbench.
    from jackryan.ingestion.router import has_usable_text

    assert has_usable_text(text)
