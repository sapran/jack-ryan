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

_HAS_EXTRA = 0x0001
_HAS_DATA = 0x0002
# An entry whose data continues in the next volume of a set.
_SPLIT_AFTER = 0x0010
# In the main header's archive-flags field: this archive is one volume of a set.
_ARCHIVE_VOLUME = 0x0001
# In an end-of-archive block's flags: another volume follows this one.
_ENDARC_NOT_LAST = 0x0001


def _real_libarchive_version() -> int:
    """The host's actual libarchive version, read once before any fixture runs.

    Captured at import deliberately. The autouse fixture below raises the
    reported version to the floor, so a test that asked the library at call time
    would be handed the patched answer — its expectation computed by the very
    thing it exists to check, which is a guard that cannot fail.
    """
    try:
        import libarchive.ffi

        return int(libarchive.ffi.version_number())
    except Exception:  # noqa: BLE001 - absent library; the floor test says so
        return 0


_REAL_LIBARCHIVE = _real_libarchive_version()


@pytest.fixture(autouse=True)
def _reader_at_the_floor(monkeypatch):
    """Exercise this module's logic, not libarchive's patch level.

    `MIN_LIBARCHIVE` is a deployment control: it stops a real instance handing
    *untrusted* archives to a parser with a known double free. These tests are
    about what this extractor does with an archive once it can read one, and
    every fixture they use is built in this file rather than supplied by anyone.

    The alternative was to skip the reader-dependent tests below the floor. That
    was rejected: CI is the only gate guarding this repository, its runner's
    system library is older than the floor, and skipping would mean the whole
    RAR feature ships with no functional coverage — a regression in the
    extractor would pass green. Losing that coverage is itself a security
    problem, and a bigger one than exercising a benign self-built fixture on an
    older library.

    Two things keep it honest: `test_the_host_reader_satisfies_the_floor_when_required`
    asserts the real version when `JACKRYAN_REQUIRE_RAR=1`, and the Docker build
    gate builds a patched library, which is what proves the floor is satisfiable
    rather than merely asserted. Tests that are *about* the floor patch the
    version themselves and so override this.

    No library at all is a skip rather than an error. Importing `libarchive.ffi`
    here unguarded made every test in this module ERROR on such a host, which
    reports a broken test suite where the honest report is an unavailable
    capability — and `rar_status` exists precisely to say that this host cannot
    read archives without anything else failing.
    """
    if _REAL_LIBARCHIVE == 0:
        pytest.skip("no usable libarchive on this host, so there is no reader to exercise")

    import libarchive.ffi

    if libarchive.ffi.version_number() < containers.MIN_LIBARCHIVE:
        monkeypatch.setattr(
            libarchive.ffi, "version_number", lambda: containers.MIN_LIBARCHIVE
        )


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
    # Keyed off the flags, not off whether the areas are non-empty: a file
    # header declaring HAS_DATA must carry a data-size field even when the size
    # is zero, which is exactly the case a link entry is.
    if flags & _HAS_EXTRA:
        core += _vint(len(extra))
    if flags & _HAS_DATA:
        core += _vint(len(data))
    core += body + extra
    header = _vint(len(core)) + core
    return struct.pack("<I", zlib.crc32(header) & 0xFFFFFFFF) + header + data


