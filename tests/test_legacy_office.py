"""Legacy binary Office formats, read by converting them to modern ones.

None of these tests needs LibreOffice. The suite cannot write a Word 97 file —
no dependency can — so what is proven here is everything *around* the
conversion: which reader the converted file reaches, what a mislabelled file
does, and that every way a converter can fail comes back as an `ExtractionError`
rather than something that would end an ingest run.

The conversion itself is proven out of suite, by `scripts/verify_legacy_office.py`.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from jackryan.ingestion import legacy_office
from jackryan.ingestion.extractors import ExtractionError
from jackryan.ingestion.legacy_office import LegacyOfficeExtractor
from jackryan.ingestion.quality_gate import NATIVE
from jackryan.ingestion.router import FormatRouter


def a_real_workbook(path: Path) -> Path:
    """A genuine XLSX, written under whatever name the caller asked for."""
    from openpyxl import Workbook

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Leases"
    sheet.append(["party", "berth"])
    sheet.append(["Northgate Holdings", "Северный причал"])
    workbook.save(path)
    return path


def a_stub_converter(tmp_path: Path, body: str) -> str:
    """A shell script standing in for LibreOffice, so the failure paths are reachable."""
    script = tmp_path / "stub-soffice"
    script.write_text(f"#!/bin/sh\n{body}\n", encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return str(script)


def use_converter(monkeypatch, value: str | None) -> None:
    monkeypatch.setattr(legacy_office, "find_converter", lambda: value)


# --- What the router does with the four suffixes ------------------------------


def test_the_four_suffixes_carry_their_legacy_media_types():
    assert legacy_office.LEGACY_SUFFIXES == {
        ".doc": "application/msword",
        ".xls": "application/vnd.ms-excel",
        ".ppt": "application/vnd.ms-powerpoint",
        ".rtf": "application/rtf",
    }


# --- The mislabel rescue, which needs no converter at all ---------------------


def test_a_workbook_misnamed_xls_is_read_by_the_workbook_reader(tmp_path, monkeypatch):
    """The dump held two of these: a real XLSX with a legacy name.

    Converting one would be a lossy round trip for no reason, and refusing it
    would lose a document that is perfectly readable. It is read directly — with
    no converter installed at all, which is what the monkeypatch asserts.
    """
    use_converter(monkeypatch, None)
    path = a_real_workbook(tmp_path / "book.xls")

    result = FormatRouter().extract(path)

    # The workbook rendering, not a second one: the same `## sheet:` / `row N:`
    # shape every XLSX in the corpus already has.
    assert "## sheet: Leases" in result.text
    assert "row 2:" in result.text
    assert "Northgate Holdings" in result.text
    assert "Северный причал" in result.text
    # The type the file on disk is named for, not the one it was read as.
    assert result.media_type == "application/vnd.ms-excel"
    assert result.extractor == "legacy-office-passthrough+spreadsheet"
    assert result.text_source == NATIVE


# --- A container that contradicts its suffix ----------------------------------


def test_html_misnamed_xls_is_refused_naming_what_was_expected(tmp_path):
    """The dump held one of these. LibreOffice's own error would name neither."""
    path = tmp_path / "sheet.xls"
    path.write_text("<html><body><p>x</p></body></html>", encoding="utf-8")

    with pytest.raises(ExtractionError) as exc:
        FormatRouter().extract(path)

    message = str(exc.value)
    assert "sheet.xls" in message and "OLE2" in message


def test_a_file_that_is_not_rtf_is_refused_at_the_header(tmp_path):
    path = tmp_path / "note.rtf"
    path.write_text("not rtf at all", encoding="utf-8")

    with pytest.raises(ExtractionError) as exc:
        FormatRouter().extract(path)

    assert "RTF header" in str(exc.value)


# --- The converter, absent ----------------------------------------------------


def test_an_absent_converter_names_the_remedy(tmp_path, monkeypatch):
    use_converter(monkeypatch, None)
    path = tmp_path / "letter.doc"
    path.write_bytes(legacy_office._OLE2_MAGIC + b"\x00" * 64)

    with pytest.raises(ExtractionError) as exc:
        FormatRouter().extract(path)

    message = str(exc.value)
    assert "LibreOffice" in message and "PATH" in message and "letter.doc" in message


def test_an_absent_converter_does_not_stop_an_ingest_run(tmp_path, monkeypatch, context):
    """A host that reads no legacy file must not be stopped by a converter it will never use.

    This is the whole reason the converter is reported rather than verified at
    the start of a run, the way the recognition engine is.
    """
    use_converter(monkeypatch, None)
    folder = tmp_path / "dump"
    folder.mkdir()
    (folder / "brief.md").write_text("# Harbour Lease\n\nSigned in 2021.", encoding="utf-8")
    (folder / "letter.doc").write_bytes(legacy_office._OLE2_MAGIC + b"\x00" * 64)

    casefile = context.casefiles.create(title="Mixed dump")
    report = context.ingestion.ingest(casefile.id, folder)

    statuses = {Path(o.path).name: o.status for o in report.outcomes}
    assert statuses["brief.md"] == "ingested"
    assert statuses["letter.doc"] == "failed"


