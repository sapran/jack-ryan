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
