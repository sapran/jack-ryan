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

from jackryan.config import Profile
from jackryan.ingestion.extractors import ExtractionError, default_extractors
from jackryan.ingestion.quality_gate import QualityGate
from jackryan.ingestion.router import CONTENT_ROUTED, SCRATCH_STEM, FormatRouter
from jackryan.ingestion.sniffing import (
    PREFIX_BYTES,
    _ole2_directory_names,
    producible_suffixes,
    sniff_suffix,
)

# Invented, not taken from any corpus — this repository is public and no real
# filename belongs in it. What is reproduced is the *shape* that motivated the
# change: shell quotes baked into the name by whatever exported it, so
# `Path.suffix` reads `.xlsx'` and no extractor claims it.
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


def _bitmap(path: Path) -> Path:
    """A structurally valid bitmap: `BM` plus a header that agrees with itself.

    The declared size is the real size, the DIB header size is one the format
    defines, and the pixel data starts after that header and inside the file.
    Two letters alone are not enough, deliberately.
    """
    body = bytearray(54 + 64)
    body[0:2] = b"BM"
    struct.pack_into("<I", body, 2, len(body))
    struct.pack_into("<I", body, 10, 54)
    struct.pack_into("<I", body, 14, 40)
    path.write_bytes(bytes(body))
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


def test_every_suffix_sniffing_can_return_is_accepted_by_an_extractor():
    """A signature for a format nothing will take can only ever be a refusal.

    Both sides are derived: the suffixes from the sniffer's own tables, and the
    verdict from each shipped extractor's `accepts` — asked about the scratch
    name the delegate would actually be handed, which is the question `_resolve`
    asks. Neither side is a literal list, so adding a signature for a format
    nothing reads fails here without anyone remembering to edit this test.

    An earlier version listed the payloads by hand and therefore proved nothing:
    a reviewer appended a `Rar!` signature at runtime and it stayed green.

    `accepts` rather than membership of `suffixes`, because those diverge —
    `TarExtractor` declares `.gz` and refuses it without a `.tar` underneath.
    """
    extractors = default_extractors()
    unclaimed = {
        suffix
        for suffix in producible_suffixes()
        if not any(e.accepts(Path(f"{SCRATCH_STEM}{suffix}")) for e in extractors)
    }
    assert not unclaimed, unclaimed
    # Guard the guard: an empty derivation would satisfy the assertion above.
    assert len(producible_suffixes()) >= 10


def test_document_text_is_not_mistaken_for_a_stream_name(tmp_path):
    """The byte scan must find directory entries, not prose.

    Found by review, and the consequence is a wrong answer rather than a miss:
    Word and Excel store text as UTF-16LE too, so a document whose body
    mentions a workbook would be identified as one and handed to the converter
    as a spreadsheet. Measured on a Visio-shaped fixture, which sniffed `.xls`.

    The directory here names a stream the table does not know, so the header
    path declines and the scan is what answers — which is exactly where the
    mistake lived.
    """
    header = bytearray(512)
    header[0:8] = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
    struct.pack_into("<H", header, 30, 9)
    struct.pack_into("<I", header, 48, 0)

    directory = bytearray(512)
    for index, name in enumerate(("Root Entry", "VisioDocument")):
        entry = bytearray(128)
        encoded = name.encode("utf-16-le")
        entry[0 : len(encoded)] = encoded
        struct.pack_into("<H", entry, 64, len(encoded) + 2)
        directory[index * 128 : (index + 1) * 128] = entry

    # Two documents, because the scan has two discriminators and a fixture that
    # exercises only one leaves the other free to rot. Each of these isolates
    # one, verified by mutation: remove either check and exactly one goes red.
    #
    # (a) Unaligned. The word lands off a 128-byte boundary, where prose falls
    # and a directory entry never does, and runs into NUL padding — so the
    # terminator alone cannot reject it and alignment must.
    unaligned = bytearray(512)
    unaligned[7:] = "see the Workbook".encode("utf-16-le").ljust(505, b"\x00")[:505]
    a = tmp_path / "unaligned.unknown"
    a.write_bytes(bytes(header) + bytes(directory) + bytes(unaligned))
    at = a.read_bytes().find("Workbook".encode("utf-16-le"))
    assert at % 128 != 0, at
    assert sniff_suffix(a) is None

    # (b) Aligned by chance, followed by a space rather than a NUL. This is the
    # realistic case the first fixture could not reach: the alignment check
    # passes, so only the terminator rejects it. A genuine entry's name is
    # NUL-terminated; prose continuing into the next word is not.
    aligned = bytearray(512)
    sentence = "Workbook tab is over here".encode("utf-16-le")
    aligned[0 : len(sentence)] = sentence  # "Workbook" at offset 0 of this sector
    b = tmp_path / "aligned.unknown"
    b.write_bytes(bytes(header) + bytes(directory) + bytes(aligned))
    at = b.read_bytes().find("Workbook".encode("utf-16-le"))
    assert at % 128 == 0, at
    after = b.read_bytes()[at + 16 : at + 18]
    assert after != b"\x00\x00", after
    assert sniff_suffix(b) is None