def _file_block(
    name: str,
    payload: bytes,
    declared: int | None = None,
    *,
    header_flags: int = 0,
) -> bytes:
    """A stored (uncompressed) file entry.

    `declared` exists to let a test lie about the unpacked size independently of
    the bytes actually present, which is the case the size ceiling defends
    against. `header_flags` adds to the block's common flags, which is how an
    entry says its data is split across volumes.
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
    return _block(_HEAD_FILE, _HAS_DATA | header_flags, body, data=payload)


def _rar(path, entries, *, header_encrypted: bool = False, archive_flags: int = 0):
    """Write a RAR5 archive of stored entries."""
    out = bytearray(_SIGNATURE)
    if header_encrypted:
        # What a real password-protected archive puts in front of everything
        # else. libarchive refuses at this block and never reaches the entries,
        # which is the behaviour the encryption scenarios turn on.
        out += _block(_HEAD_CRYPT, 0, _vint(0) + _vint(0) + bytes([15]) + b"\x00" * 16)
    out += _block(_HEAD_MAIN, 0, _vint(archive_flags))
    for name, payload in entries:
        blob = payload.encode() if isinstance(payload, str) else payload
        out += _file_block(name, blob)
    out += _block(_HEAD_ENDARC, 0, _vint(0))
    path.write_bytes(bytes(out))
    return path


# -- the older generation ---------------------------------------------------
#
# RAR 2.9/3.x is a different container entirely — fixed-layout little-endian
# headers rather than RAR5's vints — and libarchive reads it with a different
# reader. It is built here as well because the only RAR3 coverage this file had
# was a signature string compared against `_rar_format`, which read no bytes at
# all, and that is how an encrypted RAR3 archive came to be ingested as
# ciphertext: the check that would have caught it was reached only for RAR5, and
# nothing in this module ever asked a RAR3 archive to be read.

_RAR3_SIGNATURE = b"Rar!\x1a\x07\x00"

_RAR3_MAIN = 0x73
_RAR3_FILE = 0x74
_RAR3_ENDARC = 0x7B

_RAR3_LONG_BLOCK = 0x8000  # an ADD_SIZE field follows the base header
_MHD_VOLUME = 0x0001  # main header: this archive is one volume of a set
_MHD_PASSWORD = 0x0080  # main header: every later header is encrypted
_LHD_SPLIT_AFTER = 0x0002  # file header: this entry continues in the next volume
_FHD_PASSWORD = 0x0004  # file header: this entry's data is encrypted
_FHD_SALT = 0x0400  # file header: an 8-byte salt follows the name


def _rar3_block(kind: int, flags: int, rest: bytes) -> bytes:
    """One RAR 2.9/3.x block: HEAD_CRC is the low 16 bits of a CRC32 from HEAD_TYPE on."""
    body = bytes([kind]) + struct.pack("<H", flags) + struct.pack("<H", 7 + len(rest)) + rest
    return struct.pack("<H", zlib.crc32(body) & 0xFFFF) + body


def _rar3_file_block(name: str, payload: bytes, flags: int, file_crc: int | None) -> bytes:
    """A stored RAR3 file entry.

    PACK_SIZE is the first field after the base header, which is also where the
    format's generic ADD_SIZE lives — so a block's total length is HEAD_SIZE plus
    PACK_SIZE, and a walk needs no knowledge of this body to step over it.

    `file_crc` is settable because a real encrypted entry stores the CRC of the
    *plaintext*, which does not match the ciphertext on disk.
    """
    encoded = name.encode()
    rest = struct.pack(
        "<IIBIIBBHI",
        len(payload),  # PACK_SIZE
        len(payload),  # UNP_SIZE
        0,  # HOST_OS
        zlib.crc32(payload) & 0xFFFFFFFF if file_crc is None else file_crc,
        0,  # FTIME
        29,  # UNP_VER: 2.9
        0x30,  # METHOD: store
        len(encoded),  # NAME_SIZE
        0,  # ATTR
    ) + encoded
    if flags & _FHD_SALT:
        rest += b"\x00" * 8
    return _rar3_block(_RAR3_FILE, _RAR3_LONG_BLOCK | flags, rest) + payload


def _rar3(path, entries, *, file_flags: int = 0, main_flags: int = 0, file_crc: int | None = None):
    """Write a RAR 2.9/3.x archive of stored entries."""
    out = bytearray(_RAR3_SIGNATURE)
    out += _rar3_block(_RAR3_MAIN, main_flags, struct.pack("<HI", 0, 0))
    for name, payload in entries:
        blob = payload.encode() if isinstance(payload, str) else payload
        out += _rar3_file_block(name, blob, file_flags, file_crc)
    out += _rar3_block(_RAR3_ENDARC, 0x4000, b"")
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


def test_the_fixture_builder_emits_a_real_rar3(tmp_path):
    """The same proof for the older generation, and it reads bytes.

    What stood here before compared `_rar_format` against a string for sixteen
    zero bytes behind a RAR3 signature. That opened nothing, read nothing, and
    was the file's only RAR3 coverage — so the encryption check being reached
    for RAR5 alone was invisible. This drives the whole path: libarchive's
    separate RAR3 reader opens the archive, lists it, and returns the payload.
    """
    archive = _rar3(tmp_path / "legacy.rar", [("notes.txt", "the tariff was deferred")])

    extraction = RarExtractor().extract(archive)

    assert extraction.extractor == "rar"
    assert extraction.media_type == "application/vnd.rar"
    assert extraction.metadata["entries"] == "1"
    assert extraction.refusals == ()
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
    out += _file_block("before.txt", b"FIRST")
    out += _file_block("liar.txt", b"A" * 400, declared=5)
    out += _file_block("honest.txt", b"kept")
    out += _block(_HEAD_ENDARC, 0, _vint(0))
    archive = tmp_path / "bundle.rar"
    archive.write_bytes(bytes(out))

    children = list(RarExtractor().iter_children(archive))

    assert [c.name for c in children] == ["before.txt", "honest.txt"]
    # The payloads matter as much as the names. Stopping mid-entry leaves that
    # entry's block stream unconsumed, and the reader's cursor is shared and
    # forward-only: if abandoning one entry desynchronised it, the casualty
    # would be the *next* entry, arriving short or shifted rather than absent.
    # Asserting names alone would not notice that.
    assert [c.data for c in children] == [b"FIRST", b"kept"]


# -- laziness --------------------------------------------------------------


def _watch_reads(monkeypatch) -> list[bytes]:
    """Record every payload byte libarchive hands back, as it hands it back.

    `ArchiveEntry.get_blocks` resolves `ffi.read_data` when its body first runs,
    so replacing the module attribute is enough and no entry object has to be
    reached into. What the recorder gives a test is the one thing a generator's
    shape cannot fake: *when* the bytes of a given entry were pulled off the
    reader.
    """
    import libarchive.ffi

    delivered: list[bytes] = []
    real = libarchive.ffi.read_data

    def recording(archive_p, buffer, size):  # noqa: ANN001,ANN202 - libarchive's own types
        count = real(archive_p, buffer, size)
        if count > 0:
            delivered.append(buffer.raw[:count])
        return count

    monkeypatch.setattr(libarchive.ffi, "read_data", recording)
    return delivered


def test_a_rar_entry_is_read_only_when_it_is_reached(tmp_path, monkeypatch):
    """One entry at a time, judged on what libarchive was asked to deliver.

    What stood here before took the first child and closed the generator. That
    passes for an implementation that reads every entry into a list and then
    `yield from`s it — the shape the spec's scenario exists to forbid, since it
    puts a whole archive in memory before the expansion budget can refuse any of
    it. `iter_children` being a generator is not the claim; the claim is that
    the later entries' bytes have not been touched, and only watching the reads
    can tell those apart.
    """
    bundle = _rar(
        tmp_path / "bundle.rar",
        [("a.txt", "first-alpha"), ("b.txt", "second-beta"), ("c.txt", "third-gamma")],
    )
    delivered = _watch_reads(monkeypatch)

    entries = RarExtractor().iter_children(bundle)
    first = next(entries)

    assert first.name == "a.txt"
    assert first.data == b"first-alpha"
    seen = b"".join(delivered)
    assert b"first-alpha" in seen, "the yielded entry's own bytes must have been read"
    assert b"second-beta" not in seen
    assert b"third-gamma" not in seen
    # Abandoning the iterator partway is what the expansion budget does when a
    # bound is reached, so it must not raise on the way out.
    entries.close()


def test_the_expansion_budget_stops_a_rar_before_its_later_entries_are_read(
    context, casefile, tmp_path, monkeypatch
):
    """Why laziness is worth a test at all, exercised through the shipped path.

    The bound exists to refuse an archive partway, and it can only do that if
    the entries beyond the refusal were never read. So this drives a real ingest
    with a bound the second entry crosses and then asks libarchive what it was
    made to deliver. The limit is injected exactly as `tests/test_expansion_budget.py`
    does, because the real defaults would need a 20 GB archive.

    One entry beyond the accepted set *is* read, and that is not a defect: the
    service weighs a child on `len(child.data)`, because a declared size is
    chosen by whoever built the archive and this module refuses to trust it. So
    the entry that breaks the bound must arrive to break it. What must never be
    read is anything after that — and an implementation that gathered the
    archive into a list before yielding would read all three.
    """
    from jackryan.ingestion.budget import ExpansionBudget

    budget = ExpansionBudget(max_descendants=1)
    context.ingestion._limits = (
        budget.max_depth,
        budget.max_descendants,
        budget.max_extracted_bytes,
    )
    bundle = _rar(
        tmp_path / "bundle.rar",
        [("a.txt", "first-alpha"), ("b.txt", "second-beta"), ("c.txt", "third-gamma")],
    )
    delivered = _watch_reads(monkeypatch)

    report = context.ingestion.ingest(casefile.short_id, bundle)

    assert report.exhausted_by is not None
    seen = b"".join(delivered)
    assert b"first-alpha" in seen
    assert b"second-beta" in seen, "the entry that broke the bound is what breaks it"
    assert b"third-gamma" not in seen, "an entry past the refusal was read anyway"
    stored = {d.filename for d in context.store.list_documents(casefile.id, include_expanded=True)}
    assert stored == {"bundle.rar", "a.txt"}


# -- an archive that cannot be opened --------------------------------------


def test_an_encrypted_rar_fails_the_document_naming_encryption(tmp_path):
    bundle = _rar(tmp_path / "locked.rar", [("secret.txt", "x")], header_encrypted=True)

    with pytest.raises(ExtractionError) as raised:
        RarExtractor().extract(bundle)

    assert "locked.rar" in str(raised.value)
    assert "encrypted" in str(raised.value)
    assert "password" in str(raised.value)


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
    """A RAR5 signature over zeroes, whose first block declares a zero-length header.

    libarchive does refuse this one, so the assertion on the walk's own finding
    is what makes the test say something about this module. No block header is
    empty, so a declared length of zero is a positive malformation — and without
    that branch the walk steps five bytes at a time through the zeroes to the
    same refusal reported as an absent main header, which is true but is not
    what is wrong with the file.
    """
    archive = tmp_path / "truncated.rar"
    archive.write_bytes(_SIGNATURE + b"\x00" * 32)

    assert containers._survey(archive, "rar5").unreadable == containers._MALFORMED
    with pytest.raises(ExtractionError) as raised:
        RarExtractor().extract(archive)

    assert "truncated.rar" in str(raised.value)


# -- an archive that was cut short -----------------------------------------
#
# libarchive's RAR5 reader answers an unparseable or truncated header with
# end-of-archive rather than an error, so every shape below used to arrive as
# `Extraction(entries=0)` with no exception and no refusal — stored as an
# ingested container with no children, and indistinguishable from `hollow.rar`,
# which is genuinely empty. That is the falsehood the spec's second requirement
# names: "holds nothing" and "could not be opened" are different claims about
# evidence.


def _cut_at(tmp_path, name: str, keep: int):
    """A complete two-entry archive, truncated to its first `keep` bytes."""
    full = _rar(tmp_path / "full.rar", [("a.txt", "alpha"), ("b.txt", "beta")]).read_bytes()
    path = tmp_path / name
    path.write_bytes(full[:keep])
    return path


_MAIN_BLOCK_END = len(_SIGNATURE) + len(_block(_HEAD_MAIN, 0, _vint(0)))
_FIRST_ENTRY_END = _MAIN_BLOCK_END + len(_file_block("a.txt", b"alpha"))


@pytest.mark.parametrize(
    ("label", "keep", "reason"),
    [
        ("the signature alone", len(_SIGNATURE), containers._NO_MAIN),
        ("the signature and four bytes", len(_SIGNATURE) + 4, containers._CUT),
        ("cut inside the first file header", _MAIN_BLOCK_END + 6, containers._CUT),
        ("cut inside the first entry's data", _FIRST_ENTRY_END - 2, containers._CUT),
        ("cut inside the second file header", _FIRST_ENTRY_END + 6, containers._CUT),
    ],
)
def test_a_truncated_rar_fails_rather_than_reading_as_empty(tmp_path, label, keep, reason):
    """Each shape, and which finding refused it.

    The reason is asserted, not just the refusal, because the walk establishes
    this from four separate pieces of arithmetic and they do not all catch the
    same shapes. Asserting the refusal alone leaves three of the four provable
    only by deleting them one at a time and watching nothing change — and one of
    them would then be indistinguishable from the fallback that reports a header
    it merely failed to parse, which is a weaker and less accurate claim about
    the same file.
    """
    archive = _cut_at(tmp_path, "cut.rar", keep)

    assert containers._survey(archive, "rar5").unreadable == reason, label
    with pytest.raises(ExtractionError) as raised:
        RarExtractor().extract(archive)

    assert "cut.rar" in str(raised.value)
    assert reason in str(raised.value)


def test_a_rar5_header_whose_size_field_is_nonsense_fails(tmp_path):
    """A ten-byte size vint, which no valid header carries.

    Reported as a 24-byte file that returned `Extraction(entries=0)`. The walk's
    vint reader refuses a value that cannot fit in 64 bits, and reaching that at
    the end of the file is a positive statement that the headers do not account
    for it — not a byte the walk failed to understand and should defer on. This
    is the one shape that arrives as "could not be read" rather than as
    "declares more bytes than the file contains", and the distinction is the
    walk's stance: the fallback claims only that it could not account for the
    file, never that it understood what it found.
    """
    archive = tmp_path / "nonsense.rar"
    archive.write_bytes(_SIGNATURE + b"\x00" * 4 + b"\x80" * 10 + b"\x00" * 2)

    assert containers._survey(archive, "rar5").unreadable == containers._MALFORMED
    with pytest.raises(ExtractionError) as raised:
        RarExtractor().extract(archive)

    assert "nonsense.rar" in str(raised.value)


def test_a_truncated_rar_is_not_stored_as_a_container_with_no_children(
    context, casefile, tmp_path
):
    """The harm, end to end, and the pair `hollow.rar` must still be told from."""
    cut = _cut_at(tmp_path, "cut.rar", _MAIN_BLOCK_END + 6)

    report = context.ingestion.ingest(casefile.short_id, cut)

    assert report.failed == 1
    assert context.store.list_documents(casefile.id, include_expanded=True) == []


def test_a_truncated_rar_does_not_stop_the_run(context, casefile, tmp_path):
    folder = tmp_path / "dump"
    folder.mkdir()
    full = _rar(folder / "full.rar", [("a.txt", "alpha"), ("b.txt", "beta")]).read_bytes()
    (folder / "cut.rar").write_bytes(full[: _MAIN_BLOCK_END + 6])
    (folder / "plain.md").write_text("# Memo\n\nThe tariff was deferred.")

    report = context.ingestion.ingest(casefile.short_id, folder)

    assert report.failed == 1
    names = {d.filename for d in context.store.list_documents(casefile.id, include_expanded=True)}
    assert "plain.md" in names
    assert "cut.rar" not in names


# Past the 7-byte marker block and the 13-byte main header, then past the first
# entry. Named so the offsets below say what they cut into.
_RAR3_MAIN_END = len(_RAR3_SIGNATURE) + 13
_RAR3_FIRST_ENTRY_END = _RAR3_MAIN_END + len(_rar3_file_block("a.txt", b"alpha", 0, None))


@pytest.mark.parametrize(
    ("label", "keep"),
    [
        ("cut inside the first file header", _RAR3_MAIN_END + 6),
        ("cut inside the first entry's data", _RAR3_FIRST_ENTRY_END - 3),
        ("cut inside the second file header", _RAR3_FIRST_ENTRY_END + 6),
    ],
)
def test_a_truncated_rar3_fails_as_well(tmp_path, label, keep):
    """The older generation, where the walk is not the only thing refusing.

    libarchive's RAR3 reader does raise on a cut file — unlike its RAR5 reader,
    which answers with end-of-archive — so a test asserting only the refusal
    would pass with this walk's truncation detection removed and would prove
    nothing about it. The walk's own finding is therefore asserted as well, and
    the three shapes reach both of the ways it is established: a block header
    that runs out of file, and a complete header declaring data that does not
    fit behind it.
    """
    full = _rar3(tmp_path / "full.rar", [("a.txt", "alpha"), ("b.txt", "beta")]).read_bytes()
    archive = tmp_path / "cut.rar"
    archive.write_bytes(full[:keep])

    assert containers._survey(archive, "rar").unreadable is not None, label
    with pytest.raises(ExtractionError) as raised:
        RarExtractor().extract(archive)

    assert "cut.rar" in str(raised.value)


def test_a_well_formed_archive_with_trailing_bytes_is_still_read(tmp_path):
    """The reason the walk stops at the end-of-archive block.

    A `.rar` in a real dump can carry bytes after its last block — padding from
    a transfer, a recovery volume's remnant. Parsing those as a further header
    would make the truncation finding refuse a readable archive, which is the
    one thing a walk may never do.
    """
    archive = _rar(tmp_path / "padded.rar", [("a.txt", "alpha")])
    archive.write_bytes(archive.read_bytes() + b"\x00" * 3)

    assert RarExtractor().extract(archive).metadata["entries"] == "1"
    assert [c.data for c in RarExtractor().iter_children(archive)] == [b"alpha"]


# -- one volume of a set is not a whole archive ----------------------------
#
# Every test here builds an archive that *is* a volume and names it something
# a filename rule would not catch. What stood here before was a complete,
# single-volume archive named `split.part1.rar`, so it exercised a regular
# expression and nothing else — and its docstring's claim that libarchive
# raises on such an archive is false: a first volume ending in a well-formed
# end-of-archive block lists cleanly and delivers a split entry's first
# fragment as though it were the entry.


def _rar5_first_volume(
    path,
    *,
    archive_flags: int = _ARCHIVE_VOLUME,
    entry_flags: int = _SPLIT_AFTER,
):
    """The first volume of a split RAR5 set, named however the caller likes.

    Two entries: one complete, one whose declared 20 bytes are only 10 bytes
    present because the rest is in the next volume. Both statements the format
    makes about this are settable so a test can strip one and prove which signal
    did the refusing.
    """
    out = bytearray(_SIGNATURE)
    out += _block(_HEAD_MAIN, 0, _vint(archive_flags))
    out += _file_block("whole.txt", b"complete entry")
    out += _file_block("split.txt", b"FIRST-HALF", declared=20, header_flags=entry_flags)
    # Flagged "not the last volume", which is what makes libarchive read this
    # as a finished archive rather than raising.
    out += _block(_HEAD_ENDARC, 0, _vint(_ENDARC_NOT_LAST))
    path.write_bytes(bytes(out))
    return path


def test_a_multi_volume_rar_is_refused_with_a_remedy(tmp_path):
    """The whole point: a volume set's first volume, named like any other file."""
    archive = _rar5_first_volume(tmp_path / "archive.rar")

    with pytest.raises(ExtractionError) as raised:
        RarExtractor().extract(archive)

    assert "archive.rar" in str(raised.value)
    assert "multi-volume" in str(raised.value)
    assert "join the volumes" in str(raised.value)


