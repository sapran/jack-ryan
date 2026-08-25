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
