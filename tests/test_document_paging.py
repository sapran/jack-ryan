"""Paging a document listing, and reaching a container's contents through it.

Every fixture here is synthetic. No real case material enters the repository.

Two things in this file are deliberate and easy to undo by accident.

**The order oracle is built by the test, never read back from the code under
test.** `expected_order` is `sorted()` over the entry names the fixture itself
wrote. Asking the store for the same children a second time and comparing would
compare the pipeline with itself, and would stay green for any ordering the
store applied consistently — including one that pages inconsistently. The names
are ASCII on purpose: SQLite orders text byte-wise and Python orders by code
point, and the two agree only while nothing outside ASCII is in play.

**The fixture holds a container inside a container.** That is what the removed
`list_children` could not report — it selected `*` and aliased no
`child_count`, so `_row_to_document` defaulted every child to zero children and
a nested archive was indistinguishable from a leaf. A fixture one level deep
would pass against the old defect.

**What mutation actually established**, since two of these assertions were
written believing they covered more than they did:

- Dropping the *subquery's* `ORDER BY` — the one that decides which rows land
  on a page — reddens three tests. That is the guard that matters.
- Widening the count's predicate to the whole casefile reddens nine. It first
  *hung* rather than failing, which is why both sweep loops are bounded.
- Dropping the *outer* `ORDER BY` leaves all twelve green. Not a gap in these
  tests: `EXPLAIN QUERY PLAN` shows SQLite driving the join from the ordered
  subquery and probing by primary key, so the order is currently inherited, and
  a sweep at 6, 20, 60, 200 and 600 children paged correctly without it. The
  line stays as insurance against a plan SQLite may change; `sqlite.py` records
  why at the line itself.
- Removing the trailing `d.id` tie-breaker also leaves them green, because
  ingestion cannot produce a tie to break — microsecond `created_at`, unique
  sibling paths. Same reasoning, recorded at `_document_selection`.
"""

from __future__ import annotations

import json
import zipfile

import pytest
from fastapi.testclient import TestClient

from jackryan.errors import NotFoundError
from jackryan.interfaces.mcp.server import build_mcp_server
from jackryan.server import create_app
from jackryan.services.ingestion import MAX_DOCUMENT_PAGE

# Five plain entries and one nested archive: six direct children. Odd and even
# page shapes are both exercised below — six over a limit of two is three full
# pages, six over a limit of four ends in a partial page — because a final page
# equal to the limit and one short of it are different boundaries.
#
# **The creation order is deliberately not the sorted order, and the nested
# archive is deliberately not last.** Documents are stored in the order the
# archive yields them, so rowids ascend in this order. A fixture written
# alphabetically makes insertion order and containment-path order coincide, and
# then the ordering under test cannot be distinguished from no ordering at all:
# measured, dropping the query's outer `ORDER BY` left every test in this file
# green. Scrambled, the two orders differ and the assertion bites.
CREATION_ORDER = (
    "echo.txt",
    "charlie.txt",
    "nested.zip",
    "alpha.txt",
    "delta.txt",
    "bravo.txt",
)
NESTED = "nested.zip"
ENTRIES = tuple(name for name in CREATION_ORDER if name != NESTED)
BURIED = "buried.txt"


@pytest.fixture
def casefile(context):
    return context.casefiles.create("Paging Inquiry")


@pytest.fixture
def container(context, casefile, tmp_path):
    """One archive holding five documents and a further archive.

    Returns the stored container document, so a test does not have to find it.
    """
    inner = tmp_path / NESTED
    with zipfile.ZipFile(inner, "w") as archive:
        archive.writestr(BURIED, "the buried tariff clause")

    outer = tmp_path / "bundle.zip"
    with zipfile.ZipFile(outer, "w") as archive:
        for index, name in enumerate(CREATION_ORDER):
            if name == NESTED:
                archive.writestr(NESTED, inner.read_bytes())
            else:
                archive.writestr(name, f"entry {index} of the harbour bundle")

    report = context.ingestion.ingest(casefile.short_id, outer)
    assert report.failed == 0, "the fixture must ingest cleanly or it proves nothing"

    top = context.ingestion.list_documents(casefile.short_id)
    assert [d.filename for d in top] == ["bundle.zip"]
    # Vacuity guard. Every assertion below is about six children and a nested
    # container; a fixture that quietly stopped producing either would leave
    # this file passing over an empty or flat selection.
    assert top[0].child_count == 6, "the fixture must hold six direct children"
    return top[0]


