"""Routing a file on its content when its name defeats the registry.

Two halves. The first is the signature table: what it admits, and — carrying
more weight — what it refuses, because a wrong signature turns a clean refusal
into a mis-read document that nothing downstream can detect.

The second is that the fallback actually runs. The service layer skips a file
whose `extractor_for` is `None` before `extract` is ever called, so a fallback
proven only against `FormatRouter` would pass every test here and do nothing on
a real folder. The end-to-end tests therefore drive `IngestionService`, and
`test_the_fallback_is_reached_on_a_folder_walk` is the one that fails if that
pre-filter is ever restored to a suffix-only question.

Everything is built here rather than fixtured from real files: synthetic data
only, and a workbook keeps the model-dependent readers out of it — no test in
this suite is meant to reach recognition.
"""

from __future__ import annotations

import glob
import struct
import tempfile
import zipfile
from pathlib import Path

import pytest
from openpyxl import Workbook

from jackryan.ingestion.extractors import ExtractionError, default_extractors
from jackryan.ingestion.quality_gate import QualityGate
from jackryan.ingestion.router import CONTENT_ROUTED, FormatRouter
from jackryan.ingestion.sniffing import (
    PREFIX_BYTES,
    _ole2_directory_names,
    sniff_suffix,
)

# The name that started this: shell quotes baked into the filename by whatever
# exported it, so `Path.suffix` reads `.xlsx'` and the registry claims nothing.
DECORATED = "'Сводная ведомость.xlsx'"


@pytest.fixture
def router(gate: QualityGate) -> FormatRouter:
    return FormatRouter(gate=gate)


def _workbook(path: Path, value: str = "Ведомость 12345") -> Path:
    """A real workbook, readable by the extractor that claims `.xlsx`."""
    book = Workbook()
    # `worksheets[0]` rather than `active`, which is typed as optional.
    book.worksheets[0]["A1"] = value
    book.save(path)
    return path


def _ooxml(path: Path, part: str) -> Path:
    """An OOXML container holding one identifying part and nothing else.

    Enough for the signature table, which decides on the part's presence. Not
    enough to be read, which is what the separate end-to-end tests are for.
    """
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(part, "<?xml version='1.0'?><root/>")
    return path


def _ole2(
    path: Path,
    stream: str,
    *,
    reachable_directory: bool = True,
    sector_shift: int = 9,
    entry_index: int = 1,
) -> Path:
    """A compound file whose directory names one stream.

    The directory opens with `Root Entry`, as a real one does, and the named
    stream sits at `entry_index`. That is not decoration: with the stream at
    offset 0 a misaligned directory read still overlaps it, so a fixture shaped
    that way masks an offset bug — which is exactly what the first version of
    these tests did.

    With `reachable_directory` the header points at the directory sector, which
    is how a real file is read. Without it the header declares no directory, so
    only the bounded byte scan can find the name — the fallback path.

    `sector_shift` is 9 for 512-byte sectors and 12 for 4096-byte ones.
    """
    sector_size = 1 << sector_shift
    if (entry_index + 1) * 128 > sector_size:
        raise ValueError(
            f"entry {entry_index} does not fit a {sector_size}-byte sector"
        )

    # The header occupies the whole first sector whatever its size, which is
    # what the offset arithmetic under test depends on.
    header = bytearray(sector_size)
    header[0:8] = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
    struct.pack_into("<H", header, 30, sector_shift)
    struct.pack_into("<I", header, 48, 0 if reachable_directory else 0xFFFFFFFF)

    directory = bytearray(sector_size)

    def place(index: int, name: str) -> None:
        entry = bytearray(128)
        encoded = name.encode("utf-16-le")
        entry[0 : len(encoded)] = encoded
        # The length counts the trailing NUL that terminates the name.
        struct.pack_into("<H", entry, 64, len(encoded) + 2)
        directory[index * 128 : (index + 1) * 128] = entry

    place(0, "Root Entry")
    place(entry_index, stream)

    path.write_bytes(bytes(header) + bytes(directory))
    return path


# -- the signature table ----------------------------------------------------


