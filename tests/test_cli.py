"""The CLI is the other thin adapter; it must surface the same errors."""

from __future__ import annotations

import json

import pytest

from jackryan import cli


@pytest.fixture(autouse=True)
def use_temp_context(monkeypatch, context):
    monkeypatch.setattr(cli, "build_context", lambda: context)
    monkeypatch.setattr(context, "close", lambda: None)
    return context


def run(argv, capsys) -> tuple[int, str, str]:
    code = cli.main(argv)
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_status_reports_configuration(capsys):
    code, out, _ = run(["status"], capsys)
    assert code == 0
    assert "profile" in out
    # Reported rather than enforced at startup, so this is where an operator
    # finds out before starting an hour-long run rather than 26 archives into it.
    assert "rar" in out


def test_create_then_list(capsys):
    code, out, _ = run(["--json", "casefile", "create", "Dockside Invoices"], capsys)
    assert code == 0
    assert json.loads(out)["slug"] == "dockside-invoices"

    code, out, _ = run(["--json", "casefile", "list"], capsys)
    assert [c["slug"] for c in json.loads(out)] == ["dockside-invoices"]


def test_empty_list_says_so(capsys):
    _, out, _ = run(["casefile", "list"], capsys)
    assert "No casefiles yet" in out


def test_show_accepts_a_slug(capsys):
    run(["--json", "casefile", "create", "Registry Extracts"], capsys)
    code, out, _ = run(["--json", "casefile", "show", "registry-extracts"], capsys)
    assert code == 0
    assert json.loads(out)["title"] == "Registry Extracts"


def test_unknown_reference_exits_nonzero_with_a_typed_code(capsys):
    code, _, err = run(["casefile", "show", "missing"], capsys)
    assert code == 1
    assert "not_found" in err


def test_delete_removes_it(capsys):
    run(["--json", "casefile", "create", "Scratch"], capsys)
    code, _, _ = run(["casefile", "delete", "scratch"], capsys)
    assert code == 0
    _, out, _ = run(["--json", "casefile", "list"], capsys)
    assert json.loads(out) == []


# -- M1: ingest, search, documents ---------------------------------------


def test_ingest_then_search(capsys, corpus):
    run(["--json", "casefile", "create", "Harbour Inquiry"], capsys)

    code, out, _ = run(["--json", "ingest", "harbour-inquiry", str(corpus)], capsys)
    assert code == 0
    assert json.loads(out)["ingested"] == 3

    code, out, _ = run(["--json", "search", "harbour-inquiry", "harbour lease Northgate"], capsys)
    assert code == 0
    results = json.loads(out)
    assert results and results[0]["document"] == "lease.md"


def test_ingest_prints_a_line_per_document(capsys, corpus):
    run(["--json", "casefile", "create", "Harbour Inquiry"], capsys)
    code, out, _ = run(["ingest", "harbour-inquiry", str(corpus)], capsys)
    assert code == 0
    assert "3 ingested, 0 failed" in out
    # The negative twin of the test below: a clean run must not warn. A summary
    # that always warns teaches an operator to ignore the warning.
    assert "did not cover everything it was offered" not in out


def test_an_incomplete_run_says_so_in_the_human_summary(capsys, tmp_path):
    """A person reading the summary must be told the run fell short.

    The counts alone read as a whole result: "1 ingested, 0 failed" is exactly
    what a complete run prints, and the file nothing could read leaves no trace
    in either number.
    """
    folder = tmp_path / "drop"
    folder.mkdir()
    (folder / "lease.md").write_text("# Lease\n\nThe harbour lease was awarded.\n", "utf-8")
    (folder / "activate.bat").write_bytes(b"@echo off\r\nnet use z: \\\\server\\share\r\n")

    run(["--json", "casefile", "create", "Mixed Drop"], capsys)
    code, out, _ = run(["ingest", "mixed-drop", str(folder)], capsys)

    # An incomplete run is a real result, not a failure: a non-zero code here
    # would break every script that ingests a folder of mixed content.
    assert code == 0
    assert "1 ingested, 0 failed" in out
    assert "did not cover everything it was offered" in out
    assert "no registered extractor" in out


def test_search_says_so_when_nothing_matches(capsys, corpus):
    run(["--json", "casefile", "create", "Empty Case"], capsys)
    code, out, _ = run(["search", "empty-case", "anything at all"], capsys)
    assert code == 0
    assert "No matches" in out


def test_document_list_and_show(capsys, corpus):
    run(["--json", "casefile", "create", "Harbour Inquiry"], capsys)
    run(["--json", "ingest", "harbour-inquiry", str(corpus)], capsys)

    code, out, _ = run(["--json", "document", "list", "harbour-inquiry"], capsys)
    assert code == 0
    documents = json.loads(out)
    assert len(documents) == 3

    code, out, _ = run(
        ["--json", "document", "show", "harbour-inquiry", documents[0]["short_id"]], capsys
    )
    assert code == 0
    assert json.loads(out)["id"] == documents[0]["id"]


def test_ingesting_into_an_unknown_casefile_exits_nonzero(capsys, corpus):
    code, _, err = run(["ingest", "no-such-case", str(corpus)], capsys)
    assert code == 1
    assert "not_found" in err


def test_repair_reports_a_corpus_that_needs_nothing(capsys, corpus):
    """The pass is safe to run on current data, and says it changed nothing.

    `chunks_examined` is asserted, not just the two zeros. This corpus holds no
    identifier at all, so `mentions_corrected == 0` is true of a pass that never
    looked — the spec asks for a run that corrected nothing to be
    distinguishable from one that did not look, and this is the field that
    distinguishes them.
    """
    run(["--json", "casefile", "create", "Harbour Inquiry"], capsys)
    run(["--json", "ingest", "harbour-inquiry", str(corpus)], capsys)

    code, out, _ = run(["--json", "repair", "mention-offsets", "harbour-inquiry"], capsys)
    assert code == 0
    report = json.loads(out)
    assert report["documents_examined"] == 3
    assert report["chunks_examined"] == 3
    assert report["chunks_unlocatable"] == 0
    assert report["mentions_corrected"] == 0