@pytest.fixture
def expected_order():
    """The order the test asserts, derived from the fixture's own names.

    A container's contents are ordered by containment path, which is the
    parent's path joined to the entry name — so with one parent the order is
    the sorted entry names. Built here rather than fetched, so the assertion
    has an oracle the store cannot move.
    """
    order = sorted(CREATION_ORDER)
    # The premise the ordering assertions rest on. If these ever coincide the
    # tests below still pass while proving nothing about ordering, which is the
    # state this file was first written in.
    assert order != list(CREATION_ORDER), (
        "the fixture must be created out of order, or no ordering is under test"
    )
    return order


def _names(page):
    return [d.filename for d in page.documents]


# -- the page reports what it is a page of ---------------------------------


def test_a_full_sweep_omits_and_repeats_nothing(context, casefile, container, expected_order):
    """Six children over three pages of two, each exactly once.

    The loop is bounded rather than `while True`. A `total_matching` counted
    under a wider predicate than the page keeps `truncated` true past the last
    document, so an unbounded follow of `continue_from` never terminates:
    measured, that mutation hung for fifteen minutes instead of failing. A
    guard that hangs is not a red test, so the bound is part of the assertion.
    """
    seen: list[str] = []
    pages = []
    offset = 0

    for _ in range(10):
        page = context.ingestion.list_document_page(
            casefile.short_id, container.short_id, offset=offset, limit=2
        )
        pages.append(page)
        seen.extend(_names(page))
        if page.continue_from is None:
            break
        offset = page.continue_from
    else:
        raise AssertionError(
            f"the listing never ended: {len(pages)} pages for "
            f"total_matching={pages[-1].total_matching}"
        )

    assert [len(p.documents) for p in pages] == [2, 2, 2]
    assert [p.offset for p in pages] == [0, 2, 4]
    assert [p.continue_from for p in pages] == [2, 4, None]
    assert [p.truncated for p in pages] == [True, True, False]
    assert all(p.total_matching == 6 for p in pages)
    assert all(p.selection == "children" for p in pages)
    # The whole point: every child once, in the order the fixture implies.
    assert seen == expected_order
    assert len(set(seen)) == 6


def test_a_final_page_shorter_than_the_limit_ends_the_listing(
    context, casefile, container, expected_order
):
    """Four then two. A short final page must not read as more to come."""
    first = context.ingestion.list_document_page(
        casefile.short_id, container.short_id, offset=0, limit=4
    )
    second = context.ingestion.list_document_page(
        casefile.short_id, container.short_id, offset=first.continue_from, limit=4
    )

    assert len(first.documents) == 4 and first.truncated and first.continue_from == 4
    assert len(second.documents) == 2
    assert second.truncated is False
    assert second.continue_from is None
    assert _names(first) + _names(second) == expected_order


def test_a_page_past_the_end_is_empty_without_denying_the_contents(
    context, casefile, container
):
    """An empty page and an empty container are different facts.

    `total_matching` is what separates them, which is why it is reported on a
    page carrying nothing.
    """
    page = context.ingestion.list_document_page(
        casefile.short_id, container.short_id, offset=99, limit=2
    )

    assert page.documents == []
    assert page.total_matching == 6
    assert page.truncated is False
    assert page.continue_from is None
    assert page.selection == "children"


def test_an_over_large_limit_is_clamped_rather_than_refused(context, casefile, container):
    page = context.ingestion.list_document_page(
        casefile.short_id, container.short_id, limit=10_000
    )

    assert page.limit == MAX_DOCUMENT_PAGE
    assert len(page.documents) <= MAX_DOCUMENT_PAGE
    assert len(page.documents) == 6


