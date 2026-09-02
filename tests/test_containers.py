"""Containers: what comes out of a file that holds other files.

Every fixture here is synthetic. No real case material enters the repository.
"""

from __future__ import annotations

import email.message
import io
import tarfile
import zipfile

import pytest
from openpyxl import Workbook

from jackryan.ingestion.budget import ExpansionBudget
from jackryan.ingestion.router import FormatRouter


@pytest.fixture
def casefile(context):
    return context.casefiles.create("Container Inquiry")


@pytest.fixture
def router():
    return FormatRouter()


def _message(subject="Harbour lease", body="The lease was signed.", attachment=None):
    message = email.message.EmailMessage()
    message["From"] = "clerk@example.com"
    message["To"] = "board@example.com"
    message["Cc"] = "registry@example.com"
    message["Date"] = "Mon, 01 Mar 2021 09:00:00 +0000"
    message["Subject"] = subject
    message.set_content(body)
    if attachment is not None:
        name, data = attachment
        message.add_attachment(
            data, maintype="text", subtype="plain", filename=name
        )
    return message


def _zip(path, entries):
    with zipfile.ZipFile(path, "w") as archive:
        for name, data in entries:
            archive.writestr(name, data)
    return path


# -- archives --------------------------------------------------------------


def test_a_zip_of_a_document_yields_both_documents(context, casefile, tmp_path):
    bundle = _zip(tmp_path / "bundle.zip", [("notes/memo.md", "# Memo\n\nThe tariff was deferred.")])

    report = context.ingestion.ingest(casefile.short_id, bundle)

    assert report.failed == 0
    documents = context.store.list_documents(casefile.id, include_expanded=True)
    names = {d.filename for d in documents}
    assert names == {"bundle.zip", "memo.md"}
    memo = next(d for d in documents if d.filename == "memo.md")
    assert "tariff" in memo.extracted_text


def test_the_container_is_a_document_and_its_entries_are_its_children(
    context, casefile, tmp_path
):
    bundle = _zip(tmp_path / "bundle.zip", [("a.txt", "alpha"), ("b.txt", "beta")])

    context.ingestion.ingest(casefile.short_id, bundle)

    top = context.store.list_documents(casefile.id)
    assert [d.filename for d in top] == ["bundle.zip"]
    assert top[0].child_count == 2
    children = context.store.list_children(top[0].id)
    assert {c.filename for c in children} == {"a.txt", "b.txt"}
    assert all(c.parent_id == top[0].id for c in children)


def test_an_unsupported_entry_does_not_fail_the_container(context, casefile, tmp_path):
    bundle = _zip(
        tmp_path / "bundle.zip", [("good.txt", "readable"), ("photo.raw", "\x00\x01")]
    )

    report = context.ingestion.ingest(casefile.short_id, bundle)

    assert report.failed == 0
    assert any("photo.raw" in r for r in report.refusals)
    assert not report.complete, "a refusal means the ingest was not complete"
    names = {d.filename for d in context.store.list_documents(casefile.id, include_expanded=True)}
    assert "good.txt" in names


def test_a_traversing_entry_is_refused_and_its_siblings_survive(
    context, casefile, tmp_path
):
    bundle = _zip(
        tmp_path / "bundle.zip",
        [("../escape.txt", "outside"), ("inside.txt", "kept"), ("/abs.txt", "absolute")],
    )

    report = context.ingestion.ingest(casefile.short_id, bundle)

    names = {d.filename for d in context.store.list_documents(casefile.id, include_expanded=True)}
    assert "inside.txt" in names
    assert "escape.txt" not in names
    assert "abs.txt" not in names
    assert report.failed == 0