def test_sniffing_identifies_a_format_the_registry_handles(tmp_path):
    """Each signature resolves to the suffix its own extractor claims."""
    cases = {
        _workbook(tmp_path / "book.bin"): ".xlsx",
        _ooxml(tmp_path / "doc.bin", "word/document.xml"): ".docx",
        _ooxml(tmp_path / "deck.bin", "ppt/presentation.xml"): ".pptx",
        _ooxml(tmp_path / "plain.bin", "notes/readme.txt"): ".zip",
    }
    for path, expected in cases.items():
        assert sniff_suffix(path) == expected, path.name

    raw = {
        "paper.bin": (b"%PDF-1.7\n%\xc7\xec\x8f\xa2\n", ".pdf"),
        "memo.bin": (b"{\\rtf1\\ansi\\deff0 text}", ".rtf"),
        "scan.bin": (b"\x89PNG\r\n\x1a\n" + bytes(64), ".png"),
        "photo.bin": (b"\xff\xd8\xff\xe0" + bytes(64), ".jpg"),
        "fax.bin": (b"II*\x00" + bytes(64), ".tiff"),
        "shot.bin": (b"RIFF\x24\x00\x00\x00WEBPVP8 " + bytes(32), ".webp"),
    }
    for name, (payload, expected) in raw.items():
        path = tmp_path / name
        path.write_bytes(payload)
        assert sniff_suffix(path) == expected, name


def test_an_ole2_file_is_identified_by_its_stream_names(tmp_path):
    """The outer container is the same for all four; the directory decides."""
    assert sniff_suffix(_ole2(tmp_path / "a.bin", "WordDocument")) == ".doc"
    assert sniff_suffix(_ole2(tmp_path / "b.bin", "Workbook")) == ".xls"
    assert sniff_suffix(_ole2(tmp_path / "c.bin", "PowerPoint Document")) == ".ppt"
    assert sniff_suffix(_ole2(tmp_path / "d.bin", "__substg1.0_0037001F")) == ".msg"


def test_the_ole2_directory_is_found_where_the_header_points(tmp_path):
    """The sector arithmetic, asserted on the unit that performs it.

    Deliberately not through `sniff_suffix`, and the fixture is deliberately
    shaped. Two things mask an offset bug here, both found by mutation:

    The byte scan behind the header read recovers the same answer from the
    prefix, so a wrong offset still yields the right suffix and any test written
    at the composed level passes while the arithmetic is broken.

    And with a 4096-byte sector the natural mistake — `512 + n * sector_size`,
    assuming a fixed-size header — reads exactly 3584 bytes low, which is a
    multiple of the 128-byte entry stride, so a misaligned read still overlaps
    the directory's first 512 bytes. A stream placed at offset 0 is found
    anyway. Placing it past that window is what makes the read's correctness
    observable at all.

    512-byte sectors cannot distinguish that mutation: `(n+1)*512` and
    `512+n*512` are the same expression. Only the 4096 case carries the proof,
    which is why it is here and not left to the dump that happened to arrive.
    """
    beyond_the_overlap = 5  # 640 bytes into the sector, past the low read's reach
    path = _ole2(
        tmp_path / "big-sectors.bin",
        "WordDocument",
        sector_shift=12,
        entry_index=beyond_the_overlap,
    )
    names = _ole2_directory_names(path, path.read_bytes()[:PREFIX_BYTES])
    assert "WordDocument" in names
    assert names[0] == "Root Entry"


def test_an_ole2_file_with_four_kilobyte_sectors_resolves(tmp_path):
    """The other sector size the format defines, end to end."""
    path = _ole2(tmp_path / "big-sectors.bin", "WordDocument", sector_shift=12)
    assert sniff_suffix(path) == ".doc"


def test_an_ole2_directory_beyond_the_first_sector_still_resolves(tmp_path):
    """The byte scan behind the header read, which is why it is there."""
    path = _ole2(tmp_path / "chained.bin", "Workbook", reachable_directory=False)
    assert sniff_suffix(path) == ".xls"


def test_an_unrecognised_ole2_file_is_not_guessed(tmp_path):
    """A compound file holding none of the four is refused, not assigned one."""
    assert sniff_suffix(_ole2(tmp_path / "other.bin", "Ole10Native")) is None


