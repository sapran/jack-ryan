"""Indexing one document's passages, so a document reached by browsing is citable.

Every fixture here is synthetic. No real case material enters the repository.

Four things in this file are deliberate and easy to undo by accident.

**The order oracle is the chunker, not the listing.** `expected_spans` runs
`chunk_text` over the document's own extracted text with the contract the
fixture configured, and the sweep asserts the pages reproduce those spans in
that order. The oracle is therefore produced by the code that *writes* passages,
never by the code this change added to read them — asking the listing for the
same rows a second time and comparing would compare the query with itself and
stay green for any ordering it applied consistently, including one that pages
inconsistently.

**The multi-passage document is deliberately long enough to page.** A document
of one passage cannot exercise a page boundary at all: the first page is the
whole selection, `truncated` is false whatever the query did, and every
assertion about continuation passes without reaching the code that decides it.
This is the same failure `docs/implementation-notes.md` records for the window
tests, whose single-passage fixtures proved nothing.

**The empty index is driven by a real container, not by a hand-written row.**
`router.extract` refuses to store a document with no usable text but exempts a
container, "because an archive's value is in its entries" — so an archive
holding no entries is genuinely stored with no text and no passages. Deleting
chunk rows to manufacture the state instead would test a state the pipeline
cannot produce.

**The journey test removes `case_search` from the server.** The whole claim is
that a citation is reachable without a ranked search, and a test that merely
does not call one proves nothing: an implementation that quietly needed it would
still pass. `remove_tool` makes the failure mode a missing tool rather than an
unnoticed dependency, which is the arrangement
`test_an_agent_cites_a_carrier_without_a_ranked_search` already uses for the
identifier path.
"""

from __future__ import annotations

import email.message
import json
import zipfile

import pytest
from fastapi.testclient import TestClient

from jackryan.errors import NotFoundError
from jackryan.ingestion.chunker import chunk_text
from jackryan.interfaces.mcp.server import build_mcp_server
from jackryan.interfaces.mcp.shapes import one_line
from jackryan.server import create_app
from jackryan.services.ingestion import MAX_DOCUMENT_OFFSET, MAX_PASSAGE_PAGE
from jackryan.storage.port import Chunk

# Long enough for several passages at the test contract's 400-character chunks,
# under two headings so `heading_path` is exercised rather than defaulted, and
# with one distinctive line so the citation can be checked against the source.
SECTIONED = "\n\n".join(
    [
        "# Harbour survey",
        "## Dredging",
        " ".join(f"Dredging line {n} of the survey record." for n in range(1, 26)),
        "## Tariffs",
        " ".join(f"Tariff line {n} of the schedule." for n in range(1, 26)),
        "A cormorant was recorded on the mooring buoy on the fourth of June.",
    ]
)
DISTINCTIVE = "A cormorant was recorded on the mooring buoy"

ATTACHED = "The dredging invoice is attached for the board's approval."
HOLLOW = "hollow.zip"
NESTED = "nested.zip"
BURIED = "buried.txt"


@pytest.fixture
def casefile(context):
    return context.casefiles.create("Passage Inquiry")


@pytest.fixture
def dump(tmp_path):
    """One archive holding a sectioned document, an empty archive and a nest.

    The empty archive is what makes a document with no passages reachable, and
    the nested archive is what makes the second level of the browse reachable —
    a fixture one level deep cannot tell "entered a container" from "entered the
    only container".
    """
    hollow = tmp_path / HOLLOW
    with zipfile.ZipFile(hollow, "w"):
        pass

    nested = tmp_path / NESTED
    with zipfile.ZipFile(nested, "w") as archive:
        archive.writestr(BURIED, "the buried tariff clause and nothing else")

    bundle = tmp_path / "bundle.zip"
    with zipfile.ZipFile(bundle, "w") as archive:
        archive.writestr("survey.md", SECTIONED)
        archive.writestr(HOLLOW, hollow.read_bytes())
        archive.writestr(NESTED, nested.read_bytes())
    return bundle


