"""RAR archives: what comes out of them, and what refuses to come out.

Every fixture here is synthetic and built in-process. No real case material
enters the repository, and no external archiver is needed to run these tests.

Building the fixtures rather than committing them is not a preference. RAR
compression is proprietary: the only tool that can *write* a RAR is RARLAB's
own, which is not installable in CI and is not a dependency this project will
take. What made a written fixture possible is that RAR5 permits an entry to be
stored uncompressed, so `_rar` emits the container format around unmodified
bytes and never compresses anything. The proof that what it emits is a genuine
RAR5 archive is that libarchive — the reader under test, which knows nothing
about this module — reads it back; `test_the_fixture_builder_emits_a_real_rar5`
is that assertion, and it is the test the rest of the file rests on.
"""

from __future__ import annotations

import struct
import zlib

import pytest

from jackryan.ingestion import containers
from jackryan.ingestion.containers import RarExtractor, rar_status
from jackryan.ingestion.extractors import ExtractionError
from jackryan.ingestion.router import FormatRouter

_SIGNATURE = b"Rar!\x1a\x07\x01\x00"

_HEAD_MAIN = 1
_HEAD_FILE = 2
_HEAD_CRYPT = 4
_HEAD_ENDARC = 5

_HAS_DATA = 0x0002


@pytest.fixture
def casefile(context):
    return context.casefiles.create("Archive Inquiry")


@pytest.fixture
def router():
    return FormatRouter()


def _vint(value: int) -> bytes:
    """RAR5's variable-length integer: seven bits a byte, high bit continues."""
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        out.append(byte | (0x80 if value else 0))
        if not value:
            return bytes(out)


def _block(kind: int, flags: int, body: bytes, data: bytes = b"", extra: bytes = b"") -> bytes:
    """One RAR5 block: a CRC over everything from the size field onward."""
    core = _vint(kind) + _vint(flags)
    if extra:
        core += _vint(len(extra))
    if data:
        core += _vint(len(data))
    core += body + extra
    header = _vint(len(core)) + core
    return struct.pack("<I", zlib.crc32(header) & 0xFFFFFFFF) + header + data


def _file_block(name: str, payload: bytes, declared: int | None = None) -> bytes:
    """A stored (uncompressed) file entry.

    `declared` exists to let a test lie about the unpacked size independently of
    the bytes actually present, which is the case the size ceiling defends
    against.
    """
    encoded = name.encode()
    body = (
        _vint(0x0004)  # file flags: a CRC32 of the unpacked data follows
        + _vint(declared if declared is not None else len(payload))
        + _vint(0)  # attributes
        + struct.pack("<I", zlib.crc32(payload) & 0xFFFFFFFF)
        + _vint(0)  # compression info: version 0, method 0 (store)
        + _vint(0)  # host os
        + _vint(len(encoded))
        + encoded
    )
    return _block(_HEAD_FILE, _HAS_DATA, body, data=payload)


def _rar(path, entries, *, header_encrypted: bool = False):
    """Write a RAR5 archive of stored entries."""
    out = bytearray(_SIGNATURE)
    if header_encrypted:
        # What a real password-protected archive puts in front of everything
        # else. libarchive refuses at this block and never reaches the entries,
        # which is the behaviour the encryption scenarios turn on.
        out += _block(_HEAD_CRYPT, 0, _vint(0) + _vint(0) + bytes([15]) + b"\x00" * 16)
    out += _block(_HEAD_MAIN, 0, _vint(0))
    for name, payload in entries:
        blob = payload.encode() if isinstance(payload, str) else payload
        out += _file_block(name, blob)
    out += _block(_HEAD_ENDARC, 0, _vint(0))
    path.write_bytes(bytes(out))
    return path


# -- the fixture builder itself --------------------------------------------


