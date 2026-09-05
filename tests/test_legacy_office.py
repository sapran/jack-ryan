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
import time
from pathlib import Path
from xml.etree.ElementTree import ParseError

import pytest

from jackryan.ingestion import extractors, legacy_office
from jackryan.ingestion.extractors import Extraction, ExtractionError
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


def test_a_timeout_kills_the_whole_converter_tree_not_just_the_launcher(
    tmp_path, monkeypatch
):
    """`soffice` is a launcher; the worker is a grandchild.

    `subprocess.run`'s own timeout kills a single pid, so the killed process is
    the launcher and `soffice.bin` survives — still holding the profile lock, and
    still able to write into the scratch directory *after* the `finally` has
    removed it. The stub reproduces that shape: a shell that backgrounds a
    long-lived grandchild and then waits.
    """
    marker = tmp_path / "grandchild-was-alive"
    body = (
        f'( sleep 3; echo alive > "{marker}" ) &\n'
        "GRANDCHILD=$!\n"
        f'echo $GRANDCHILD > "{tmp_path}/grandchild.pid"\n'
        "wait $GRANDCHILD"
    )
    monkeypatch.setattr(legacy_office, "CONVERSION_TIMEOUT_S", 1)
    use_converter(monkeypatch, a_stub_converter(tmp_path, body))

    with pytest.raises(ExtractionError):
        FormatRouter().extract(a_legacy_doc(tmp_path))

    grandchild = int((tmp_path / "grandchild.pid").read_text().strip())
    # Give the grandchild longer than it wanted, then check it never got there.
    time.sleep(3.5)
    assert not marker.exists(), "the grandchild outlived the timeout and kept working"
    with pytest.raises(OSError):
        os.kill(grandchild, 0)


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


# --- A successful conversion, with the real delegate --------------------------


def a_converting_stub(tmp_path: Path, monkeypatch, payload: Path) -> None:
    """A stub converter that writes a real modern file into the output directory.

    The argv is [profile, --headless, --convert-to, target, --outdir, out_dir,
    input], so `$4` is the target suffix and `$6` is the output directory. The
    stub writes under `$4` rather than a fixed name, because the extractor finds
    its output by globbing for exactly that suffix.
    """
    use_converter(
        monkeypatch,
        a_stub_converter(tmp_path, f'cp "{payload}" "$6/converted.$4"; exit 0'),
    )


def test_a_converted_file_reports_the_conversion_lineage_and_the_legacy_type(
    tmp_path, monkeypatch
):
    """The one in-suite test that drives a conversion all the way to a result.

    `documents.extractor` carrying the `legacy-office+` prefix is the only signal
    an analyst has that a converter stood between the file and the text, and the
    media-type override is what keeps the corpus honest about what the evidence
    is. Both were asserted only by the out-of-suite script, which needs
    LibreOffice and does not run in CI — so a regression in either would have
    reached main green.
    """
    a_converting_stub(tmp_path, monkeypatch, a_real_workbook(tmp_path / "payload.xlsx"))

    result = FormatRouter().extract(a_legacy_doc(tmp_path, "ledger.xls"))

    assert result.extractor == "legacy-office+spreadsheet"
    assert result.media_type == "application/vnd.ms-excel"
    assert result.text_source == NATIVE
    assert "## sheet: Leases" in result.text
    assert "Северный причал" in result.text


# --- The delegate's own failure -----------------------------------------------


def test_a_delegate_failure_names_the_original_file_not_the_scratch_copy(
    tmp_path, monkeypatch
):
    """The converted file lives in a temporary directory under a generated name.

    Reporting that name to an operator would name a file that no longer exists
    and that they never had.
    """
    a_converting_stub(tmp_path, monkeypatch, a_real_workbook(tmp_path / "payload.xlsx"))

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


def test_a_delegate_raising_something_other_than_extraction_error_is_contained(
    tmp_path, monkeypatch
):
    """`SpreadsheetExtractor` does not honour the contract, and this is the guard.

    `load_workbook` is wrapped but the lazy row iteration under it is not, so a
    workbook truncated mid-sheet surfaces a bare `ParseError`. `_ingest_work`
    catches only `(ValidationError, ExtractionError)`, so without this guard one
    malformed file ends a whole run.
    """
    a_converting_stub(tmp_path, monkeypatch, a_real_workbook(tmp_path / "payload.xlsx"))

    class Explodes:
        name = "spreadsheet"
        suffixes = {".xlsx": "application/x-stub"}

        def accepts(self, path: Path) -> bool:
            return True

        def extract(self, path: Path):
            raise ParseError("unclosed token: line 1, column 3246")

    extractor = LegacyOfficeExtractor()
    extractor._workbooks = Explodes()

    with pytest.raises(ExtractionError) as exc:
        extractor.extract(a_legacy_doc(tmp_path, "ledger.xls"))

    message = str(exc.value)
    assert message.startswith("ledger.xls, read as .xlsx: ParseError:")
    assert "unclosed token" in message


# --- RTF content under a .doc name --------------------------------------------