@pytest.fixture
def message(tmp_path):
    """A message carrying two attachments, which is the other container shape."""
    note = email.message.EmailMessage()
    note["From"] = "clerk@example.com"
    note["To"] = "board@example.com"
    note["Date"] = "Mon, 01 Mar 2021 09:00:00 +0000"
    note["Subject"] = "Dredging invoice"
    note.set_content("See the attachments.")
    note.add_attachment(
        ATTACHED.encode("utf-8"), maintype="text", subtype="plain", filename="invoice.txt"
    )
    note.add_attachment(
        b"The mooring schedule for the quarter.",
        maintype="text",
        subtype="plain",
        filename="schedule.txt",
    )
    path = tmp_path / "cover.eml"
    path.write_bytes(note.as_bytes())
    return path


@pytest.fixture
def ingested(context, casefile, dump, message):
    """Both containers in one casefile, with the documents the tests select.

    Returns the sectioned child, the empty archive and the container, all
    resolved once so no test has to find them, and asserts the fixture actually
    produced the shapes every assertion below rests on.
    """
    for path in (dump, message):
        report = context.ingestion.ingest(casefile.short_id, path)
        assert report.failed == 0, f"{path.name} must ingest cleanly or it proves nothing"

    everything = {
        document.filename: document
        for document in context.ingestion.list_documents(
            casefile.short_id, include_expanded=True
        )
    }
    survey = everything["survey.md"]
    hollow = everything[HOLLOW]
    bundle = everything["bundle.zip"]

    # Vacuity guards. Every assertion below is about a document with several
    # passages, a document with none, and two levels of nesting; a fixture that
    # quietly stopped producing any of them would leave this file green over an
    # empty selection.
    assert len(chunk_text(survey.extracted_text, max_chars=400, overlap_chars=50)) > 3, (
        "the sectioned document must hold several passages to page at all"
    )
    assert hollow.extracted_text == "", "the empty archive must be stored with no text"
    assert bundle.child_count == 3, "the container must hold three direct children"
    assert everything[NESTED].child_count == 1, "the nest must hold its own child"
    return survey, hollow, bundle


@pytest.fixture
def expected_passages(context, ingested):
    """Every field of the index the chunker decides, in the order it decided them.

    An oracle from the *writing* side of the pipeline: `chunk_text` is what
    produced the rows, and the listing under test only reads them, so this
    cannot be satisfied by a query that agrees with itself.

    It carries the span, the stored length and the heading path — not the span
    alone, which is what it carried first. Review established that with only
    spans asserted, aliasing `LENGTH(c.text)` to `0` or to `c.char_end`, or
    aliasing `heading_path` to any non-empty column, left every test in this
    file green: the two derived values were returned by the query and compared
    against nothing but themselves.
    """
    survey, _, _ = ingested
    pieces = chunk_text(
        survey.extracted_text,
        max_chars=context.config.contract.chunk_max_chars,
        overlap_chars=context.config.contract.chunk_overlap_chars,
    )
    return [
        (piece.char_start, piece.char_end, len(piece.text), piece.heading_path)
        for piece in pieces
    ]


# -- the service ----------------------------------------------------------