def test_sniffing_refuses_what_it_cannot_positively_identify(tmp_path):
    """The near misses, and the reason there is no text fallback.

    Every one of these decodes as text, and a batch script, a calendar invite
    and a detached signature are all present in the dump this change answers. A
    text fallback would draw the lot into the corpus as documents an analyst has
    to scroll past.
    """
    near_misses = {
        "script.bat": b"@echo off\r\nnet use z: \\\\server\\share\r\n",
        "invite.ics": b"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nEND:VCALENDAR\r\n",
        "signature.p7s": b"0\x82\x0b\x1a\x06\t*\x86H\x86\xf7\r\x01\x07\x02",
        "prose.unknown": "Приказ о зачислении, ordinary prose.".encode(),
        "noise.unknown": bytes(range(256)) * 4,
        "empty.unknown": b"",
        "short.unknown": b"PK",
    }
    for name, payload in near_misses.items():
        path = tmp_path / name
        path.write_bytes(payload)
        assert sniff_suffix(path) is None, name


def test_a_broken_archive_is_refused_rather_than_raising(tmp_path):
    """ZIP magic and nothing behind it. A refusal, never an exception out."""
    path = tmp_path / "truncated.unknown"
    path.write_bytes(b"PK\x03\x04" + bytes(32))
    assert sniff_suffix(path) is None


def test_an_unreadable_file_is_refused_rather_than_raising(tmp_path):
    """Sniffing runs where the alternative is already a refusal.

    Raising would turn one file's permissions into a failed run, which is the
    opposite of what this fallback is for.
    """
    path = tmp_path / "locked.unknown"
    _workbook(path)
    path.chmod(0o000)
    try:
        assert sniff_suffix(path) is None
    finally:
        path.chmod(0o644)


def test_every_suffix_sniffing_can_return_is_claimed_by_an_extractor(tmp_path):
    """A signature for a format nothing reads would be a crash, not a route.

    Derived from the live registry rather than compared against a literal list,
    so registering a signature for an unhandled format fails here immediately.
    """
    declared = {s for e in default_extractors() for s in e.suffixes}

    produced = set()
    for path in (
        _workbook(tmp_path / "1.bin"),
        _ooxml(tmp_path / "2.bin", "word/document.xml"),
        _ooxml(tmp_path / "3.bin", "ppt/presentation.xml"),
        _ooxml(tmp_path / "4.bin", "notes/readme.txt"),
        _ole2(tmp_path / "5.bin", "WordDocument"),
        _ole2(tmp_path / "6.bin", "Workbook"),
        _ole2(tmp_path / "7.bin", "PowerPoint Document"),
        _ole2(tmp_path / "8.bin", "__substg1.0_0037001F"),
    ):
        produced.add(sniff_suffix(path))
    for payload in (
        b"%PDF-1.7\n",
        b"{\\rtf1 x}",
        b"\x89PNG\r\n\x1a\n",
        b"\xff\xd8\xff\xe0",
        b"II*\x00",
        b"MM\x00*",
        b"BM\x36\x00",
        b"RIFF\x24\x00\x00\x00WEBPVP8 ",
    ):
        path = tmp_path / "raw.bin"
        path.write_bytes(payload + bytes(64))
        produced.add(sniff_suffix(path))

    assert None not in produced
    assert produced <= declared, produced - declared


# -- that the fallback is actually reached -----------------------------------


def test_the_fallback_is_reached_on_a_folder_walk(context, tmp_path):
    """The tripwire. A router-only fallback would leave this failing.

    `services/ingestion.py` skips a file whose `extractor_for` is `None` before
    `extract` is called, so this asserts through the service on a folder — the
    shape a real ingest takes — rather than against the router directly.
    """
    folder = tmp_path / "dump"
    folder.mkdir()
    _workbook(folder / DECORATED, value="Ведомость 12345")

    casefile = context.casefiles.create("Decorated Names")
    report = context.ingestion.ingest(casefile.short_id, folder)

    assert report.ingested == 1, report.refusals
    assert not report.refusals
    (document,) = context.ingestion.list_documents(casefile.short_id)
    assert "12345" in document.extracted_text


def test_a_content_routed_document_discloses_its_route_and_keeps_its_name(
    context, tmp_path
):
    """Read as something other than its name is a disclosure, not a correction.

    The filename stays what is on disk, quotes included, because that is what
    the operator has; the lineage says how it was read.
    """
    folder = tmp_path / "dump"
    folder.mkdir()
    _workbook(folder / DECORATED)

    casefile = context.casefiles.create("Disclosure")
    context.ingestion.ingest(casefile.short_id, folder)

    (document,) = context.ingestion.list_documents(casefile.short_id)
    assert document.filename == DECORATED
    assert document.extractor.startswith(f"{CONTENT_ROUTED}+")
    # The media type is the delegate's answer: what the evidence is, not how it
    # was found.
    assert document.media_type.endswith("spreadsheetml.sheet")


