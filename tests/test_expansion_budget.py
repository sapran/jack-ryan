"""The bound on how far one ingest may expand, and what it reports.

A budget that stops an ingest silently is worse than no budget: what was
refused is what an analyst needs to know about.
"""

from __future__ import annotations

import zipfile

import pytest

from jackryan.ingestion.budget import ExpansionBudget


@pytest.fixture
def casefile(context):
    return context.casefiles.create("Budget Inquiry")


def _limit(context, budget: ExpansionBudget) -> None:
    """Narrow the wired service's budget for one test.

    Reaching the real defaults would need a 20 GB archive. The limits are
    injected the same way a deployment would set them, so what is exercised is
    the shipped path rather than a patched one.
    """
    context.ingestion._limits = (
        budget.max_depth,
        budget.max_descendants,
        budget.max_extracted_bytes,
    )


# -- the budget on its own -------------------------------------------------


def test_depth_beyond_the_bound_is_refused_and_named():
    budget = ExpansionBudget(max_depth=2)

    assert budget.allows_depth(2) is True
    assert budget.allows_depth(3) is False
    assert budget.spent
    assert "2 levels" in budget.exhausted_by


def test_the_descendant_count_is_a_bound():
    budget = ExpansionBudget(max_descendants=2)

    assert budget.take_child(10) is True
    assert budget.take_child(10) is True
    assert budget.take_child(10) is False
    assert "expanded documents" in budget.exhausted_by
    assert budget.descendants == 2, "a refused child is not charged"


def test_the_byte_ceiling_counts_what_extraction_produced():
    budget = ExpansionBudget(max_extracted_bytes=100)

    assert budget.take_child(60) is True
    assert budget.take_child(60) is False, "60 + 60 is over the ceiling"
    assert "extracted bytes" in budget.exhausted_by
    assert budget.extracted_bytes == 60


def test_the_first_bound_hit_is_the_one_reported():
    budget = ExpansionBudget(max_descendants=1, max_extracted_bytes=1)

    budget.take_child(1)
    budget.take_child(1)  # descendants runs out first
    budget.take_child(1)  # bytes would too, but the first reason stands

    assert "expanded documents" in budget.exhausted_by


# -- the budget in an ingest -----------------------------------------------


def _bomb(path, entries=64, size=4096):
    """A small archive that expands to much more than it occupies.

    Not a real zip bomb — a real one is gigabytes on expansion and this suite
    must stay fast. It is the same shape: highly compressible entries whose
    expanded size is what the budget must count.
    """
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for index in range(entries):
            archive.writestr(f"entry-{index:04d}.txt", "A" * size)
    return path


def test_a_high_expansion_archive_is_stopped_by_the_byte_budget(
    context, casefile, tmp_path
):
    # A ceiling a handful of entries will cross, so what stops the ingest is
    # the budget rather than the archive running out.
    _limit(context, ExpansionBudget(max_extracted_bytes=20_000))
    bomb = _bomb(tmp_path / "bomb.zip")

    report = context.ingestion.ingest(casefile.short_id, bomb)

    assert report.exhausted_by is not None
    assert "extracted bytes" in report.exhausted_by
    assert not report.complete
    # What was already stored stays stored — a bound is not a rollback.
    assert report.ingested >= 1
    stored = context.store.list_documents(casefile.id, include_expanded=True)
    assert 0 < len(stored) < 64


def test_a_stopped_ingest_says_which_bound_stopped_it(context, casefile, tmp_path):
    bundle = tmp_path / "wide.zip"
    with zipfile.ZipFile(bundle, "w") as archive:
        for index in range(8):
            archive.writestr(f"note-{index}.txt", f"body {index}")

    _limit(context, ExpansionBudget(max_descendants=3))
    report = context.ingestion.ingest(casefile.short_id, bundle)

    assert report.exhausted_by is not None
    assert "expanded documents" in report.exhausted_by
    assert any("expanded documents" in r for r in report.refusals)
    assert report.ingested == 4, "the container plus the three it could afford"


def test_nesting_deeper_than_the_bound_is_refused(context, casefile, tmp_path):
    # Three archives, each holding the next.
    innermost = tmp_path / "level3.zip"
    with zipfile.ZipFile(innermost, "w") as archive:
        archive.writestr("secret.txt", "the deepest document")
    middle = tmp_path / "level2.zip"
    with zipfile.ZipFile(middle, "w") as archive:
        archive.write(innermost, "level3.zip")
    outer = tmp_path / "level1.zip"
    with zipfile.ZipFile(outer, "w") as archive:
        archive.write(middle, "level2.zip")

    _limit(context, ExpansionBudget(max_depth=1))
    report = context.ingestion.ingest(casefile.short_id, outer)

    assert report.exhausted_by is not None
    assert "levels" in report.exhausted_by
    names = {
        d.filename
        for d in context.store.list_documents(casefile.id, include_expanded=True)
    }
    assert "secret.txt" not in names, "expansion stopped before the deepest level"


def test_the_expansion_workspace_is_removed_afterwards(context, casefile, tmp_path):
    import tempfile

    bundle = tmp_path / "bundle.zip"
    with zipfile.ZipFile(bundle, "w") as archive:
        archive.writestr("a.txt", "alpha")

    before = set(pathlib_iterdir(tempfile.gettempdir()))
    context.ingestion.ingest(casefile.short_id, bundle)
    after = set(pathlib_iterdir(tempfile.gettempdir()))

    leaked = {p for p in after - before if "jackryan-expand-" in p}
    assert not leaked, f"expansion workspace left behind: {leaked}"


def test_the_workspace_is_removed_even_when_the_ingest_raises(
    context, casefile, tmp_path, monkeypatch
):
    import tempfile

    bundle = tmp_path / "bundle.zip"
    with zipfile.ZipFile(bundle, "w") as archive:
        archive.writestr("a.txt", "alpha")

    def explode(*args, **kwargs):
        raise RuntimeError("something went wrong mid-ingest")

    monkeypatch.setattr(context.ingestion, "_ingest_work", explode)

    before = set(pathlib_iterdir(tempfile.gettempdir()))
    with pytest.raises(RuntimeError):
        context.ingestion.ingest(casefile.short_id, bundle)
    after = set(pathlib_iterdir(tempfile.gettempdir()))

    leaked = {p for p in after - before if "jackryan-expand-" in p}
    assert not leaked, f"workspace survived a failure: {leaked}"


def pathlib_iterdir(directory):
    import pathlib

    try:
        return [str(p) for p in pathlib.Path(directory).iterdir()]
    except OSError:  # pragma: no cover - unreadable temp dir
        return []