def test_the_pages_together_carry_every_passage_exactly_once(
    context, casefile, ingested, expected_passages
):
    """Paged to its end, the listing reproduces the chunker's own sequence.

    Every field the chunker decided is compared, not the spans alone: the
    stored length and the heading path are derived by the query and would
    otherwise be checked against nothing but themselves.

    Bounded for the reason the document sweep is: a `total_matching` counted
    under a wider predicate than the rows keeps `truncated` true forever, and a
    test that hangs reports nothing.
    """
    survey, _, _ = ingested
    seen: list[tuple[int, int, int, str]] = []
    ordinals: list[int] = []
    identifiers: list[str] = []
    offset, calls = 0, 0
    for _ in range(20):
        page = context.ingestion.list_document_passage_page(
            casefile.short_id, survey.short_id, offset, 2
        )
        calls += 1
        assert page.total_matching == len(expected_passages)
        assert page.document is not None and page.document.id == survey.id
        assert len(page.passages) <= 2
        seen.extend(
            (p.char_start, p.char_end, p.characters, p.heading_path)
            for p in page.passages
        )
        ordinals.extend(p.ordinal for p in page.passages)
        identifiers.extend(p.id for p in page.passages)
        if not page.truncated:
            assert page.continue_from is None
            break
        offset = page.continue_from
    else:
        raise AssertionError(f"the listing never ended after {calls} calls")

    assert calls > 1, "a fixture that fits in one page cannot exercise a boundary"
    assert seen == expected_passages
    assert ordinals == list(range(len(expected_passages)))
    # A premise of the heading comparison: an all-empty heading path would not
    # distinguish that column from any other empty one.
    assert any(heading for *_, heading in expected_passages), (
        "the fixture must hold a heading or `heading_path` proves nothing"
    )
    # **`characters` cannot be distinguished from the span here, and that is
    # measured rather than assumed.** Asserting that some passage's stored
    # length differs from `char_end - char_start` was tried and fails for every
    # passage: `a-chunk-begins-where-its-text-does` made
    # `source[char_start:char_end] == text` an invariant of the chunker, so the
    # two are equal for every row this pipeline writes. It is asserted in that
    # direction instead, which is the honest claim and still catches a length
    # aliased to a constant or to another column — and it is why the mutation
    # table records the `LENGTH(text)` → span mutation as GREEN by construction
    # rather than as an unguarded field. The field earns its place only on a
    # corpus written before that invariant, whose rows describe the untrimmed
    # window, and no such corpus is constructed here.
    assert all(
        characters == end - start for start, end, characters, _ in expected_passages
    ), "the chunker no longer records the trimmed span"
    # The id set from a different code path, so a query that lost or duplicated
    # a row is caught even where its spans happen to line up.
    assert sorted(identifiers) == sorted(
        chunk.id for chunk in context.store.list_document_chunks(survey.id)
    )
    assert len(set(identifiers)) == len(identifiers), "a passage was returned twice"


def test_the_count_is_of_this_document_and_not_the_casefile(
    context, casefile, ingested, expected_passages
):
    """`total_matching` counts this document's passages, not the casefile's.

    The casefile holds several other documents with passages of their own, so a
    count taken under a wider predicate than the page is visible here and
    nowhere else in this file: every other assertion still passes with the
    predicate widened, and `truncated` simply stays true past the end.
    """
    survey, _, _ = ingested
    page = context.ingestion.list_document_passage_page(casefile.short_id, survey.id)

    casefile_wide = sum(
        len(context.store.list_document_chunks(document.id))
        for document in context.ingestion.list_documents(
            casefile.short_id, include_expanded=True
        )
    )
    assert page.total_matching == len(expected_passages)
    assert casefile_wide > page.total_matching, (
        "the fixture must hold passages outside this document or the count proves nothing"
    )
    assert all(p.document_id == survey.id for p in page.passages)


def test_both_bounds_are_clamped_at_both_ends(context, casefile, ingested):
    """Clamped rather than refused, as every bound on this surface is.

    A `limit` of 0 is the quiet one: it returns no rows while the count reports
    the whole document, so `truncated` stays true and a caller following
    `continue_from` never advances.
    """
    survey, _, _ = ingested
    total = context.ingestion.list_document_passage_page(
        casefile.short_id, survey.id
    ).total_matching

    zero = context.ingestion.list_document_passage_page(casefile.short_id, survey.id, 0, 0)
    assert len(zero.passages) == 1, "a limit of 0 must be floored to one row"

    over = context.ingestion.list_document_passage_page(
        casefile.short_id, survey.id, 0, MAX_PASSAGE_PAGE * 10
    )
    assert over.limit == MAX_PASSAGE_PAGE
    assert len(over.passages) == total

    negative = context.ingestion.list_document_passage_page(
        casefile.short_id, survey.id, -5, 2
    )
    assert negative.offset == 0, "a negative offset reported as itself repeats rows"
    assert negative.continue_from == 2

    # Above SQLite's integer range. Unclamped this reaches the driver and raises
    # `OverflowError`, which is not a `JackRyanError`, so the tool would raise
    # instead of answering.
    huge = context.ingestion.list_document_passage_page(
        casefile.short_id, survey.id, MAX_DOCUMENT_OFFSET * 4, 2
    )
    assert huge.passages == []
    assert huge.total_matching == total, "a page past the end still sizes the document"
    assert huge.beyond_the_end is True