def test_the_main_header_volume_flag_alone_refuses_a_volume(tmp_path):
    """The primary signal, isolated by stripping the per-entry one.

    This is the archive's own statement that it belongs to a set, and it is set
    on every volume of one — which is why it replaced the filename rule rather
    than joining it.
    """
    archive = _rar5_first_volume(tmp_path / "archive.rar", entry_flags=0)

    with pytest.raises(ExtractionError) as raised:
        RarExtractor().extract(archive)

    assert "volume flag" in str(raised.value)


def test_a_split_entry_alone_refuses_a_volume(tmp_path):
    """The second, independent signal, isolated by stripping the first.

    An archive whose main header was rewritten to drop the volume flag still
    carries entries that say their data continues elsewhere, and reading such an
    entry as a whole document is the harm — `split.txt` would otherwise be
    stored with 10 of its 20 declared bytes and nothing would say so.
    """
    archive = _rar5_first_volume(tmp_path / "archive.rar", archive_flags=0)

    with pytest.raises(ExtractionError) as raised:
        RarExtractor().extract(archive)

    assert "continues in another volume" in str(raised.value)


def test_a_volume_is_refused_by_the_expansion_pass_as_well(tmp_path):
    """Both passes, from the one guard.

    `iter_children` repeated neither this refusal nor the encryption one while
    its comment claimed parity with the listing pass, so a volume expanded
    without a listing first yielded `split.txt` truncated and called it whole.
    """
    archive = _rar5_first_volume(tmp_path / "archive.rar")

    with pytest.raises(ExtractionError) as raised:
        list(RarExtractor().iter_children(archive))

    assert "multi-volume" in str(raised.value)