def test_each_selection_names_itself(context, casefile, container):
    """Three selections, three names, so an empty page is legible."""
    intake = context.ingestion.list_document_page(casefile.short_id)
    everything = context.ingestion.list_document_page(
        casefile.short_id, include_expanded=True
    )
    contents = context.ingestion.list_document_page(
        casefile.short_id, container.short_id
    )

    assert intake.selection == "ingested"
    assert intake.total_matching == 1
    assert everything.selection == "all"
    # The container, its six children, and the one document inside the nested
    # archive.
    assert everything.total_matching == 8
    assert contents.selection == "children"
    assert contents.total_matching == 6


# -- nesting ---------------------------------------------------------------


def test_a_nested_container_is_marked_and_can_be_entered(context, casefile, container):
    """The assertion the removed `list_children` could not pass.

    It aliased no `child_count`, so this nested archive came back reporting
    zero children and the level below it was unreachable — the caller was told
    a container was a leaf.
    """
    contents = context.ingestion.list_document_page(
        casefile.short_id, container.short_id
    )
    nested = next(d for d in contents.documents if d.filename == NESTED)

    assert nested.child_count == 1, "a nested container must be marked as one"

    inside = context.ingestion.list_document_page(
        casefile.short_id, nested.short_id
    )

    assert _names(inside) == [BURIED]
    assert inside.total_matching == 1
    assert inside.parent is not None and inside.parent.id == nested.id


def test_a_document_that_expanded_to_nothing_says_so(context, casefile, tmp_path):
    """An empty contents listing is not an empty casefile.

    Selecting the children of a plain document is a legitimate question with
    the answer "none"; the selection name is what stops that reading as "this
    casefile is empty".
    """
    plain = tmp_path / "memo.md"
    plain.write_text("# Memo\n\nThe tariff was deferred.")
    context.ingestion.ingest(casefile.short_id, plain)
    document = context.ingestion.list_documents(casefile.short_id)[0]

    page = context.ingestion.list_document_page(casefile.short_id, document.short_id)

    assert page.documents == []
    assert page.total_matching == 0
    assert page.selection == "children"
    assert page.truncated is False


# -- the compartment holds -------------------------------------------------


def test_a_container_in_another_casefile_is_refused(context, casefile, container):
    """A casefile is a compartment, and a listing may not reach across one."""
    other = context.casefiles.create("Unrelated Inquiry")

    with pytest.raises(NotFoundError):
        context.ingestion.list_document_page(other.short_id, container.id)

    # And nothing about its contents leaked by another route: the other
    # casefile still reports itself as empty.
    assert context.ingestion.list_document_page(other.short_id).total_matching == 0


# -- the agent journey the capability exists for ---------------------------


async def _call(server, name, args=None):
    result = await server.call_tool(name, args or {})
    return json.loads(result.content[0].text)