def test_a_document_in_another_casefile_is_refused(context, casefile, ingested):
    """A casefile is a compartment, and an index may not reach across one."""
    survey, _, _ = ingested
    other = context.casefiles.create("Unrelated Inquiry")

    with pytest.raises(NotFoundError) as excinfo:
        context.ingestion.list_document_passage_page(other.short_id, survey.id)

    # The message may echo the caller's own reference and nothing else: a
    # refusal naming a filename or a count would breach the compartment while
    # appearing to respect it.
    message = str(excinfo.value)
    assert survey.filename not in message
    assert DISTINCTIVE not in message
    assert "Dredging" not in message


def test_a_document_with_no_passages_reports_an_empty_index(context, casefile, ingested):
    """Nothing to cite is a real state, reported rather than approximated.

    Driven by a container the pipeline genuinely stored with no text. The page
    must not claim to be truncated, or a caller following `continue_from` would
    page an empty document forever.
    """
    _, hollow, _ = ingested
    page = context.ingestion.list_document_passage_page(casefile.short_id, hollow.id)

    assert page.passages == []
    assert page.total_matching == 0
    assert page.truncated is False
    assert page.continue_from is None
    # False, because the page did not begin past the end — the document has no
    # end to begin past. The two are different facts and the surface says so.
    assert page.beyond_the_end is False


def test_the_store_floors_its_own_bounds(context, ingested):
    """The store enforces the bounds rather than trusting its caller.

    Reached directly, which is the only way to see it: the service clamps
    before delegating, so through the service these floors are unreachable and
    a mutation removing them reports green. They are not redundant — the tests
    beside this one reach the store directly, and the reported `offset` must be
    the one SQLite applied because `continue_from` is computed from it. A page
    returning the first rows while reporting `offset=-5` hands back a
    `continue_from` that repeats them.

    A `limit` of 0 is the quiet half: it returns no rows while the count still
    reports the whole document, so `truncated` stays true and a caller
    following `continue_from` never advances.
    """
    survey, _, _ = ingested

    zero = context.store.list_document_passage_page(survey.id, 0, 0)
    assert len(zero.passages) == 1, "a limit of 0 must be floored to one row"
    assert zero.limit == 1

    negative = context.store.list_document_passage_page(survey.id, -5, 2)
    assert negative.offset == 0
    assert negative.continue_from == 2
    assert [p.ordinal for p in negative.passages] == [0, 1]


def test_two_passages_sharing_an_ordinal_still_page_in_a_total_order(
    context, casefile, ingested
):
    """The ordering ends in a tiebreak, and this is what can see it.

    `mcp-tool-surface` requires an ordering in which a page boundary cannot
    fall inside a tie, and the port declaration makes it a SHALL. `ordinal`
    alone does not satisfy it: `chunks` enforces no uniqueness on
    `(document_id, ordinal)` — the chunker happens to emit them sequentially,
    which is why review found that dropping `, char_start, id` from both
    orderings left the whole suite green.

    So the tie is built rather than waited for. `replace_chunks` stores whatever
    chunks it is given, so two passages share ordinal 0 here, and the document
    is paged one row at a time: without a tiebreak SQLite may return the same
    row for both pages or neither, and every page would still be individually
    well-formed, which is what makes the defect invisible without this test.

    A `text` of different lengths, so `characters` distinguishes the two rows
    even if their spans did not.
    """
    survey, _, _ = ingested
    tied = [
        Chunk(
            id="a" * 32,
            document_id=survey.id,
            casefile_id=survey.casefile_id,
            ordinal=0,
            heading_path="First",
            text="the earlier of two passages at one ordinal",
            char_start=0,
            char_end=42,
        ),
        Chunk(
            id="b" * 32,
            document_id=survey.id,
            casefile_id=survey.casefile_id,
            ordinal=0,
            heading_path="Second",
            text="the later one, longer than the first",
            char_start=100,
            char_end=136,
        ),
    ]
    context.store.replace_chunks(
        survey.id, tied, [[0.5] * context.config.contract.embed_dimensions] * 2, []
    )

    seen: list[str] = []
    for offset in (0, 1):
        page = context.store.list_document_passage_page(survey.id, offset, 1)
        assert page.total_matching == 2
        assert len(page.passages) == 1
        seen.append(page.passages[0].id)

    assert seen == ["a" * 32, "b" * 32], "the tie was not broken by the passage's place"
    assert len(set(seen)) == 2, "one page boundary inside a tie repeated a passage"