def test_a_signature_its_extractor_would_refuse_is_not_routed(monkeypatch, tmp_path):
    """The delegate is chosen by `accepts`, not by declared membership.

    Those diverge in exactly one place today: `TarExtractor` declares `.gz`,
    `.bz2` and `.xz` but refuses them unless a `.tar` sits underneath. Nothing
    currently sniffs to one, so this drives the signature directly rather than
    waiting for the day someone adds gzip magic — at which point membership
    would hand `TarExtractor` a file it had already refused, turning an honest
    refusal into a per-document failure.
    """
    monkeypatch.setattr(
        "jackryan.ingestion.router.sniff_suffix", lambda path: ".gz"
    )
    router = FormatRouter(gate=QualityGate.from_profile(Profile(name="default")))

    path = tmp_path / "notes.unknown"
    path.write_bytes(b"not a tar, and not gzip either")

    assert router.extractor_for(path) is None
    with pytest.raises(ExtractionError):
        router.extract(path)



def test_a_zip_based_document_of_an_unread_format_is_refused(tmp_path):
    """OpenDocument and the other OPC packages are near misses, not archives.

    Found by review. Calling an ODF file an archive is worse than refusing it:
    measured on this fixture before the fix, the casefile gained a document
    whose text was the part list, four refusals for the XML parts, and the
    preview thumbnail materialised as a child and sent through recognition. An
    institutional dump of hundreds of ODF files would fill a casefile with
    exactly the false matches this module exists to refuse.

    A genuine archive is unaffected: it declares neither marker.
    """
    odf = tmp_path / "report.unknown"
    with zipfile.ZipFile(odf, "w") as archive:
        archive.writestr("mimetype", "application/vnd.oasis.opendocument.text")
        archive.writestr("content.xml", "<office/>")
        archive.writestr("Thumbnails/thumbnail.png", b"\x89PNG\r\n\x1a\n")
    assert sniff_suffix(odf) is None

    # An OPC package nothing here reads — `.xlsb`, `.vsdx`, `.xps` all look
    # like this once the three OOXML parts are ruled out.
    opc = tmp_path / "drawing.unknown"
    with zipfile.ZipFile(opc, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("visio/document.xml", "<VisioDocument/>")
    assert sniff_suffix(opc) is None

    # A plain archive still is one.
    plain = tmp_path / "bundle.unknown"
    with zipfile.ZipFile(plain, "w") as archive:
        archive.writestr("notes/readme.txt", "just files")
    assert sniff_suffix(plain) == ".zip"


def test_a_compound_file_larger_than_the_prefix_is_still_identified(tmp_path):
    """The seek branch, which every other fixture here is too small to reach.

    Not a corner: Word writes its streams first and the directory last, so for
    any legacy document carrying embedded images — over a megabyte — seeking to
    the header's offset is the *only* path that can answer. The byte scan cannot
    mask a failure here, because the directory lies beyond the prefix entirely.

    Found by review: neutering the seek left every other test in this file
    green while a real `.doc` over 1 MB became unidentifiable.
    """
    sector = 512
    directory_sector = PREFIX_BYTES // sector + 4

    header = bytearray(sector)
    header[0:8] = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
    struct.pack_into("<H", header, 30, 9)
    struct.pack_into("<I", header, 48, directory_sector)

    directory = bytearray(sector)
    for index, name in enumerate(("Root Entry", "WordDocument")):
        entry = bytearray(128)
        encoded = name.encode("utf-16-le")
        entry[0 : len(encoded)] = encoded
        struct.pack_into("<H", entry, 64, len(encoded) + 2)
        directory[index * 128 : (index + 1) * 128] = entry

    # Body sectors between the header and the directory, holding nothing that
    # names a stream — so only the seek can find the answer. Sector N begins at
    # `(N + 1) * sector_size` because the header occupies the first one, so
    # reaching sector `directory_sector` takes exactly that many body sectors.
    body = bytes(directory_sector * sector)
    path = tmp_path / "big-legacy.unknown"
    path.write_bytes(bytes(header) + body + bytes(directory))

    assert path.stat().st_size > PREFIX_BYTES
    assert sniff_suffix(path) == ".doc"



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


def _unsupported_version_zip(path: Path, tmp_path: Path) -> Path:
    """A zip declaring an extract version no reader supports.

    `zipfile.namelist()` raises `NotImplementedError` for this — not a
    `BadZipFile`, not an `OSError` — and 103 bytes is enough to build one.
    """
    seed = tmp_path / "seed.zip"
    with zipfile.ZipFile(seed, "w") as archive:
        archive.writestr("a.txt", "x")
    raw = bytearray(seed.read_bytes())
    struct.pack_into("<H", raw, raw.find(b"PK\x01\x02") + 6, 100)  # version 10.0
    path.write_bytes(bytes(raw))
    return path


def test_a_hostile_archive_cannot_end_the_run(context, tmp_path):
    """The blocker a reviewer found, asserted where the damage happened.

    `sniff_suffix` is called from `extractor_for`, which the service consults in
    its main loop *outside* the per-document handler — so a raise there ends the
    whole ingest rather than failing one file. Measured before the fix: this
    folder stored one document and produced no report at all, where `develop`
    completed with two.

    Asserted through the service for that reason. At the `sniff_suffix` level
    this would only prove a return value; the contract that matters is that the
    two good documents on either side of the hostile one still arrive.
    """
    folder = tmp_path / "dump"
    folder.mkdir()
    _workbook(folder / "a-good.xlsx", value="Первый документ")
    _unsupported_version_zip(folder / "m-hostile", tmp_path)
    _workbook(folder / "z-also-good.xlsx", value="Третий документ")

    casefile = context.casefiles.create("Hostile Archive")
    report = context.ingestion.ingest(casefile.short_id, folder)

    assert report.ingested == 2, report.refusals
    stored = {d.filename for d in context.ingestion.list_documents(casefile.short_id)}
    assert stored == {"a-good.xlsx", "z-also-good.xlsx"}


def test_sniffing_returns_a_refusal_for_every_archive_that_will_not_open(tmp_path):
    """Each input known to raise out of `namelist`, pinned individually.

    The net in `sniff_suffix` is not the only thing standing behind these: name
    them, so that narrowing the net later fails here rather than in an ingest.
    """
    assert sniff_suffix(_unsupported_version_zip(tmp_path / "v", tmp_path)) is None

    truncated = tmp_path / "t"
    truncated.write_bytes(b"PK\x03\x04" + bytes(32))
    assert sniff_suffix(truncated) is None

    directory = tmp_path / "dir.unknown"
    directory.mkdir()
    assert sniff_suffix(directory) is None


def test_two_letters_are_not_a_bitmap(tmp_path):
    """`BM` is prose as often as it is a header.

    Without a structural check a memo opening "BMW purchase order" routes into
    the image reader and the recognition stack — this module's own
    positive-signatures rule broken by its own table.
    """
    memo = tmp_path / "memo.unknown"
    memo.write_bytes("BMW purchase order, 2023. Приказ о закупке.".encode())
    assert sniff_suffix(memo) is None

    # A real header, built by the shared helper: one definition of what a valid
    # bitmap is, so this test and the registry-coverage test cannot disagree.
    assert sniff_suffix(_bitmap(tmp_path / "image.unknown")) == ".bmp"


def test_a_symlink_is_not_read_at_all(tmp_path):
    """Identifying one buys nothing, and reading it leaves the dump.

    The service refuses a symlink before anything is stored, so sniffing one
    could only ever open a file outside the folder under examination — a format
    oracle for a path the analyst did not offer. Asserted by watching the open,
    because the return value is `None` either way.
    """
    outside = tmp_path / "outside.xlsx"
    _workbook(outside, value="Не для корпуса")

    folder = tmp_path / "dump"
    folder.mkdir()
    link = folder / "attachment"
    link.symlink_to(outside)

    opened: list[str] = []
    real_open = Path.open

    def watched(self, *args, **kwargs):
        opened.append(str(self))
        return real_open(self, *args, **kwargs)

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(Path, "open", watched)
        assert sniff_suffix(link) is None
    assert opened == []


def test_a_scratch_name_is_not_derived_from_the_operators_filename(router, tmp_path):
    """An extensionless name one byte under the limit still ingests.

    Appending a suffix to the original stem made the destination *longer* than
    the source, so a 251-byte extensionless file failed on a limit its own name
    never reached. The scratch stem is fixed, so the original's length cannot
    reach the copy.
    """
    path = tmp_path / ("d" * 251)
    _workbook(path, value="Длинное имя")
    assert len(path.name) == 251

    extraction = router.extract(path)
    assert "Длинное имя" in extraction.text
    assert extraction.extractor.startswith(f"{CONTENT_ROUTED}+")


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


def test_content_routing_does_not_widen_the_advertised_formats(router, tmp_path):
    """`supported_suffixes` answers what the registry declares, before and after.

    The first version of this test compared `supported_suffixes()` with the same
    comprehension over the same registry — a derivation against itself, which no
    change to content routing could ever falsify. A reviewer called it out, and
    a test that cannot go red certifies nothing.

    So it observes the thing the claim is about: a file is content-routed, and
    the advertised set neither changes nor learns the decorated suffix it just
    read. That fails if anyone ever teaches this to remember what it routed.
    """
    before = router.supported_suffixes()

    routed = _workbook(tmp_path / DECORATED)
    assert router.extract(routed).extractor.startswith(f"{CONTENT_ROUTED}+")

    assert router.supported_suffixes() == before
    assert ".xlsx'" not in router.supported_suffixes()
