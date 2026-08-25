"""Regressions for defects found by adversarial review of M1.

Each test here failed against the code as first written. They are kept together
so the specific failures that got through are visible as a set.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from jackryan.errors import ConflictError, ValidationError
from jackryan.ingestion.chunker import MAX_HEADING_PATH_CHARS, chunk_text
from jackryan.storage.port import Casefile


# -- critical: deleting a casefile used to brick all future ingestion --------


def test_deleting_a_casefile_leaves_no_orphan_vectors_or_postings(context, corpus):
    """The bug: virtual tables never see ON DELETE CASCADE, so vectors and
    full-text postings survived their chunks. SQLite reuses the freed rowids,
    so the next ingest anywhere collided and the instance could never ingest
    again."""
    doomed = context.casefiles.create("Doomed Case")
    context.ingestion.ingest(doomed.short_id, corpus)
    context.casefiles.delete(doomed.short_id)

    raw = context.store._db
    assert raw.execute("SELECT count(*) FROM chunk_vectors").fetchone()[0] == 0
    assert raw.execute("SELECT count(*) FROM chunks_fts").fetchone()[0] == 0

    # The real symptom: ingesting again must still work.
    survivor = context.casefiles.create("Later Case")
    report = context.ingestion.ingest(survivor.short_id, corpus)
    assert report.ingested == 3 and report.failed == 0
    assert context.search.search(survivor.short_id, "harbour lease")


def test_deleting_a_document_leaves_no_orphans(context, corpus):
    casefile = context.casefiles.create("Case")
    context.ingestion.ingest(casefile.short_id, corpus)
    document = context.ingestion.list_documents(casefile.short_id)[0]

    raw = context.store._db
    raw.execute("DELETE FROM documents WHERE id = ?", (document.id,))
    raw.commit()
    orphans = raw.execute(
        "SELECT count(*) FROM chunk_vectors WHERE rowid NOT IN (SELECT rowid FROM chunks)"
    ).fetchone()[0]
    assert orphans == 0


# -- high: semantic recall must not depend on other casefiles ---------------


def test_vector_recall_survives_a_much_larger_neighbouring_casefile(context, corpus, tmp_path):
    """The bug: a global KNN was truncated before the casefile filter, so a
    small casefile's vector hits vanished once another casefile dominated."""
    noisy = context.casefiles.create("Noisy Neighbour")
    bulk = tmp_path / "bulk"
    bulk.mkdir()
    for i in range(40):
        (bulk / f"doc{i}.txt").write_text(
            f"harbour lease northgate holdings port authority document {i}\n", encoding="utf-8"
        )
    context.ingestion.ingest(noisy.short_id, bulk)

    small = context.casefiles.create("Small Case")
    context.ingestion.ingest(small.short_id, corpus)

    hits = context.search.search(small.short_id, "harbour lease Northgate", limit=5)
    assert hits, "the small casefile returned nothing at all"
    assert any(h.vector_rank is not None for h in hits), "vector retriever contributed nothing"
    assert all(h.chunk.casefile_id == small.id for h in hits)


# -- high: a named file that cannot be handled must say so ------------------


def test_a_directly_named_unsupported_file_fails_loudly(context, tmp_path):
    """The bug: it was skipped like a stray file in a folder walk, so the
    caller was told 0 ingested, 0 failed and exit 0."""
    casefile = context.casefiles.create("Case")
    odd = tmp_path / "report.xyz"
    odd.write_text("content that nothing can read", encoding="utf-8")

    report = context.ingestion.ingest(casefile.short_id, odd)
    assert report.failed == 1
    assert report.ingested == 0
    detail = report.outcomes[0].detail
    assert "report.xyz" in detail and ".xyz" in detail


def test_an_unsupported_file_inside_a_folder_is_still_skipped_quietly(context, corpus):
    (corpus / "stray.xyz").write_text("not asked for", encoding="utf-8")
    report = context.ingestion.ingest(context.casefiles.create("Case").short_id, corpus)
    assert report.failed == 0
    assert all("stray.xyz" not in o.path for o in report.outcomes)