def test_the_fixture_builder_emits_a_real_rar5(tmp_path):
    """The one test the rest of this file depends on.

    If `_rar` emitted something only this module could read, every assertion
    below would be about a private format rather than about RAR.
    """
    archive = _rar(tmp_path / "a.rar", [("notes.txt", "the tariff was deferred")])

    extraction = RarExtractor().extract(archive)

    assert extraction.extractor == "rar"
    assert extraction.metadata["entries"] == "1"
    children = list(RarExtractor().iter_children(archive))
    assert [c.name for c in children] == ["notes.txt"]
    assert children[0].data == b"the tariff was deferred"


# -- registration ----------------------------------------------------------


def test_the_router_selects_the_rar_extractor(router, tmp_path):
    assert router.extractor_for(tmp_path / "bundle.rar").name == "rar"


def test_rar_is_reported_as_a_supported_suffix(router):
    assert ".rar" in router.supported_suffixes()


def test_a_rar_is_consulted_before_the_document_engine():
    # Order is the priority table: the first `accepts` wins, so an archive must
    # be reached before anything that would read it as one opaque file.
    names = [e.name for e in FormatRouter()._extractors]
    assert names.index("rar") < names.index("docling")


# -- expansion -------------------------------------------------------------


def test_a_rar_of_a_document_yields_both_documents(context, casefile, tmp_path):
    bundle = _rar(
        tmp_path / "bundle.rar", [("notes/memo.md", "# Memo\n\nThe tariff was deferred.")]
    )

    report = context.ingestion.ingest(casefile.short_id, bundle)

    assert report.failed == 0
    documents = context.store.list_documents(casefile.id, include_expanded=True)
    assert {d.filename for d in documents} == {"bundle.rar", "memo.md"}
    memo = next(d for d in documents if d.filename == "memo.md")
    assert "tariff" in memo.extracted_text


def test_the_rar_container_is_a_document_and_its_entries_are_its_children(
    context, casefile, tmp_path
):
    bundle = _rar(tmp_path / "bundle.rar", [("a.txt", "alpha"), ("b.txt", "beta")])

    context.ingestion.ingest(casefile.short_id, bundle)

    top = context.store.list_documents(casefile.id)
    assert [d.filename for d in top] == ["bundle.rar"]
    assert top[0].child_count == 2
    children = context.store.list_children(top[0].id)
    assert {c.filename for c in children} == {"a.txt", "b.txt"}
    assert all(c.parent_id == top[0].id for c in children)


def test_the_container_carries_its_listing_as_its_own_text(context, casefile, tmp_path):
    bundle = _rar(tmp_path / "bundle.rar", [("contract.txt", "signed"), ("annex.txt", "x")])

    context.ingestion.ingest(casefile.short_id, bundle)
    container = context.store.list_documents(casefile.id)[0]
    assert "contract.txt" in container.extracted_text
    assert "annex.txt" in container.extracted_text
    assert container.media_type == "application/vnd.rar"


def test_an_empty_rar_is_still_stored_as_a_container(context, casefile, tmp_path):
    """A container is exempt from the rule that a document must yield usable text.

    An archive holding nothing has no listing, so it has no text of its own. It
    is still evidence that an empty archive was in the dump, and the exemption
    is what stores it — which is why `is_container` is not decoration. Without
    the flag this document is refused for yielding no usable text, and the fact
    that it existed is lost.
    """
    bundle = _rar(tmp_path / "hollow.rar", [])

    report = context.ingestion.ingest(casefile.short_id, bundle)

    assert report.failed == 0
    documents = context.store.list_documents(casefile.id)
    assert [d.filename for d in documents] == ["hollow.rar"]
    assert documents[0].extracted_text == ""
    assert documents[0].child_count == 0


def test_an_unsupported_entry_does_not_fail_the_rar(context, casefile, tmp_path):
    bundle = _rar(
        tmp_path / "bundle.rar", [("good.txt", "readable"), ("index.db", b"\x00\x01\x02")]
    )

    report = context.ingestion.ingest(casefile.short_id, bundle)

    assert report.failed == 0
    assert any("index.db" in r for r in report.refusals)
    names = {d.filename for d in context.store.list_documents(casefile.id, include_expanded=True)}
    assert "good.txt" in names