@pytest.mark.parametrize("mode,suffix", [("w", ".tar"), ("w:gz", ".tar.gz"), ("w:bz2", ".tar.bz2")])
def test_tar_archives_expand_whatever_the_compression(
    context, casefile, tmp_path, mode, suffix
):
    archive_path = tmp_path / f"bundle{suffix}"
    with tarfile.open(archive_path, mode) as archive:
        body = b"the dredging contract"
        info = tarfile.TarInfo("contract.txt")
        info.size = len(body)
        archive.addfile(info, io.BytesIO(body))

    context.ingestion.ingest(casefile.short_id, archive_path)

    names = {d.filename for d in context.store.list_documents(casefile.id, include_expanded=True)}
    assert "contract.txt" in names


def test_a_lone_gzip_is_not_mistaken_for_an_archive(router, tmp_path):
    assert router.extractor_for(tmp_path / "notes.txt.gz") is None


# -- directories -----------------------------------------------------------


def test_a_directory_is_a_traversal_not_a_document(context, casefile, tmp_path):
    root = tmp_path / "dump"
    (root / "sub" / "deeper").mkdir(parents=True)
    (root / "sub" / "deeper" / "note.txt").write_text("found deep", encoding="utf-8")

    context.ingestion.ingest(casefile.short_id, root)

    documents = context.store.list_documents(casefile.id, include_expanded=True)
    assert [d.filename for d in documents] == ["note.txt"]
    # The directories are in the path, but are not themselves documents.
    assert documents[0].parent_id is None
    assert documents[0].containment_path == "sub/deeper/note.txt"
    # ...and the path a walk recorded does not count toward identity, so the
    # same bytes in two folders stay one document.
    assert documents[0].identity_path == ""


def test_the_same_bytes_in_two_folders_are_one_document(context, casefile, tmp_path):
    root = tmp_path / "dump"
    (root / "a").mkdir(parents=True)
    (root / "b").mkdir(parents=True)
    (root / "a" / "note.txt").write_text("identical bytes", encoding="utf-8")
    (root / "b" / "note.txt").write_text("identical bytes", encoding="utf-8")

    context.ingestion.ingest(casefile.short_id, root)

    documents = context.store.list_documents(casefile.id, include_expanded=True)
    assert len(documents) == 1, "a directory walk keeps content-only identity"


# -- mail ------------------------------------------------------------------


def test_a_message_carries_its_headers_in_its_text(context, casefile, tmp_path):
    path = tmp_path / "note.eml"
    path.write_bytes(_message().as_bytes())

    context.ingestion.ingest(casefile.short_id, path)

    document = context.store.list_documents(casefile.id)[0]
    text = document.extracted_text
    assert "clerk@example.com" in text          # From
    assert "board@example.com" in text          # To
    assert "01 Mar 2021" in text                # Date
    assert "Harbour lease" in text              # Subject
    assert "The lease was signed." in text      # body


def test_an_attachment_is_a_child_of_its_message(context, casefile, tmp_path):
    path = tmp_path / "note.eml"
    path.write_bytes(_message(attachment=("schedule.txt", b"rent schedule")).as_bytes())

    context.ingestion.ingest(casefile.short_id, path)

    message = context.store.list_documents(casefile.id)[0]
    children = context.store.list_children(message.id)
    assert [c.filename for c in children] == ["schedule.txt"]
    assert "rent schedule" in children[0].extracted_text


def test_a_mailbox_is_expanded_into_its_messages(context, casefile, tmp_path):
    path = tmp_path / "box.mbox"
    path.write_bytes(
        b"From a@example.com\n" + _message(subject="First").as_bytes()
        + b"\nFrom b@example.com\n" + _message(subject="Second").as_bytes()
    )

    context.ingestion.ingest(casefile.short_id, path)

    mailbox = context.store.list_documents(casefile.id)[0]
    children = context.store.list_children(mailbox.id)
    assert len(children) == 2
    subjects = " ".join(c.extracted_text for c in children)
    assert "First" in subjects and "Second" in subjects