def test_a_rar3_volume_is_refused_on_its_main_header_flag(tmp_path):
    """The older generation says the same thing in its own header.

    Old-style sets are `name.rar` plus `name.r00`, so the first volume carries
    no `.partN` at all and a filename rule never saw it.
    """
    archive = _rar3(
        tmp_path / "legacy.rar", [("piece.txt", "half a document")], main_flags=_MHD_VOLUME
    )

    with pytest.raises(ExtractionError) as raised:
        RarExtractor().extract(archive)

    assert "multi-volume" in str(raised.value)
    assert "volume flag" in str(raised.value)


def test_a_rar3_split_entry_is_refused(tmp_path):
    archive = _rar3(
        tmp_path / "legacy.rar",
        [("piece.txt", "half a document")],
        file_flags=_LHD_SPLIT_AFTER,
    )

    with pytest.raises(ExtractionError) as raised:
        RarExtractor().extract(archive)

    assert "continues in another volume" in str(raised.value)


def test_an_ordinary_archive_named_like_a_volume_is_still_read(tmp_path):
    """The cost of the filename rule, now paid by nobody.

    `.partN` in a stem is a name, and a name in an investigative dump is chosen
    by whoever handed it over — an analyst numbering their own files gets
    `evidence.part1.rar`. Refusing that told them to join volumes that do not
    exist and dropped the document from the corpus, which in a dump of thousands
    of files is as bad as reading a fragment. Neither generation's volume flag
    is set here, so neither is refused.
    """
    modern = _rar(tmp_path / "evidence.part1.rar", [("a.txt", "alpha")])
    legacy = _rar3(tmp_path / "evidence.part2.rar", [("b.txt", "beta")])

    assert RarExtractor().extract(modern).metadata["entries"] == "1"
    assert RarExtractor().extract(legacy).metadata["entries"] == "1"


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


