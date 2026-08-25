"""Ingestion: identity from content, and refusal of what it cannot read safely."""

from __future__ import annotations

import pytest

from jackryan.errors import AmbiguousReferenceError, NotFoundError, ValidationError


@pytest.fixture
def casefile(context):
    return context.casefiles.create("Harbour Inquiry")


def test_ingesting_a_folder_reports_each_document(context, casefile, corpus):
    report = context.ingestion.ingest(casefile.short_id, corpus)
    assert report.ingested == 3
    assert report.failed == 0
    assert all(o.chunks > 0 for o in report.outcomes)


def test_unsupported_files_in_a_folder_are_skipped_quietly(context, casefile, corpus):
    (corpus / "photo.raw").write_bytes(b"\x00\x01\x02")
    report = context.ingestion.ingest(casefile.short_id, corpus)
    # Skipped, not failed: a mixed folder is normal and should not fail the run.
    assert report.failed == 0
    assert all("photo.raw" not in o.path for o in report.outcomes)


def test_reingesting_the_same_bytes_keeps_the_identifier(context, casefile, corpus):
    first = context.ingestion.ingest(casefile.short_id, corpus)
    before = {d.filename: d.id for d in context.ingestion.list_documents(casefile.short_id)}

    second = context.ingestion.ingest(casefile.short_id, corpus)
    after = {d.filename: d.id for d in context.ingestion.list_documents(casefile.short_id)}

    assert before == after
    assert all(o.status == "ingested" for o in first.outcomes)
    assert all(o.status == "reingested" for o in second.outcomes)
    assert len(after) == 3


def test_reingesting_edited_content_is_a_new_document(context, casefile, corpus):
    context.ingestion.ingest(casefile.short_id, corpus / "lease.md")
    (corpus / "lease.md").write_text("# Harbour Lease\n\nEntirely different text.\n", encoding="utf-8")
    context.ingestion.ingest(casefile.short_id, corpus / "lease.md")
    # Different bytes are a different document, even under the same filename.
    assert len(context.ingestion.list_documents(casefile.short_id)) == 2


def test_the_same_file_in_two_casefiles_is_two_documents(context, casefile, corpus):
    other = context.casefiles.create("Unrelated Matter")
    context.ingestion.ingest(casefile.short_id, corpus / "lease.md")
    context.ingestion.ingest(other.short_id, corpus / "lease.md")

    mine = context.ingestion.list_documents(casefile.short_id)
    theirs = context.ingestion.list_documents(other.short_id)
    assert len(mine) == len(theirs) == 1
    assert mine[0].id != theirs[0].id


def test_a_symlink_is_refused(context, casefile, corpus, tmp_path):
    link = corpus / "linked.md"
    link.symlink_to(corpus / "lease.md")
    report = context.ingestion.ingest(casefile.short_id, corpus)
    failures = [o for o in report.outcomes if o.status == "failed"]
    assert any("symbolic link" in o.detail for o in failures)


def test_an_empty_file_is_refused(context, casefile, corpus):
    (corpus / "empty.txt").write_text("", encoding="utf-8")
    report = context.ingestion.ingest(casefile.short_id, corpus)
    assert any(o.status == "failed" and "empty" in o.detail for o in report.outcomes)


def test_ingesting_a_missing_path_is_a_validation_error(context, casefile, tmp_path):
    with pytest.raises(ValidationError, match="does not exist"):
        context.ingestion.ingest(casefile.short_id, tmp_path / "nowhere")


def test_documents_resolve_by_short_id(context, casefile, corpus):
    context.ingestion.ingest(casefile.short_id, corpus)
    document = context.ingestion.list_documents(casefile.short_id)[0]
    assert context.ingestion.resolve_document(casefile.short_id, document.short_id).id == document.id


def test_an_unknown_document_reference_is_not_found(context, casefile, corpus):
    context.ingestion.ingest(casefile.short_id, corpus)
    with pytest.raises(NotFoundError):
        context.ingestion.resolve_document(casefile.short_id, "ffffffffff")


def test_a_document_from_another_casefile_is_not_visible(context, casefile, corpus):
    other = context.casefiles.create("Unrelated Matter")
    context.ingestion.ingest(casefile.short_id, corpus / "lease.md")
    mine = context.ingestion.list_documents(casefile.short_id)[0]
    with pytest.raises(NotFoundError):
        context.ingestion.resolve_document(other.short_id, mine.id)


def test_extracted_text_is_stored_with_the_document(context, casefile, corpus):
    context.ingestion.ingest(casefile.short_id, corpus / "lease.md")
    document = context.ingestion.list_documents(casefile.short_id)[0]
    assert "Northgate" in document.extracted_text
    assert document.extractor == "docling"
    assert document.byte_size > 0