# -- the agent surface ----------------------------------------------------


async def _call(server, name, args=None):
    result = await server.call_tool(name, args or {})
    return json.loads(result.content[0].text)


def _unfenced(value: str, nonce: str) -> str:
    """The text inside a fence, with the fence's own shape asserted.

    Written out rather than `split("\\n")[1]`, which is what this test first
    did: a passage of a sectioned document spans several lines, so taking the
    first one silently compared a fragment against the whole span and failed
    for a reason that had nothing to do with the span.
    """
    prefix, suffix = f"<<<UNTRUSTED {nonce}\n", f"\n{nonce} UNTRUSTED>>>"
    assert value.startswith(prefix) and value.endswith(suffix), "the fence is malformed"
    return value[len(prefix) : -len(suffix)]


@pytest.mark.anyio
async def test_an_agent_cites_a_document_reached_by_listing_without_a_search(
    context, casefile, ingested
):
    """The journey this change exists for, with `case_search` off the server.

    Intake, into the container, into the container inside it, index a chosen
    child's passages, read one, cite it, and check the citation's span against
    the text the fixture wrote. Every identifier comes from the call before it.
    """
    survey, _, container = ingested
    server = build_mcp_server(context)
    server.remove_tool("case_search")
    assert "case_search" not in [tool.name for tool in await server.list_tools()], (
        "the tool must be gone, or this test proves nothing about needing it"
    )

    intake = await _call(server, "case_list_documents", {"casefile": casefile.short_id})
    bundle = next(
        row for row in intake["results"] if row["filename"] == "bundle.zip"
    )
    assert bundle["children"] == 3
    assert bundle["document_id"] == container.id

    contents = await _call(
        server,
        "case_list_documents",
        {"casefile": casefile.short_id, "parent": bundle["short_id"]},
    )
    assert contents["selection"] == "children"
    nest = next(row for row in contents["results"] if row["filename"] == NESTED)
    assert nest["children"] == 1, "the second level must be reachable"
    deeper = await _call(
        server,
        "case_list_documents",
        {"casefile": casefile.short_id, "parent": nest["short_id"]},
    )
    assert [row["filename"] for row in deeper["results"]] == [BURIED]

    child = next(row for row in contents["results"] if row["filename"] == "survey.md")

    # The step that did not exist: a document reached by listing, indexed.
    index = await _call(
        server,
        "case_list_passages",
        {"casefile": casefile.short_id, "document": child["document_id"]},
    )
    assert index["document"]["document_id"] == survey.id
    assert index["document"]["found_at"] == "bundle.zip/survey.md"
    assert index["total"] == index["total_matching"] > 1
    assert all(row["document_id"] == survey.id for row in index["results"])
    assert [row["ordinal"] for row in index["results"]] == list(range(index["total"]))
    assert any(row["heading_path"] for row in index["results"]), (
        "the fixture's headings must reach the index or it indexes less than it claims"
    )

    # The passage holding the line the fixture wrote, chosen by its span against
    # the document's own text — the search-free way to find a relevant passage.
    where = survey.extracted_text.index(DISTINCTIVE)
    chosen = next(
        row
        for row in index["results"]
        if row["char_start"] <= where < row["char_end"]
    )

    passage = await _call(
        server,
        "case_get_passage",
        {"casefile": casefile.short_id, "chunk_id": chosen["chunk_id"]},
    )
    assert DISTINCTIVE in passage["text"]
    assert passage["document_id"] == survey.id

    citation = await _call(
        server, "case_cite", {"casefile": casefile.short_id, "chunk_id": chosen["chunk_id"]}
    )
    assert citation["document_id"] == survey.id
    # The citation names the path an analyst would follow by hand: the child's
    # own filename identifies nothing without the archive that carried it.
    assert citation["found_at"] == "bundle.zip/survey.md"
    # The span is checked against the text the fixture wrote, not against
    # anything the store reported: a citation whose span cannot be followed back
    # to the source by hand is not a chain of evidence.
    quoted = _unfenced(citation["quote"], citation["fence_nonce"])
    assert survey.extracted_text[citation["char_start"] : citation["char_end"]] == quoted
    assert DISTINCTIVE in quoted