def test_the_host_reader_satisfies_the_floor_when_required():
    """The one test that looks at the real host rather than the patched value.

    Set `JACKRYAN_REQUIRE_RAR=1` to demand a genuinely patched library — the
    check to run in an image build or a release gate, where "the tests passed"
    must mean the shipped configuration works rather than that a fixture stood
    in for it.
    """
    import os

    # `_REAL_LIBARCHIVE`, not a call to the library: the autouse fixture has
    # already raised what the library reports, so asking it now would hand this
    # test the answer it is supposed to be checking.
    if os.environ.get("JACKRYAN_REQUIRE_RAR") == "1":
        assert _REAL_LIBARCHIVE >= containers.MIN_LIBARCHIVE, (
            f"JACKRYAN_REQUIRE_RAR=1 but this host has libarchive "
            f"{_REAL_LIBARCHIVE}, below the {containers.MIN_LIBARCHIVE} floor"
        )
    assert rar_status() != containers.RAR_UNAVAILABLE


# -- the file is handled on what it is, not what it is named ---------------


@pytest.mark.parametrize("builder", ["zip", "tar", "gzip"])
def test_another_archive_format_behind_a_rar_suffix_is_refused(tmp_path, builder):
    """Found by a security review, and it was storing a falsehood.

    libarchive's reader defaults to trying every format it knows, so before the
    signature check a ZIP or tar named `.rar` was read by this extractor and
    stored asserting `application/vnd.rar`. Two harms, not one: the media type
    was a false statement about the evidence, and a ZIP was routed around
    `ZipExtractor`, whose symlink refusal this extractor does not reproduce.
    """
    import gzip as gziplib
    import io
    import tarfile
    import zipfile

    path = tmp_path / "disguised.rar"
    if builder == "zip":
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("inner.txt", "zip content")
    elif builder == "tar":
        with tarfile.open(path, "w") as archive:
            info = tarfile.TarInfo("inner.txt")
            payload = b"tar content"
            info.size = len(payload)
            archive.addfile(info, io.BytesIO(payload))
    else:
        path.write_bytes(gziplib.compress(b"plain stream"))

    with pytest.raises(ExtractionError) as raised:
        RarExtractor().extract(path)

    assert "not a RAR archive" in str(raised.value)
    assert "disguised.rar" in str(raised.value)


