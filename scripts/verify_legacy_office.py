#!/usr/bin/env python3
"""Exercise the legacy Office conversion, which the test suite cannot reach.

`tests/test_legacy_office.py` proves everything around the conversion — which
reader a converted file reaches, what a mislabelled file does, and that every
way a converter can fail comes back as an `ExtractionError`. It cannot prove the
conversion itself, because nothing in this repository can write a Word 97 file
and no real corpus material may be committed as a fixture.

This script closes that gap without a fixture. It manufactures genuine OLE2 and
RTF files by asking LibreOffice to convert synthetic HTML and flat-ODF sources
*into* the legacy formats, then runs the real `FormatRouter` over each product
and checks what came back.

    python scripts/verify_legacy_office.py

It needs LibreOffice and nothing else — no model weights, no network. It writes
to a temporary directory and removes it. The sentinels are synthetic: no real
case material belongs in this repository.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
import traceback
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from jackryan.ingestion.legacy_office import find_converter  # noqa: E402
from jackryan.ingestion.quality_gate import NATIVE  # noqa: E402
from jackryan.ingestion.router import FormatRouter  # noqa: E402

PASS, FAIL = "PASS", "FAIL"
results: list[tuple[str, str, str]] = []

# One Cyrillic, one Latin. Both must survive the round trip: a converter that
# mangles the encoding would still produce readable Latin text, so a Latin-only
# check would pass on a corpus this workbench exists to read.
CYRILLIC = "Северный причал 2021"
LATIN = "Northgate Holdings"

# Flat ODF, so an Impress source needs no library. A Writer document cannot be
# saved as PowerPoint, which is why the `.ppt` case cannot reuse the HTML source.
FODP = """<?xml version="1.0" encoding="UTF-8"?>
<office:document
 xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"
 xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"
 xmlns:draw="urn:oasis:names:tc:opendocument:xmlns:drawing:1.0"
 xmlns:svg="urn:oasis:names:tc:opendocument:xmlns:svg-compatible:1.0"
 office:version="1.3"
 office:mimetype="application/vnd.oasis.opendocument.presentation">
 <office:body><office:presentation>
  <draw:page draw:name="page1">
   <draw:frame svg:width="20cm" svg:height="4cm" svg:x="2cm" svg:y="2cm">
    <draw:text-box><text:p>{latin}</text:p><text:p>{cyrillic}</text:p></draw:text-box>
   </draw:frame>
  </draw:page>
 </office:presentation></office:body>