# --- The three subprocess failure paths ---------------------------------------
#
# `IngestionService._ingest_work` catches only `(ValidationError,
# ExtractionError)`. A `CalledProcessError`, `TimeoutExpired` or `OSError`
# escaping this extractor would end a 1922-file run rather than fail one
# document, so each is exercised with a stub converter.


def a_legacy_doc(tmp_path: Path, name: str = "letter.doc") -> Path:
    path = tmp_path / name
    path.write_bytes(legacy_office._OLE2_MAGIC + b"\x00" * 64)
    return path


def test_a_failing_converter_carries_its_own_stderr_into_the_message(tmp_path, monkeypatch):
    use_converter(
        monkeypatch,
        a_stub_converter(tmp_path, 'echo "no export filter found" >&2\nexit 1'),
    )

    with pytest.raises(ExtractionError) as exc:
        FormatRouter().extract(a_legacy_doc(tmp_path))

    message = str(exc.value)
    assert "letter.doc" in message and "no export filter found" in message


def test_a_hung_converter_is_stopped_and_the_message_names_the_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(legacy_office, "CONVERSION_TIMEOUT_S", 1)
    use_converter(monkeypatch, a_stub_converter(tmp_path, "sleep 30"))

    with pytest.raises(ExtractionError) as exc:
        FormatRouter().extract(a_legacy_doc(tmp_path))

    message = str(exc.value)
    assert "letter.doc" in message and "exceeded 1s" in message


def test_a_converter_that_exits_clean_but_writes_nothing_is_a_failure(tmp_path, monkeypatch):
    """LibreOffice does exactly this in some cases, so the glob is the real gate."""
    use_converter(monkeypatch, a_stub_converter(tmp_path, "exit 0"))

    with pytest.raises(ExtractionError) as exc:
        FormatRouter().extract(a_legacy_doc(tmp_path))

    assert "produced no output" in str(exc.value)


def test_a_converter_that_cannot_be_run_fails_the_document(tmp_path, monkeypatch):
    """Resolvable but not executable — an OSError, which is not an ExtractionError."""
    script = tmp_path / "unrunnable"
    script.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    script.chmod(script.stat().st_mode & ~stat.S_IXUSR & ~stat.S_IXGRP & ~stat.S_IXOTH)
    use_converter(monkeypatch, str(script))

    with pytest.raises(ExtractionError) as exc:
        FormatRouter().extract(a_legacy_doc(tmp_path))

    assert "letter.doc" in str(exc.value)


# --- The delegate's own failure -----------------------------------------------


def test_a_delegate_failure_names_the_original_file_not_the_scratch_copy(
    tmp_path, monkeypatch
):
    """The converted file lives in a temporary directory under a generated name.

    Reporting that name to an operator would name a file that no longer exists
    and that they never had.
    """
    written = a_real_workbook(tmp_path / "source.xlsx")
    body = f'cp "{written}" "$6/converted.xlsx" 2>/dev/null; exit 0'
    use_converter(monkeypatch, a_stub_converter(tmp_path, body))

    class Refuses:
        name = "spreadsheet"
        suffixes = {".xlsx": "application/x-stub"}

        def accepts(self, path: Path) -> bool:
            return True

        def extract(self, path: Path):
            raise ExtractionError(f"could not read {path.name} as a workbook")

    extractor = LegacyOfficeExtractor()
    extractor._workbooks = Refuses()

    with pytest.raises(ExtractionError) as exc:
        extractor.extract(a_legacy_doc(tmp_path, "ledger.xls"))

    message = str(exc.value)
    # The operator's own filename leads, and the delegate's diagnosis is kept
    # behind it rather than discarded — without the rewrap the message would
    # name only the scratch copy.
    assert message.startswith("ledger.xls, read as .xlsx:")
    assert message.endswith("could not read converted.xlsx as a workbook")


# --- The scratch directory ----------------------------------------------------


def test_the_scratch_directory_is_removed_whatever_happens(tmp_path, monkeypatch):
    use_converter(monkeypatch, a_stub_converter(tmp_path, "exit 1"))
    before = {p for p in Path(os.environ.get("TMPDIR", "/tmp")).glob("jackryan-legacy-*")}

    with pytest.raises(ExtractionError):
        FormatRouter().extract(a_legacy_doc(tmp_path))

    after = {p for p in Path(os.environ.get("TMPDIR", "/tmp")).glob("jackryan-legacy-*")}
    assert after == before