@pytest.mark.anyio
async def test_an_attachment_is_cited_the_same_way(context, casefile, ingested):
    """The other container shape: a message's attachment, indexed and cited.

    An attachment is the case the capability was argued from — short text, a
    generic name — so it is asserted rather than assumed to follow from the
    archive.
    """
    server = build_mcp_server(context)
    server.remove_tool("case_search")

    intake = await _call(server, "case_list_documents", {"casefile": casefile.short_id})
    cover = next(row for row in intake["results"] if row["filename"] == "cover.eml")
    attachments = await _call(
        server,
        "case_list_documents",
        {"casefile": casefile.short_id, "parent": cover["short_id"]},
    )
    invoice = next(
        row for row in attachments["results"] if row["filename"] == "invoice.txt"
    )

    index = await _call(
        server,
        "case_list_passages",
        {"casefile": casefile.short_id, "document": invoice["document_id"]},
    )
    assert index["total_matching"] >= 1
    citation = await _call(
        server,
        "case_cite",
        {"casefile": casefile.short_id, "chunk_id": index["results"][0]["chunk_id"]},
    )
    assert ATTACHED in citation["quote"]
    assert citation["found_at"] == "cover.eml/invoice.txt"


@pytest.mark.anyio
async def test_an_empty_index_explains_itself_rather_than_denying_the_document(
    context, casefile, ingested
):
    """Two empty pages, two different true statements.

    Both are asserted, because the failure they guard is silent: a page past the
    end reported as "this document has nothing to cite" is a false claim of
    absence, which is the class of answer this whole capability exists to
    remove.
    """
    survey, hollow, _ = ingested
    server = build_mcp_server(context)

    nothing = await _call(
        server, "case_list_passages", {"casefile": casefile.short_id, "document": hollow.id}
    )
    assert nothing["results"] == []
    assert "no stored passages" in nothing["formatted"]
    assert "case_list_documents" in nothing["formatted"], (
        "the message must name what to do instead of citing"
    )

    past = await _call(
        server,
        "case_list_passages",
        {"casefile": casefile.short_id, "document": survey.id, "offset": 900},
    )
    assert past["results"] == []
    assert past["total_matching"] > 0
    assert "No passages at offset 900" in past["formatted"]
    assert "no stored passages" not in past["formatted"], (
        "a page past the end must not read as a document with nothing in it"
    )