@pytest.mark.anyio
async def test_an_agent_reaches_a_child_and_cites_it_without_searching(
    context, casefile, container, expected_order
):
    """Intake, enter the container by prefix, page it, read a child, cite it.

    No search runs. That is the point: an attachment's text is short and its
    name is generic, so a container is exactly where retrieval is least likely
    to surface the evidence, and this is the route that does not depend on it.
    """
    server = build_mcp_server(context)

    listing = await _call(server, "case_list_documents", {"casefile": casefile.short_id})

    assert listing["selection"] == "ingested"
    assert listing["total"] == 1
    row = listing["results"][0]
    assert row["children"] == 6
    assert "(+6 inside)" in listing["formatted"]

    # Entered by the 8-character short id, which every identifier on this
    # surface must accept.
    seen: list[str] = []
    offset, calls = 0, 0
    # Bounded for the same reason as the service-level sweep: a wrong
    # `total_matching` keeps `truncated` true forever, and a test that hangs
    # reports nothing.
    for _ in range(10):
        page = await _call(
            server,
            "case_list_documents",
            {"casefile": casefile.short_id, "parent": row["short_id"], "limit": 2, "offset": offset},
        )
        calls += 1
        assert page["selection"] == "children"
        assert page["total_matching"] == 6
        assert page["parent"]["document_id"] == container.id
        assert page["parent"]["short_id"] == container.short_id
        seen.extend(entry["filename"] for entry in page["results"])
        if not page["truncated"]:
            assert page["continue_from"] is None
            break
        offset = page["continue_from"]
    else:
        raise AssertionError(f"the listing never ended after {calls} calls")

    assert calls == 3
    assert seen == expected_order

    # A child reached without any search having run, read and cited.
    contents = await _call(
        server,
        "case_list_documents",
        {"casefile": casefile.short_id, "parent": row["short_id"]},
    )
    child = next(
        entry for entry in contents["results"] if entry["filename"] == "alpha.txt"
    )

    read = await _call(
        server,
        "case_read_document",
        {"casefile": casefile.short_id, "document": child["document_id"]},
    )
    assert "harbour bundle" in read["text"]

    passage = await _call(
        server,
        "case_search",
        {"casefile": casefile.short_id, "query": "harbour bundle", "limit": 10},
    )
    chunk_id = next(
        hit["chunk_id"]
        for hit in passage["results"]
        if hit["document_id"] == child["document_id"]
    )
    citation = await _call(
        server, "case_cite", {"casefile": casefile.short_id, "chunk_id": chunk_id}
    )

    # The citation names the path an analyst would follow by hand: the child's
    # own filename identifies nothing without the archive that carried it.
    reference = json.dumps(citation)
    assert "bundle.zip/alpha.txt" in reference


@pytest.mark.anyio
async def test_an_empty_page_explains_itself_rather_than_denying_the_corpus(
    context, casefile, container
):
    """Three empty pages, three different true statements."""
    server = build_mcp_server(context)

    past_end = await _call(
        server,
        "case_list_documents",
        {"casefile": casefile.short_id, "parent": container.short_id, "offset": 99},
    )
    assert "offset 99" in past_end["formatted"]
    assert "6 in this selection" in past_end["formatted"]

    empty_casefile = context.casefiles.create("Nothing Ingested")
    blank = await _call(
        server, "case_list_documents", {"casefile": empty_casefile.short_id}
    )
    assert blank["formatted"] == "No documents in this casefile."


# -- the two surfaces agree ------------------------------------------------


def test_rest_and_the_agent_surface_agree_on_the_same_page(context, casefile, container):
    """Surface against surface, field by field.

    Not each against the service call they share: a field renamed or dropped in
    one adapter would still match the service, which is the failure this
    catches.
    """
    import anyio

    with TestClient(create_app(context)) as client:
        response = client.get(
            f"/api/casefiles/{casefile.short_id}/documents",
            params={"parent": container.short_id, "limit": 2, "offset": 2},
        )
    assert response.status_code == 200
    rest = response.json()

    server = build_mcp_server(context)
    agent = anyio.run(
        _call,
        server,
        "case_list_documents",
        {"casefile": casefile.short_id, "parent": container.short_id, "limit": 2, "offset": 2},
    )

    for field in ("offset", "total_matching", "truncated", "continue_from", "selection"):
        assert rest[field] == agent[field], f"{field} disagrees between the surfaces"
    assert rest["total"] == agent["total"]
    # `id` against `document_id`: the two surfaces name a document's identifier
    # differently on purpose, which `rendering.py` records. The values must be
    # the same documents in the same order — that is what agreement means here.
    assert [d["id"] for d in rest["documents"]] == [
        r["document_id"] for r in agent["results"]
    ]
    assert rest["parent_id"] == agent["parent"]["document_id"]


def test_the_default_rest_call_still_lists_intake_only(context, casefile, container):
    """An existing caller's request stays valid and gains the page fields."""
    with TestClient(create_app(context)) as client:
        body = client.get(f"/api/casefiles/{casefile.short_id}/documents").json()

    assert body["total"] == 1
    assert [d["filename"] for d in body["documents"]] == ["bundle.zip"]
    assert body["selection"] == "ingested"
    assert body["total_matching"] == 1
    assert body["truncated"] is False
    assert body["continue_from"] is None
    assert body["parent_id"] is None