def test_a_nested_rar_reaches_the_document_inside_it(context, casefile, tmp_path):
    inner = _rar(tmp_path / "inner.rar", [("deep.txt", "the buried clause")])
    outer = _rar(tmp_path / "outer.rar", [("inner.rar", inner.read_bytes())])

    context.ingestion.ingest(casefile.short_id, outer)

    documents = context.store.list_documents(casefile.id, include_expanded=True)
    deep = next(d for d in documents if d.filename == "deep.txt")
    assert "buried clause" in deep.extracted_text
    # The containment path is what an analyst follows back by hand.
    assert deep.containment_path == "outer.rar/inner.rar/deep.txt"


# -- entry names -----------------------------------------------------------


def test_a_traversing_entry_in_a_rar_is_refused_and_its_siblings_survive(
    context, casefile, tmp_path
):
    bundle = _rar(
        tmp_path / "bundle.rar",
        [("../escape.txt", "outside"), ("inside.txt", "kept"), ("/abs.txt", "absolute")],
    )

    report = context.ingestion.ingest(casefile.short_id, bundle)

    names = {d.filename for d in context.store.list_documents(casefile.id, include_expanded=True)}
    assert "inside.txt" in names
    assert "escape.txt" not in names
    assert "abs.txt" not in names
    assert report.failed == 0


def test_an_unsafe_entry_name_is_reported_rather_than_listed(tmp_path):
    bundle = _rar(tmp_path / "bundle.rar", [("../escape.txt", "x"), ("ok.txt", "y")])

    extraction = RarExtractor().extract(bundle)

    assert extraction.metadata["entries"] == "1"
    assert "ok.txt" in extraction.text
    assert "escape.txt" not in extraction.text
    assert any("escape.txt" in r and "traversal" in r for r in extraction.refusals)


# -- the size ceiling ------------------------------------------------------


def test_an_oversized_entry_is_excluded_on_what_was_read(tmp_path, monkeypatch):
    """The declared size is not the size, and this is the case that proves it.

    libarchive delivers the bytes actually stored, not the number in the header,
    so an entry declaring five bytes and carrying four hundred arrives as four
    hundred. Deciding the ceiling on `entry.size` would let an entry of any size
    through by lying about it in a field its own author wrote.
    """
    monkeypatch.setattr(containers, "MAX_ENTRY_BYTES", 64)
    out = bytearray(_SIGNATURE)
    out += _block(_HEAD_MAIN, 0, _vint(0))
    out += _file_block("liar.txt", b"A" * 400, declared=5)
    out += _file_block("honest.txt", b"kept")
    out += _block(_HEAD_ENDARC, 0, _vint(0))
    archive = tmp_path / "bundle.rar"
    archive.write_bytes(bytes(out))

    children = list(RarExtractor().iter_children(archive))

    assert [c.name for c in children] == ["honest.txt"]


# -- laziness --------------------------------------------------------------


def test_rar_entries_are_yielded_one_at_a_time(tmp_path):
    bundle = _rar(
        tmp_path / "bundle.rar", [("a.txt", "alpha"), ("b.txt", "beta"), ("c.txt", "gamma")]
    )

    entries = RarExtractor().iter_children(bundle)
    first = next(entries)

    assert first.name == "a.txt"
    # Abandoning the iterator partway is what the expansion budget does when a
    # bound is reached, so it must not raise on the way out.
    entries.close()


# -- an archive that cannot be opened --------------------------------------


def test_an_encrypted_rar_fails_the_document_naming_encryption(tmp_path):
    bundle = _rar(tmp_path / "locked.rar", [("secret.txt", "x")], header_encrypted=True)

    with pytest.raises(ExtractionError) as raised:
        RarExtractor().extract(bundle)

    assert "locked.rar" in str(raised.value)
    assert "ncryption" in str(raised.value)


def test_an_encrypted_rar_is_not_stored_as_a_container_with_no_children(
    context, casefile, tmp_path
):
    """The distinction this rule exists for.

    "Holds nothing" and "could not be opened" are different claims about
    evidence. A stored container with zero children asserts the first, and an
    analyst has no way to tell it from an archive that was genuinely empty.
    """
    bundle = _rar(tmp_path / "locked.rar", [("secret.txt", "x")], header_encrypted=True)

    report = context.ingestion.ingest(casefile.short_id, bundle)

    assert report.failed == 1
    assert context.store.list_documents(casefile.id, include_expanded=True) == []