def test_a_file_with_a_claimed_suffix_is_never_sniffed(context, tmp_path, monkeypatch):
    """Content routing cannot change how a file that ingests today is read.

    Asserted by instrumentation rather than by outcome: a workbook named `.xlsx`
    would route correctly whether or not its content were consulted, so only
    watching the call proves the suffix decided.
    """
    calls: list[Path] = []

    def watched(path: Path):
        calls.append(path)
        return None

    monkeypatch.setattr("jackryan.ingestion.router.sniff_suffix", watched)

    folder = tmp_path / "dump"
    folder.mkdir()
    _workbook(folder / "ordinary.xlsx")
    (folder / "notes.md").write_text("# Приказ\n\nOrdinary markdown.\n")

    casefile = context.casefiles.create("Suffix Wins")
    report = context.ingestion.ingest(casefile.short_id, folder)

    assert report.ingested == 2, report.refusals
    assert calls == []


def test_an_unsignatured_file_is_still_refused(router, tmp_path):
    """The fallback narrows refusals; it does not remove them."""
    path = tmp_path / "activate.bat"
    path.write_bytes(b"@echo off\r\nnet use z: \\\\server\\share\r\n")

    assert router.extractor_for(path) is None
    with pytest.raises(ExtractionError) as raised:
        router.extract(path)
    assert path.name in str(raised.value)
    assert ".bat" in str(raised.value)


def test_a_content_routed_container_expands(context, tmp_path):
    """A container found by content stores and yields its children.

    Checked rather than assumed: `ZipExtractor` fixes its own media type and
    opens the path regardless of suffix, so no container-specific handling is
    needed — and this is what would catch that changing.
    """
    folder = tmp_path / "dump"
    folder.mkdir()
    inner = tmp_path / "inner.xlsx"
    _workbook(inner, value="Приказ внутри архива")
    with zipfile.ZipFile(folder / "'bundle.zip'", "w") as archive:
        archive.write(inner, "orders.xlsx")

    casefile = context.casefiles.create("Routed Container")
    context.ingestion.ingest(casefile.short_id, folder)

    everything = context.ingestion.list_documents(
        casefile.short_id, include_expanded=True
    )
    parent = next(d for d in everything if d.filename == "'bundle.zip'")
    assert parent.extractor.startswith(f"{CONTENT_ROUTED}+")
    children = context.ingestion.list_children(casefile.short_id, parent.id)
    assert [c.filename for c in children] == ["orders.xlsx"]
    assert "архива" in children[0].extracted_text


def test_a_failing_delegate_names_the_file_the_operator_has(router, tmp_path):
    """Not `KeyError`, and not the scratch path.

    An extractor keys its media type off `path.suffix`, so handing one a file
    still named `.xlsx'` raises `KeyError` — which is not an `ExtractionError`
    and would end the whole run rather than failing this one document.
    """
    path = tmp_path / "'corrupt.xlsx'"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("xl/workbook.xml", "not a workbook at all")

    with pytest.raises(ExtractionError) as raised:
        router.extract(path)
    message = str(raised.value)
    assert "'corrupt.xlsx'" in message
    # The route, not merely the name. Without this the plain "no extractor
    # accepts" refusal also carries the filename and the suffix, so the test
    # would pass with the fallback removed entirely — proving nothing.
    assert "read as .xlsx" in message
    assert "jackryan-routed-" not in message


def test_the_scratch_copy_is_removed_on_success_and_on_failure(router, tmp_path):
    """A scratch directory per content-routed file, and none left behind."""

    def leftovers() -> list[str]:
        return glob.glob(str(Path(tempfile.gettempdir()) / "jackryan-routed-*"))

    before = set(leftovers())

    good = _workbook(tmp_path / "'good.xlsx'")
    assert router.extract(good).text

    bad = tmp_path / "'bad.xlsx'"
    with zipfile.ZipFile(bad, "w") as archive:
        archive.writestr("xl/workbook.xml", "broken")
    with pytest.raises(ExtractionError):
        router.extract(bad)

    assert set(leftovers()) == before


def test_the_advertised_formats_are_unchanged_by_content_routing(router):
    """`supported_suffixes` answers what the registry declares.

    Content routing is a recovery path, not a capability, and widening this
    would tell an operator the corpus reads formats it does not.
    """
    assert router.supported_suffixes() == {
        suffix for e in default_extractors() for suffix in e.suffixes
    }