</office:document>
"""

HTML = f"<html><body><p>{LATIN}</p><p>{CYRILLIC}</p></body></html>"
CSV = f"party,berth\n{LATIN},{CYRILLIC}\n"

# The legacy export filters have to be named explicitly. LibreOffice 26.8
# refuses a bare `--convert-to doc` with "no export filter", so a script that
# guessed the short form would fail here rather than in the code under test.
#
# (source file, target suffix, LibreOffice export filter, expected media type)
CASES = [
    ("source.html", "doc", "doc:MS Word 97", "application/msword"),
    ("source.html", "rtf", "rtf:Rich Text Format", "application/rtf"),
    ("source.csv", "xls", "xls:MS Excel 97", "application/vnd.ms-excel"),
    ("deck.fodp", "ppt", "ppt:MS PowerPoint 97", "application/vnd.ms-powerpoint"),
]


def record(name: str, status: str, detail: str = "") -> None:
    results.append((name, status, detail))
    mark = {PASS: "✓", FAIL: "✗"}[status]
    print(f"  {mark} {name}" + (f" — {detail}" if detail else ""))


def manufacture(converter: str, workspace: Path, source: str, filter_spec: str) -> Path:
    """Ask LibreOffice for a genuine legacy file, so nothing binary is committed."""
    out_dir = workspace / "legacy"
    profile = workspace / "profile"
    out_dir.mkdir(exist_ok=True)
    profile.mkdir(exist_ok=True)
    target = filter_spec.split(":", 1)[0]
    subprocess.run(
        [
            converter,
            f"-env:UserInstallation={profile.as_uri()}",
            "--headless",
            "--convert-to",
            filter_spec,
            "--outdir",
            str(out_dir),
            str(workspace / source),
        ],
        capture_output=True,
        check=True,
        timeout=180,
    )
    produced = out_dir / f"{Path(source).stem}.{target}"
    if not produced.exists():
        raise RuntimeError(f"LibreOffice wrote no {target} for {source}")
    return produced


def check_one(router: FormatRouter, path: Path, media_type: str) -> None:
    title = f".{path.suffix.lstrip('.')} converted and read"
    result = router.extract(path)

    missing = [s for s in (LATIN, CYRILLIC) if s not in result.text]
    if missing:
        record(title, FAIL, f"sentinels lost: {missing}; got {result.text[:160]!r}")
        return
    if result.media_type != media_type:
        record(title, FAIL, f"media type {result.media_type!r}, expected {media_type!r}")
        return
    if result.text_source != NATIVE:
        record(title, FAIL, f"text_source {result.text_source!r}, expected {NATIVE!r}")
        return
    if not result.extractor.startswith("legacy-office+"):
        record(title, FAIL, f"extractor {result.extractor!r} does not name a conversion")
        return

    record(
        title,
        PASS,
        f"{len(result.text)} chars, both sentinels, "
        f"{result.media_type}, extractor={result.extractor}",
    )


def check_passthrough(router: FormatRouter, workspace: Path) -> None:
    """A real XLSX under a legacy name, which must not be converted at all."""
    title = "A modern workbook misnamed .xls is read directly"
    try:
        from openpyxl import Workbook
    except ImportError:
        record(title, FAIL, "openpyxl is not installed")
        return

    path = workspace / "book.xls"
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Leases"
    sheet.append(["party", "berth"])
    sheet.append([LATIN, CYRILLIC])
    workbook.save(path)

    result = router.extract(path)
    if result.extractor != "legacy-office-passthrough+spreadsheet":
        record(title, FAIL, f"extractor {result.extractor!r} names the wrong path")
        return
    if "## sheet: Leases" not in result.text or "row 2:" not in result.text:
        record(title, FAIL, f"not the workbook rendering: {result.text[:160]!r}")
        return
    if result.media_type != "application/vnd.ms-excel":
        record(title, FAIL, f"media type {result.media_type!r}")
        return
    record(title, PASS, f"{result.media_type}, extractor={result.extractor}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "--keep", action="store_true", help="leave the temporary directory in place"
    )
    args = parser.parse_args()

    converter = find_converter()
    if converter is None:
        print(
            "No LibreOffice on this host. Install it and put soffice on PATH; "
            "this script exists to exercise it.",
            file=sys.stderr,
        )
        return 1
    print(f"Converter: {converter}")

    workspace = Path(tempfile.mkdtemp(prefix="jackryan-legacy-verify-"))
    print(f"Workspace: {workspace}\n")

    try:
        (workspace / "source.html").write_text(HTML, encoding="utf-8")
        (workspace / "source.csv").write_text(CSV, encoding="utf-8")
        (workspace / "deck.fodp").write_text(
            FODP.format(latin=LATIN, cyrillic=CYRILLIC), encoding="utf-8"
        )

        router = FormatRouter()
        for source, _target, filter_spec, media_type in CASES:
            try:
                legacy = manufacture(converter, workspace, source, filter_spec)
                check_one(router, legacy, media_type)
            except Exception:
                record(f"{source} -> {filter_spec}", FAIL, "raised before it could report")
                traceback.print_exc()

        try:
            check_passthrough(router, workspace)
        except Exception:
            record("A modern workbook misnamed .xls is read directly", FAIL, "raised")
            traceback.print_exc()
    finally:
        if args.keep:
            print(f"\nLeft in place: {workspace}")
        else:
            shutil.rmtree(workspace, ignore_errors=True)

    failed = [r for r in results if r[1] == FAIL]
    passed = [r for r in results if r[1] == PASS]
    print("\n" + "─" * 60)
    print(f"{len(passed)} passed, {len(failed)} failed")
    if failed:
        print("\nFailures:")
        for name, _, detail in failed:
            print(f"  ✗ {name}: {detail}")
        return 1
    print(
        "\nThe conversion itself now rests on something that ran. Record the result "
        "in docs/handover.md."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