def test_a_rar3_archive_is_read_by_the_reader_that_handles_it(context, casefile, tmp_path):
    """Both generations are accepted, each named to its own reader, and read.

    Pinning only RAR5 would refuse a genuine older archive, and libarchive's
    RAR5 reader does not read RAR3. The dump that motivated this change is
    entirely RAR5, but a `.rar` from 2005 in an investigative dump is not an
    exotic hypothetical.

    What this test used to be was sixteen zero bytes behind a RAR3 signature
    handed to `_rar_format` and compared against a string. It opened nothing and
    read nothing while being the file's only RAR3 coverage, which is how the
    encryption check running for RAR5 alone survived review. The format
    assertion is kept — it is what makes the media type honest — and both
    archives are now actually ingested.
    """
    from jackryan.ingestion.containers import _rar_format

    modern = _rar(tmp_path / "modern.rar", [("new.txt", "the modern clause")])
    legacy = _rar3(tmp_path / "legacy.rar", [("old.txt", "the legacy clause")])

    assert _rar_format(modern) == "rar5"
    assert _rar_format(legacy) == "rar"
    report = context.ingestion.ingest(casefile.short_id, tmp_path)
    assert report.failed == 0
    stored = {
        d.filename: d
        for d in context.store.list_documents(casefile.id, include_expanded=True)
    }
    assert {"modern.rar", "legacy.rar", "new.txt", "old.txt"} <= set(stored)
    assert "legacy clause" in stored["old.txt"].extracted_text
    assert stored["legacy.rar"].media_type == "application/vnd.rar"


def test_an_empty_file_named_rar_is_refused_naming_what_was_expected(tmp_path):
    path = tmp_path / "hollow.rar"
    path.write_bytes(b"")

    with pytest.raises(ExtractionError) as raised:
        RarExtractor().extract(path)

    assert "not a RAR archive" in str(raised.value)


# -- entries that are pointers, not files ---------------------------------


_EXTRA_REDIRECTION = 5

_REDIRECT_SYMLINK = 1
_REDIRECT_WINDOWS_SYMLINK = 2
_REDIRECT_HARDLINK = 4


def _link_block(name: str, kind: int, target: bytes) -> bytes:
    """A RAR5 entry that is a redirection rather than content.

    The redirection lives in the file header's extra area. `HAS_DATA` is set
    with a zero length because libarchive's reader requires the data-size field
    to be present and refuses the whole archive without it.
    """
    record = _vint(_EXTRA_REDIRECTION) + _vint(kind) + _vint(0) + _vint(len(target)) + target
    encoded = name.encode()
    body = (
        _vint(0x0004)
        + _vint(0)
        + _vint(0)
        + struct.pack("<I", zlib.crc32(b"") & 0xFFFFFFFF)
        + _vint(0)
        + _vint(0)
        + _vint(len(encoded))
        + encoded
    )
    return _block(
        _HEAD_FILE, _HAS_EXTRA | _HAS_DATA, body, data=b"", extra=_vint(len(record)) + record
    )


def test_a_link_entry_is_refused_as_not_a_regular_file(tmp_path):
    """Found by a security review, and `entry.isreg` alone did not catch it.

    libarchive's RAR5 reader sets `AE_IFREG` on a **hardlink** unconditionally,
    so a hardlink arrives with `isreg=True`, `islnk=True` and an attacker-chosen
    `linkpath` — and an `isreg` test admits it as a zero-byte file. A symlink is
    excluded by `isreg`, but was excluded silently, where `TarExtractor` reports
    the same thing.

    A test built on a tar fixture cannot stand in for this: the tar reader
    promotes a hardlink to `AE_IFREG` only when the entry has a non-zero size,
    which is the opposite behaviour.
    """
    out = bytearray(_SIGNATURE)
    out += _block(_HEAD_MAIN, 0, _vint(0))
    out += _file_block("real.txt", b"alpha")
    out += _link_block("hard.txt", _REDIRECT_HARDLINK, b"../../etc/passwd")
    out += _link_block("sym.txt", _REDIRECT_SYMLINK, b"/etc/passwd")
    out += _link_block("winsym.txt", _REDIRECT_WINDOWS_SYMLINK, b"..\\..\\secrets")
    out += _block(_HEAD_ENDARC, 0, _vint(0))
    archive = tmp_path / "links.rar"
    archive.write_bytes(bytes(out))

    extraction = RarExtractor().extract(archive)

    assert extraction.text.splitlines() == ["real.txt"]
    assert {r.split(":")[0] for r in extraction.refusals} == {"hard.txt", "sym.txt", "winsym.txt"}
    assert all("not a regular file" in r for r in extraction.refusals)
    # Reported, not merely absent: an entry the archive calls a pointer must not
    # be silently dropped, or the listing overstates what was read.
    assert [c.name for c in RarExtractor().iter_children(archive)] == ["real.txt"]


# -- encryption that leaves the headers readable ---------------------------


_EXTRA_CRYPT = 1


def _data_encrypted_rar(path, name="secret.txt", payload=b"CIPHERTEXT"):
    """An archive in WinRAR's *default* password mode.

    Entry data is encrypted and the headers stay readable — the mode you get
    without ticking "encrypt file names". The record is what marks it.
    """
    record = _vint(_EXTRA_CRYPT) + _vint(0) + _vint(0) + b"\x00" * 40
    encoded = name.encode()
    body = (
        _vint(0x0004)
        + _vint(len(payload))
        + _vint(0)
        + struct.pack("<I", zlib.crc32(payload) & 0xFFFFFFFF)
        + _vint(0)
        + _vint(0)
        + _vint(len(encoded))
        + encoded
    )
    out = bytearray(_SIGNATURE)
    out += _block(_HEAD_MAIN, 0, _vint(0))
    out += _block(
        _HEAD_FILE, _HAS_EXTRA | _HAS_DATA, body, data=payload,
        extra=_vint(len(record)) + record,
    )
    out += _block(_HEAD_ENDARC, 0, _vint(0))
    path.write_bytes(bytes(out))
    return path