def test_an_empty_ingest_path_is_refused(context):
    """The bug: "" became Path("."), ingesting the working directory."""
    casefile = context.casefiles.create("Case")
    with pytest.raises(ValidationError, match="path is required"):
        context.ingestion.ingest(casefile.short_id, "")


# -- high: a conflict must not leave the database locked --------------------


def test_a_slug_conflict_leaves_no_open_transaction(context):
    """The bug: the failed INSERT kept the WAL write lock, locking out every
    other process while the instance still looked healthy."""
    context.casefiles.create("First", slug="shared")
    with pytest.raises(ConflictError):
        context.casefiles.create("Second", slug="shared")
    assert context.store._db.in_transaction is False

    # And the store is still writable.
    assert context.casefiles.create("Third", slug="third")


# -- high/medium: the chunker's heading machinery ---------------------------


def test_heading_resolution_is_linear_not_quadratic():
    """The bug: every chunk re-scanned the whole document prefix."""
    import time

    def elapsed(multiplier: int) -> float:
        body = ("# Section\n\n" + "word " * 200 + "\n\n") * multiplier
        start = time.perf_counter()
        chunk_text(body, max_chars=2000, overlap_chars=200)
        return time.perf_counter() - start

    small = elapsed(500)
    large = elapsed(2000)
    # Four times the input must not cost anywhere near sixteen times the work.
    assert large < small * 8, f"scaling looks quadratic: {small:.3f}s -> {large:.3f}s"


def test_heading_text_cannot_dominate_a_chunk():
    """The bug: an unbounded heading was copied into every chunk beneath it."""
    huge = "# " + ("T" * 100_000) + "\n\n" + ("body text here. " * 5_000)
    chunks = chunk_text(huge, max_chars=2000, overlap_chars=200)
    assert chunks
    assert all(len(c.heading_path) <= MAX_HEADING_PATH_CHARS for c in chunks)


def test_a_chunk_is_labelled_with_the_section_it_is_inside():
    """The bug: a chunk could be labelled by a heading that merely preceded it,
    or by a fragment of one split across the boundary."""
    doc = "# Alpha\n\n" + "a" * 300 + "\n\n# Beta\n\n" + "b" * 300 + "\n"
    chunks = chunk_text(doc, max_chars=200, overlap_chars=20)
    for chunk in chunks:
        body = chunk.text.strip()
        if body.startswith("b") and chunk.heading_path:
            assert chunk.heading_path == "Beta"
        if body.startswith("a") and chunk.heading_path:
            assert chunk.heading_path == "Alpha"
    # No fragment of a heading ever becomes a label.
    assert all(p in ("", "Alpha", "Beta") for p in (c.heading_path for c in chunks))


def test_every_chunk_advances_by_a_meaningful_amount():
    """The bug: an overlap close to the window crawled a character at a time,
    turning one document into millions of near-identical chunks."""
    chunks = chunk_text("x" * 5000, max_chars=100, overlap_chars=99)
    steps = [b.char_start - a.char_start for a, b in zip(chunks, chunks[1:])]
    assert steps and min(steps) >= 25
    assert len(chunks) < 200


# -- low: adapters ----------------------------------------------------------


def test_document_list_on_an_empty_casefile_talks_about_documents(context, capsys):
    from jackryan import cli

    casefile = context.casefiles.create("Empty Case")
    import jackryan.cli as cli_module

    original = cli_module.build_context
    cli_module.build_context = lambda: context
    close = context.close
    context.close = lambda: None
    try:
        cli.main(["document", "list", casefile.short_id])
    finally:
        cli_module.build_context = original
        context.close = close
    out = capsys.readouterr().out
    assert "No documents yet" in out
    assert "casefile create" not in out