@pytest.mark.anyio
async def test_the_index_carries_no_passage_text(
    context, casefile, ingested, expected_passages
):
    """A payload unfenced because it carries no prose must carry none.

    `listing_payload` is unfenced on exactly that promise, and
    `untrusted-content-boundary` says such a payload is not the one to carry
    corpus text.

    **Two hand-picked sentences were not enough, and the first version of this
    test said they were.** Review established that a clipped opening of each
    passage — the exact defect `CLAUDE.md` and the change's `design.md` call
    "the obvious way to make a passage index selectable" — passes a
    whole-sentence probe as long as the clip is shorter than the sentence, so a
    thirty-character `preview` under any key went uncaught. Two assertions
    close it: the row's key set is pinned exactly, and each passage's own
    opening characters are probed, taken from the chunker's oracle rather than
    chosen by hand.
    """
    survey, _, _ = ingested
    server = build_mcp_server(context)

    index = await _call(
        server,
        "case_list_passages",
        {"casefile": casefile.short_id, "document": survey.id, "limit": MAX_PASSAGE_PAGE},
    )
    rendered = json.dumps(index, ensure_ascii=False)
    for row in index["results"]:
        assert set(row) == {
            "chunk_id",
            "short_id",
            "document_id",
            "ordinal",
            "heading_path",
            "char_start",
            "char_end",
            "characters",
        }, f"the row gained a field: {sorted(row)}"
    # The opening of every passage, at a length a clipped preview would exceed.
    # A heading path is corpus-derived metadata and legitimately appears, so the
    # probe skips the passages whose text begins with their own heading.
    for start, end, _, heading in expected_passages:
        opening = survey.extracted_text[start : start + 24]
        if opening in heading:
            continue
        assert opening in survey.extracted_text, "the probe must be text of the document"
        assert opening not in rendered, f"the index returned passage text: {opening!r}"
    for sentence in ("Dredging line 3 of the survey record.", DISTINCTIVE):
        assert sentence in survey.extracted_text, "the probe must be text of the document"
        assert sentence not in rendered, "the index returned the passage's words"
    assert "UNTRUSTED" not in rendered, "an index carrying no prose needs no fence"
    # The notice still travels, because a heading and a filename are corpus
    # values even where no prose is.
    assert index["content_notice"]


@pytest.mark.anyio
async def test_rest_and_the_agent_surface_agree_on_a_middle_page(
    context, casefile, ingested
):
    """One service method, so two surfaces must not describe one page differently.

    A middle page rather than the first: the first page hides an offset the two
    could disagree about.
    """
    survey, _, _ = ingested
    server = build_mcp_server(context)
    tool_page = await _call(
        server,
        "case_list_passages",
        {"casefile": casefile.short_id, "document": survey.short_id, "offset": 2, "limit": 2},
    )

    app = create_app(context)
    with TestClient(app) as client:
        response = client.get(
            f"/api/casefiles/{casefile.short_id}/documents/{survey.short_id}/passages",
            params={"offset": 2, "limit": 2},
        )
    assert response.status_code == 200
    rest_page = response.json()

    for field in ("total", "offset", "total_matching", "truncated", "continue_from"):
        assert rest_page[field] == tool_page[field], f"the surfaces disagree on {field}"
    assert rest_page["document_id"] == tool_page["document"]["document_id"]
    assert [row["chunk_id"] for row in rest_page["passages"]] == [
        row["chunk_id"] for row in tool_page["results"]
    ]
    for rest_row, tool_row in zip(rest_page["passages"], tool_page["results"]):
        for field in ("document_id", "ordinal", "char_start", "char_end", "characters"):
            assert rest_row[field] == tool_row[field], f"the surfaces disagree on {field}"
        assert rest_row["short_id"] == tool_row["short_id"]
        # Stated as a relationship rather than as equality, because it is one:
        # REST returns corpus values raw, as it does for a filename, and the
        # agent surface collapses them. A heading path may be up to
        # `MAX_HEADING_PATH_CHARS` (512) long, so asserting equality would be
        # true of this fixture and false in general — and comparing nothing,
        # which is what this test did first, lets the two surfaces silently
        # read different columns.
        assert tool_row["heading_path"] == one_line(rest_row["heading_path"], 200)


@pytest.mark.anyio
async def test_a_document_in_another_casefile_is_refused_by_both_surfaces(
    context, casefile, ingested
):
    """One rule, so both adapters must report the same refusal.

    The agent surface returns a typed payload rather than raising, and REST
    answers 404; neither may describe what it declined to return.
    """
    survey, _, _ = ingested
    other = context.casefiles.create("Unrelated Inquiry")
    server = build_mcp_server(context)

    refused = await _call(
        server, "case_list_passages", {"casefile": other.short_id, "document": survey.id}
    )
    assert refused["error"] == "not_found"
    assert survey.filename not in refused["message"]
    assert "results" not in refused

    app = create_app(context)
    with TestClient(app) as client:
        response = client.get(
            f"/api/casefiles/{other.short_id}/documents/{survey.id}/passages"
        )
    assert response.status_code == 404
    assert survey.filename not in response.text