def test_a_data_encrypted_archive_fails_rather_than_yielding_ciphertext(tmp_path):
    """The worse half of the encryption case, and libarchive cannot answer it.

    Header encryption is refused by libarchive itself. Data-only encryption —
    WinRAR's default — is not: on 3.7.4, which is both this host and Debian
    trixie, the RAR5 reader skips the per-entry crypt record as an unsupported
    attribute, `archive_entry_is_data_encrypted` returns 0, and the listing pass
    succeeds. Before this check the container was stored and `iter_children`
    handed back **ciphertext as the document's content**, to be chunked,
    embedded and indexed as though it were text. That is worse than the empty
    container it was mistaken for, because nothing downstream can detect it.
    """
    archive = _data_encrypted_rar(tmp_path / "locked.rar")

    with pytest.raises(ExtractionError) as raised:
        RarExtractor().extract(archive)

    assert "encrypted" in str(raised.value)
    assert "password" in str(raised.value)


def test_both_password_modes_report_the_same_way(tmp_path):
    header = _rar(tmp_path / "h.rar", [("a.txt", "x")], header_encrypted=True)
    data = _data_encrypted_rar(tmp_path / "d.rar")

    for archive in (header, data):
        with pytest.raises(ExtractionError) as raised:
            RarExtractor().extract(archive)
        assert "encrypted" in str(raised.value)


def test_a_rar3_encrypted_entry_is_refused_rather_than_read_as_ciphertext(tmp_path):
    """The blocker, and the reason this file now builds RAR3 archives.

    `FHD_PASSWORD` in a RAR3 file header is WinRAR's password mode for the older
    generation. The encryption check was reached only when the signature said
    RAR5, so such an archive met no check whatever: libarchive listed it, said
    nothing, and delivered raw ciphertext through `read_data` to be stored as
    the document's text, chunked and embedded. Measured on 3.8.9 before the fix
    — a clean two-entry listing, `refusals=[]`, and a child document whose
    extracted text was the ciphertext.

    The archive stores the CRC of the plaintext, as a real one does, so the
    fixture cannot be mistaken for one whose CRC merely happens to match.
    """
    cipher = bytes(range(64))  # ciphertext-shaped: opaque, a multiple of 16
    archive = _rar3(
        tmp_path / "locked.rar",
        [("memo.txt", cipher), ("scan.md", cipher)],
        file_flags=_FHD_PASSWORD | _FHD_SALT,
        file_crc=0x12345678,
    )

    with pytest.raises(ExtractionError) as raised:
        RarExtractor().extract(archive)

    assert "locked.rar" in str(raised.value)
    assert "encrypted" in str(raised.value)
    assert "password" in str(raised.value)


def test_a_rar3_encrypted_entry_is_refused_by_the_expansion_pass_as_well(tmp_path):
    """The half that actually leaked, since `extract` is not what reads bytes."""
    cipher = bytes(range(64))
    archive = _rar3(
        tmp_path / "locked.rar",
        [("memo.txt", cipher)],
        file_flags=_FHD_PASSWORD | _FHD_SALT,
        file_crc=0x12345678,
    )

    with pytest.raises(ExtractionError) as raised:
        list(RarExtractor().iter_children(archive))

    assert "encrypted" in str(raised.value)


def test_a_rar3_encrypted_archive_stores_nothing(context, casefile, tmp_path):
    """End to end, which is where the ciphertext was reaching the corpus."""
    cipher = bytes(range(64))
    archive = _rar3(
        tmp_path / "locked.rar",
        [("memo.txt", cipher)],
        file_flags=_FHD_PASSWORD | _FHD_SALT,
        file_crc=0x12345678,
    )

    report = context.ingestion.ingest(casefile.short_id, archive)

    assert report.failed == 1
    assert any("encrypt" in outcome.detail for outcome in report.outcomes)
    assert context.store.list_documents(casefile.id, include_expanded=True) == []


def test_a_rar3_header_encrypted_archive_reports_like_the_others(tmp_path):
    """`MHD_PASSWORD` encrypts every header after the main one.

    libarchive does refuse this on its own, with "RAR encryption support
    unavailable" — a message that names neither a password nor a remedy. It is
    detected here so that all four combinations of generation and password mode
    reach one sentence an analyst can act on.
    """
    archive = _rar3(
        tmp_path / "locked.rar", [("memo.txt", b"x" * 16)], main_flags=_MHD_PASSWORD
    )

    with pytest.raises(ExtractionError) as raised:
        RarExtractor().extract(archive)

    assert "encrypted" in str(raised.value)
    assert "password" in str(raised.value)


def test_libarchive_own_verdict_refuses_an_encrypted_entry_when_the_walk_is_blind(
    tmp_path, monkeypatch
):
    """The second net, isolated, and the reason it was added.

    Two independent checks answer this question, and a test that any one of them
    satisfies proves neither. Here the header walk is made to find nothing at
    all — which is what a walk does with a block layout it cannot parse — and
    the archive must still be refused, on `archive_entry_is_data_encrypted`.

    That flag is the authority the walk cannot be. `libarchive-c` does not wrap
    it; it is declared in `containers` by hand.
    """
    cipher = bytes(range(64))
    archive = _rar3(
        tmp_path / "locked.rar",
        [("memo.txt", cipher)],
        file_flags=_FHD_PASSWORD | _FHD_SALT,
        file_crc=0x12345678,
    )
    monkeypatch.setattr(containers, "_survey", lambda path, fmt: containers._Survey())

    with pytest.raises(ExtractionError) as raised:
        RarExtractor().extract(archive)

    assert "encrypted" in str(raised.value)