def test_an_encrypted_rar_does_not_stop_the_run(context, casefile, tmp_path):
    folder = tmp_path / "dump"
    folder.mkdir()
    _rar(folder / "locked.rar", [("secret.txt", "x")], header_encrypted=True)
    _rar(folder / "open.rar", [("readable.txt", "the lease was signed")])

    report = context.ingestion.ingest(casefile.short_id, folder)

    assert report.failed == 1
    names = {d.filename for d in context.store.list_documents(casefile.id, include_expanded=True)}
    assert {"open.rar", "readable.txt"} <= names


def test_an_unopenable_rar_fails_naming_the_archive(tmp_path):
    archive = tmp_path / "truncated.rar"
    archive.write_bytes(_SIGNATURE + b"\x00" * 32)

    with pytest.raises(ExtractionError) as raised:
        RarExtractor().extract(archive)

    assert "truncated.rar" in str(raised.value)


def test_a_multi_volume_rar_is_refused_with_a_remedy(tmp_path):
    """Refused before opening, not after failing.

    libarchive reads the first volume's entries and only then raises, so letting
    it try would yield a partial listing that reads like a whole archive.
    """
    archive = _rar(tmp_path / "split.part1.rar", [("piece.txt", "half a document")])

    with pytest.raises(ExtractionError) as raised:
        RarExtractor().extract(archive)

    assert "multi-volume" in str(raised.value)
    assert "join the volumes" in str(raised.value)


def test_a_volume_suffix_is_matched_on_the_stem_not_the_name(tmp_path):
    # `report.part3.rar` is a volume; `partners.rar` is not, and a looser rule
    # would refuse it.
    ordinary = _rar(tmp_path / "partners.rar", [("a.txt", "alpha")])

    assert RarExtractor().extract(ordinary).metadata["entries"] == "1"


# -- an absent reader ------------------------------------------------------


def _no_reader(monkeypatch):
    """Make the libarchive import fail the way an absent library does."""
    import builtins

    real_import = builtins.__import__

    def refuse(name, *args, **kwargs):
        if name == "libarchive" or name.startswith("libarchive."):
            raise AttributeError("python: undefined symbol: archive_version_number")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", refuse)


def test_an_absent_reader_names_the_library_and_the_remedy(tmp_path, monkeypatch):
    bundle = _rar(tmp_path / "bundle.rar", [("a.txt", "alpha")])
    _no_reader(monkeypatch)

    with pytest.raises(ExtractionError) as raised:
        RarExtractor().extract(bundle)

    assert "libarchive" in str(raised.value)
    assert "install" in str(raised.value)


def test_an_absent_reader_fails_the_archive_not_the_run(context, casefile, tmp_path, monkeypatch):
    """The whole reason the reader is reported rather than verified at startup."""
    folder = tmp_path / "dump"
    folder.mkdir()
    _rar(folder / "bundle.rar", [("a.txt", "alpha")])
    (folder / "plain.md").write_text("# Memo\n\nThe tariff was deferred.")
    _no_reader(monkeypatch)

    report = context.ingestion.ingest(casefile.short_id, folder)

    assert report.failed == 1
    names = {d.filename for d in context.store.list_documents(casefile.id, include_expanded=True)}
    assert "plain.md" in names
    assert "bundle.rar" not in names


def test_an_absent_reader_reports_unavailable_rather_than_raising(monkeypatch):
    """`jackryan status` is where an operator finds out, so it must not crash.

    The import does not fail with `ImportError` when the system library is
    missing — it succeeds and the first symbol lookup fails — which is why the
    probe catches broadly and the import is not at module scope.
    """
    _no_reader(monkeypatch)

    assert rar_status() == containers.RAR_UNAVAILABLE


def test_the_reader_is_reported_on_this_host():
    assert rar_status() != containers.RAR_UNAVAILABLE