def test_a_corrupt_message_does_not_take_the_mailbox_with_it(context, casefile, tmp_path):
    path = tmp_path / "box.mbox"
    path.write_bytes(
        b"From a@example.com\n\x00\x00 not a message at all \x00\n"
        + b"\nFrom b@example.com\n" + _message(subject="Survivor").as_bytes()
    )

    report = context.ingestion.ingest(casefile.short_id, path)

    text = " ".join(
        d.extracted_text
        for d in context.store.list_documents(casefile.id, include_expanded=True)
    )
    assert "Survivor" in text
    assert report.ingested >= 2


# -- spreadsheets ----------------------------------------------------------


def test_a_workbook_keeps_sheets_and_rows_attributable(context, casefile, tmp_path):
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Leases"
    sheet.append(["party", "amount"])
    sheet.append(["Northgate Holdings", 12000])
    workbook.create_sheet("Blank")
    path = tmp_path / "book.xlsx"
    workbook.save(path)

    context.ingestion.ingest(casefile.short_id, path)

    text = context.store.list_documents(casefile.id)[0].extracted_text
    assert "## sheet: Leases" in text
    assert "row 2:" in text
    assert "Northgate Holdings" in text
    # An empty sheet is named, not a reason to refuse the workbook.
    assert "## sheet: Blank" in text


def test_delimited_files_survive_quoting_and_embedded_delimiters(
    context, casefile, tmp_path
):
    path = tmp_path / "rows.csv"
    path.write_text('name,note\n"Smith, J.","said ""yes"""\n', encoding="utf-8")

    context.ingestion.ingest(casefile.short_id, path)

    text = context.store.list_documents(casefile.id)[0].extracted_text
    assert "Smith, J." in text
    assert 'said "yes"' in text


# -- identity, reingest, and the budget ------------------------------------


def test_the_same_bytes_at_two_paths_are_two_documents(context, casefile, tmp_path):
    bundle = _zip(
        tmp_path / "bundle.zip",
        [("first/report.txt", "identical bytes"), ("second/report.txt", "identical bytes")],
    )

    context.ingestion.ingest(casefile.short_id, bundle)

    expanded = [
        d
        for d in context.store.list_documents(casefile.id, include_expanded=True)
        if d.parent_id is not None
    ]
    assert len(expanded) == 2, "which container carried it is itself evidence"
    assert {d.containment_path for d in expanded} == {
        "bundle.zip/first/report.txt",
        "bundle.zip/second/report.txt",
    }


def test_reingesting_a_container_keeps_every_descendant_identifier(
    context, casefile, tmp_path
):
    bundle = _zip(tmp_path / "bundle.zip", [("a.txt", "alpha"), ("b.txt", "beta")])

    context.ingestion.ingest(casefile.short_id, bundle)
    before = {d.id for d in context.store.list_documents(casefile.id, include_expanded=True)}
    context.ingestion.ingest(casefile.short_id, bundle)
    after = {d.id for d in context.store.list_documents(casefile.id, include_expanded=True)}

    assert before == after


def test_deleting_a_container_takes_its_descendants(context, casefile, tmp_path):
    bundle = _zip(tmp_path / "bundle.zip", [("a.txt", "alpha")])
    context.ingestion.ingest(casefile.short_id, bundle)
    container = context.store.list_documents(casefile.id)[0]
    assert context.store.descendant_ids(container.id)

    assert context.store.delete_document(container.id) is True

    assert context.store.list_documents(casefile.id, include_expanded=True) == []
    # The sidecars must have gone too. SQLite reuses rowids, so an orphaned
    # vector row makes the *next* ingest fail — which is the real assertion.
    again = context.ingestion.ingest(casefile.short_id, bundle)
    assert again.failed == 0
    assert again.ingested == 2


def test_a_count_says_whether_it_includes_expansions(context, casefile, tmp_path):
    bundle = _zip(tmp_path / "bundle.zip", [("a.txt", "alpha"), ("b.txt", "beta")])
    context.ingestion.ingest(casefile.short_id, bundle)

    stats = context.store.casefile_statistics(casefile.id)

    assert stats["documents"] == 3
    assert stats["documents_ingested"] == 1
    assert stats["documents_expanded"] == 2