def test_the_header_walk_refuses_an_encrypted_entry_when_libarchive_is_silent(
    tmp_path, monkeypatch
):
    """The first net, isolated, and the reason it cannot be dropped either.

    libarchive's flag is 0 for a data-encrypted RAR5 entry on 3.7.4, which is
    the version Debian trixie ships and the one this reader may still be pointed
    at by `LIBARCHIVE`. Silencing the flag models that, and the walk must still
    refuse both generations.
    """
    monkeypatch.setattr(containers, "_entry_data_encrypted", lambda reader, entry: False)
    modern = _data_encrypted_rar(tmp_path / "modern.rar")
    legacy = _rar3(
        tmp_path / "legacy.rar",
        [("memo.txt", bytes(range(64)))],
        file_flags=_FHD_PASSWORD | _FHD_SALT,
        file_crc=0x12345678,
    )

    for archive in (modern, legacy):
        with pytest.raises(ExtractionError) as raised:
            RarExtractor().extract(archive)
        assert "encrypted" in str(raised.value)


def test_the_header_walk_does_not_refuse_an_ordinary_archive(tmp_path):
    """Positive detection only.

    A walk may add a refusal; it must never be the reason a readable archive is
    rejected. A hand-written header walk that guessed wrong would refuse real
    evidence, so nothing is claimed about encryption or volumes unless a crypt
    record or a volume flag was positively identified — in either generation.
    """
    modern = _rar(tmp_path / "plain.rar", [("a.txt", "alpha"), ("sub/b.txt", "beta")])
    legacy = _rar3(tmp_path / "legacy.rar", [("a.txt", "alpha"), ("sub/b.txt", "beta")])

    for path, fmt in ((modern, "rar5"), (legacy, "rar")):
        survey = containers._survey(path, fmt)
        assert survey.encrypted is None
        assert survey.volume is None
        assert survey.unreadable is None


# -- names that are not UTF-8 ----------------------------------------------


def test_a_non_utf8_entry_name_is_decoded_not_repr_ed():
    """A RAR3 archive written on Windows with Cyrillic names is this shape.

    `libarchive-c` returns `bytes` for a name it cannot decode. `str()` on that
    gives the Python repr, whose suffix ends in a quote and matches no
    extractor — so the child is refused as unroutable and the container's
    listing carries a repr as searchable text.
    """
    from jackryan.ingestion.containers import _entry_name

    class _RawName:
        pathname = "договор.pdf".encode("cp1251")

    name = _entry_name(_RawName())

    assert not name.startswith("b'")
    assert name.endswith(".pdf"), "the suffix must survive, or the child cannot route"


# -- the reader's version is a floor, not a preference ---------------------


def _pretend_version(monkeypatch, number: int) -> None:
    import libarchive.ffi

    monkeypatch.setattr(libarchive.ffi, "version_number", lambda: number)


def test_a_vulnerable_libarchive_is_refused_naming_the_advisory(tmp_path, monkeypatch):
    """A quietly vulnerable parser is worse than an absent one.

    3.7.4's RAR5 reader carries CVE-2026-14164, a double free reachable by a
    crafted archive. The crash is `SIGABRT`, so no `except` sees it and the
    process dies — and ingestion runs in a thread pool inside the API server.
    Reading archives with it and hoping is not a policy, so the reader declines
    and says why.
    """
    archive = _rar(tmp_path / "a.rar", [("a.txt", "alpha")])
    _pretend_version(monkeypatch, 3_007_004)

    with pytest.raises(ExtractionError) as raised:
        RarExtractor().extract(archive)

    message = str(raised.value)
    assert "3.8.9 or newer" in message
    assert "3.7.4" in message
    assert "CVE-2026-14164" in message


def test_a_vulnerable_libarchive_reports_unavailable(monkeypatch):
    _pretend_version(monkeypatch, 3_007_004)

    assert rar_status() == containers.RAR_UNAVAILABLE


def test_the_floor_itself_is_accepted(monkeypatch, tmp_path):
    """Exactly at the floor must pass, or the boundary is off by one."""
    archive = _rar(tmp_path / "a.rar", [("a.txt", "alpha")])
    _pretend_version(monkeypatch, containers.MIN_LIBARCHIVE)

    assert RarExtractor().extract(archive).metadata["entries"] == "1"
    assert rar_status() == "3.8.9"


def test_the_reported_version_is_spelled_the_way_a_refusal_spells_it(monkeypatch, tmp_path):
    """One host, one spelling of one version.

    The surfaces reported libarchive's packed integer — `rar: 3008009` — while
    the refusal an operator reads next formats the same number as `3.8.9`. Two
    spellings of one fact read as two facts, and the operator has to work out
    that the version they were told to install is the version they have.

    The vocabulary stays two-valued: a version, or the literal `unavailable`.
    The docker gate asserts on the second, so nothing here may widen it.
    """
    archive = _rar(tmp_path / "a.rar", [("a.txt", "alpha")])
    _pretend_version(monkeypatch, 3_007_004)

    with pytest.raises(ExtractionError) as raised:
        RarExtractor().extract(archive)

    assert rar_status() == containers.RAR_UNAVAILABLE
    _pretend_version(monkeypatch, 3_009_000)
    assert rar_status() == "3.9.0"
    # The spelling a refusal uses, taken from the message rather than restated.
    assert "3.8.9 or newer" in str(raised.value)
    assert containers.RAR_UNAVAILABLE == "unavailable"


def test_a_vulnerable_reader_fails_the_archive_not_the_run(
    context, casefile, tmp_path, monkeypatch
):
    folder = tmp_path / "dump"
    folder.mkdir()
    _rar(folder / "bundle.rar", [("a.txt", "alpha")])
    (folder / "plain.md").write_text("# Memo\n\nThe tariff was deferred.")
    _pretend_version(monkeypatch, 3_007_004)

    report = context.ingestion.ingest(casefile.short_id, folder)

    assert report.failed == 1
    names = {d.filename for d in context.store.list_documents(casefile.id, include_expanded=True)}
    assert "plain.md" in names
    assert "bundle.rar" not in names