def test_rtf_content_named_doc_is_converted_rather_than_refused(tmp_path, monkeypatch):
    """Ordinary Word and mail-merge output. LibreOffice converts it happily.

    Refusing it as "neither an OLE2 nor an OOXML container" would lose exactly
    the class of readable legacy file this change exists to recover.
    """
    a_converting_stub(tmp_path, monkeypatch, a_real_workbook(tmp_path / "payload.xlsx"))

    path = tmp_path / "letter.doc"
    path.write_bytes(b"{\\rtf1\\ansi Northgate Holdings}")

    class Accepts:
        name = "docling"
        suffixes = {".docx": "application/x-stub"}

        def accepts(self, p: Path) -> bool:
            return True

        def extract(self, p: Path):
            return Extraction(text="Northgate Holdings", media_type="x", extractor="docling")

    extractor = LegacyOfficeExtractor()
    extractor._documents = Accepts()

    result = extractor.extract(path)
    assert result.extractor == "legacy-office+docling"
    assert result.media_type == "application/msword"


@pytest.mark.parametrize("suffix", [".xls", ".ppt"])
def test_rtf_content_under_a_non_word_suffix_is_still_refused(tmp_path, suffix):
    """The widening is word-processor only: RTF really is unreadable as a workbook."""
    path = tmp_path / f"ledger{suffix}"
    path.write_bytes(b"{\\rtf1\\ansi Northgate Holdings}")

    with pytest.raises(ExtractionError) as exc:
        FormatRouter().extract(path)

    assert "OLE2" in str(exc.value)


# --- The scratch directory ----------------------------------------------------


@pytest.mark.parametrize(
    "name,body",
    [
        ("letter.doc", "exit 1"),
        ("letter.doc", "exit 0"),
        ("note.rtf", "exit 0"),
    ],
)
def test_the_scratch_directory_is_removed_whatever_happens(
    tmp_path, monkeypatch, name, body
):
    """Observes the directory the extractor actually made, not a guess at one.

    Globbing the temp root would pass vacuously whenever the test's idea of the
    temp root and `tempfile.gettempdir()`'s disagree: both sets would be empty
    and the assertion would certify a cleanup that never happened.
    """
    use_converter(monkeypatch, a_stub_converter(tmp_path, body))

    made: list[Path] = []
    # Patched where the directory is now allocated: `deliver_via_scratch_directory`
    # in `extractors` makes it for both this path and content routing, and calls
    # `tempfile.mkdtemp` through the module rather than importing the name, so
    # the substitution is observed there.
    #
    # `extractors.tempfile` *is* the global `tempfile` module, so this is
    # process-wide rather than scoped to that module — naming `extractors` says
    # where the allocation happens, not where the patch reaches.
    real_mkdtemp = extractors.tempfile.mkdtemp

    def record(*args, **kwargs):
        created = real_mkdtemp(*args, **kwargs)
        made.append(Path(created))
        return created

    monkeypatch.setattr(extractors.tempfile, "mkdtemp", record)

    path = tmp_path / name
    path.write_bytes(
        b"{\\rtf1\\ansi x}" if name.endswith(".rtf") else legacy_office._OLE2_MAGIC + b"\x00" * 64
    )

    with pytest.raises(ExtractionError):
        FormatRouter().extract(path)

    assert made, "the extractor never allocated a scratch directory"
    assert not made[0].exists()


def test_a_converted_file_over_the_size_ceiling_is_refused(tmp_path, monkeypatch):
    """No input ceiling measures what the converter writes, and that is what is loaded."""
    monkeypatch.setattr(legacy_office, "MAX_CONVERTED_BYTES", 64)
    use_converter(
        monkeypatch,
        a_stub_converter(tmp_path, 'head -c 4096 /dev/zero > "$6/big.xlsx"; exit 0'),
    )

    with pytest.raises(ExtractionError) as exc:
        FormatRouter().extract(a_legacy_doc(tmp_path, "ledger.xls"))

    message = str(exc.value)
    assert "4096 bytes" in message and "64-byte limit" in message


def test_a_failure_with_no_diagnosis_still_says_something(tmp_path, monkeypatch):
    """A bare `exit 3` used to produce a message trailing off after a colon."""
    use_converter(monkeypatch, a_stub_converter(tmp_path, "exit 3"))

    with pytest.raises(ExtractionError) as exc:
        FormatRouter().extract(a_legacy_doc(tmp_path))

    assert "exited 3 without saying why" in str(exc.value)


def test_a_diagnosis_on_stdout_is_used_when_stderr_is_silent(tmp_path, monkeypatch):
    use_converter(monkeypatch, a_stub_converter(tmp_path, 'echo "source file could not be loaded"; exit 1'))

    with pytest.raises(ExtractionError) as exc:
        FormatRouter().extract(a_legacy_doc(tmp_path))

    assert "source file could not be loaded" in str(exc.value)


def test_the_tail_of_a_noisy_stderr_survives_truncation(tmp_path, monkeypatch):
    """LibreOffice opens with fontconfig noise and ends with the real complaint."""
    body = (
        'for i in $(seq 1 40); do echo "Fontconfig warning: no <cachedir> elements found" >&2; done\n'
        'echo "Error: no export filter for xlsx found, aborting." >&2\n'
        "exit 1"
    )
    use_converter(monkeypatch, a_stub_converter(tmp_path, body))

    with pytest.raises(ExtractionError) as exc:
        FormatRouter().extract(a_legacy_doc(tmp_path))

    assert "no export filter for xlsx found" in str(exc.value)