# -- the rule at the seam every adapter crosses ----------------------------


def test_the_service_excludes_expansions_by_default_and_returns_them_on_request(
    context, casefile, tmp_path
):
    """The rule lives in the service, so no adapter has to know it.

    The store enforcing it alone would leave each adapter free to disagree —
    which is how a rule becomes two rules.
    """
    bundle = _zip(tmp_path / "bundle.zip", [("a.txt", "alpha"), ("b.txt", "beta")])
    context.ingestion.ingest(casefile.short_id, bundle)

    default = context.ingestion.list_documents(casefile.short_id)
    asked = context.ingestion.list_documents(casefile.short_id, include_expanded=True)

    assert [d.filename for d in default] == ["bundle.zip"]
    assert len(asked) == 3


def test_the_containment_chain_runs_from_the_ingested_file_down(
    context, casefile, tmp_path
):
    inner = tmp_path / "inner.zip"
    _zip(inner, [("deep.txt", "the deepest text")])
    outer = tmp_path / "outer.zip"
    with zipfile.ZipFile(outer, "w") as archive:
        archive.write(inner, "inner.zip")

    context.ingestion.ingest(casefile.short_id, outer)
    deep = next(
        d
        for d in context.store.list_documents(casefile.id, include_expanded=True)
        if d.filename == "deep.txt"
    )

    chain = context.ingestion.containment_chain(casefile.short_id, deep.short_id)

    assert [d.filename for d in chain] == ["outer.zip", "inner.zip", "deep.txt"]


def test_children_are_reachable_through_the_service(context, casefile, tmp_path):
    bundle = _zip(tmp_path / "bundle.zip", [("a.txt", "alpha")])
    context.ingestion.ingest(casefile.short_id, bundle)
    container = context.ingestion.list_documents(casefile.short_id)[0]

    children = context.ingestion.list_children(casefile.short_id, container.short_id)

    assert [c.filename for c in children] == ["a.txt"]


def test_search_still_reaches_text_the_listing_hides(context, casefile, tmp_path):
    """Hiding expansions from an inventory must not hide them from retrieval."""
    bundle = _zip(tmp_path / "bundle.zip", [("buried.txt", "the buried tariff clause")])
    context.ingestion.ingest(casefile.short_id, bundle)

    assert [d.filename for d in context.ingestion.list_documents(casefile.short_id)] == [
        "bundle.zip"
    ]
    hits = context.search.search(casefile.short_id, "buried tariff clause", limit=5)
    assert any(h.document.filename == "buried.txt" for h in hits)


# -- a container with no text of its own ------------------------------------


def test_an_empty_zip_is_still_stored_as_a_container(context, casefile, tmp_path):
    """`is_container` is load-bearing, and nothing asserted it for ZIP.

    A container is exempt from the rule that a document must yield usable text,
    because an archive's value is in its entries and refusing it would leave
    those entries with no parent. An archive holding nothing has no listing and
    therefore no text at all, so it is the only case where the exemption is what
    decides the outcome — and it was untested, which let a stray edit flip the
    flag with the whole suite still green.
    """
    bundle = _zip(tmp_path / "hollow.zip", [])

    report = context.ingestion.ingest(casefile.short_id, bundle)

    assert report.failed == 0
    documents = context.store.list_documents(casefile.id)
    assert [d.filename for d in documents] == ["hollow.zip"]
    assert documents[0].extracted_text == ""
    assert documents[0].child_count == 0


def test_an_empty_tar_is_still_stored_as_a_container(context, casefile, tmp_path):
    """The same claim for tar, for the same reason."""
    bundle = tmp_path / "hollow.tar"
    with tarfile.open(bundle, "w"):
        pass

    report = context.ingestion.ingest(casefile.short_id, bundle)

    assert report.failed == 0
    documents = context.store.list_documents(casefile.id)
    assert [d.filename for d in documents] == ["hollow.tar"]
    assert documents[0].extracted_text == ""
