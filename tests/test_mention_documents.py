"""Enumerating every document that carries one identifier, exhaustively.

Every fixture here is synthetic. No real case material enters the repository.

Three things in this file are deliberate and easy to undo by accident, and they
are the same three `tests/test_document_paging.py` records for the listing it
guards.

**The order oracle is built by the test, never read back from the code under
test.** `expected_order` is assembled from the names the fixture itself wrote.
Asking the store a second time and comparing would compare the pipeline with
itself, and would stay green for any ordering applied consistently — including
one that pages inconsistently.

**The sweep loops are bounded rather than `while True`.** A `total_matching`
counted under a wider predicate than the page keeps `truncated` true past the
last entry, so an unbounded follow of `continue_from` never terminates. A guard
that hangs is not a red test, so the bound is part of the assertion.

**The carrier files are ingested one at a time, out of alphabetical order.**
They all hold one occurrence, so they are separated only by containment path,
and an ordering keyed on that path is only distinguishable from one keyed on the
creation time or the rowid if the two orders differ. Writing the files out of
order is not enough: a folder walk ingests `sorted(path.rglob("*"))`, so handing
over the folder re-sorts them and makes all three orders the same. That was
established by running it — with one folder ingest, swapping
`containment_path` for `created_at` in both `ORDER BY` clauses left every test
here green. The fixture ingests file by file and asserts, against the store,
that creation order and path order genuinely differ.

The counts here are literals, hand-derived from the fixture and asserted on both
sides. The inventory-agreement test could compare `mention_facets` with
`mention_documents` and pass while both were wrong in the same way — they share a
table and, until this change, shared nothing else. Comparing each against a
number written here is what makes the agreement worth having.
"""

from __future__ import annotations

import json

import pytest

from jackryan.errors import ValidationError
from jackryan.interfaces.mcp.server import build_mcp_server
from jackryan.mentions import MENTION_KINDS
from jackryan.services.ingestion import MAX_LISTING_PAGE

# The identifier under test, and one that normalises to a different value while
# differing from it by a single character.
CARRIED = "nadia.orlenko@example.test"
NEAR_MISS = "nadia.orlenka@example.test"
# A spelling a document might actually use. Normalisation lowercases an address
# whole, so this is the same identifier.
SHOUTED = "Nadia.Orlenko@Example.Test"

# Sixty plain carriers, one occurrence each.
PLAIN_CARRIERS = 60
# The one document holding it more than once, which must therefore lead the
# ordering.
HEAVY = "heavy.txt"
HEAVY_OCCURRENCES = 3
# One occurrence lying wholly inside the overlap between two chunks: extracted
# twice, and one occurrence.
OVERLAP = "overlap.txt"
# Carries `SHOUTED`, so it is a carrier of `CARRIED`.
SHOUTING = "spelled-differently.txt"
NEAR_MISSES = ("near-miss-a.txt", "near-miss-b.txt")
SILENT = "silent.txt"

# Hand-derived from the fixture above: sixty plain carriers, the heavy one, the
# overlap one, and the shouting one.
EXPECTED_CARRIERS = PLAIN_CARRIERS + 3
# One each, three in the heavy document, one in the overlap document (not two),
# one in the shouting document.
EXPECTED_OCCURRENCES = PLAIN_CARRIERS + HEAVY_OCCURRENCES + 1 + 1


def _carrier_names() -> list[str]:
    """The sixty carrier filenames, in an order that is not their sorted order.

    ASCII on purpose, as `test_document_paging.py` records: SQLite orders text
    byte-wise and Python orders by code point, and the two agree only while
    nothing outside ASCII is in play.
    """
    names = [f"carrier-{index:02d}.txt" for index in range(PLAIN_CARRIERS)]
    # A fixed, reproducible scramble: the odd indices first, then the even ones
    # reversed. Deterministic, so a failure is reproducible, and nowhere near
    # sorted order.
    scrambled = names[1::2] + names[::2][::-1]
    assert sorted(scrambled) == sorted(names), "the scramble lost or repeated a name"
    assert scrambled != sorted(names), "the fixture must be written out of order"
    return scrambled


def _ingest_order() -> list[str]:
    """Every fixture file, in the order the fixture ingests them one by one.

    The heavy carrier goes in the middle rather than first or last, so its
    leading position in the enumeration cannot come from having been ingested
    first, and the non-carriers are interleaved rather than appended.
    """
    plain = _carrier_names()
    order = [
        *plain[:20],
        SILENT,
        *plain[20:40],
        HEAVY,
        NEAR_MISSES[0],
        *plain[40:],
        OVERLAP,
        NEAR_MISSES[1],
        SHOUTING,
    ]
    expected = PLAIN_CARRIERS + 2 + len(NEAR_MISSES) + 2
    assert len(order) == len(set(order)) == expected, (
        f"the ingest order must name each of the {expected} files exactly once"
    )
    return order


def _overlapping_occurrence_text(contract, value: str) -> str:
    """Text placing one occurrence of `value` inside two overlapping windows.

    The same construction `tests/test_mentions.py` uses for the counting rule,
    rebuilt here rather than imported: this file asserts a different property of
    it — that a *carrier's* occurrence count collapses the two extracted rows —
    and a test module importing another test module's private helper couples
    two files that fail for different reasons.

    Built from the contract rather than from literals so it still lands in the
    overlap if the suite's chunk size changes. The chunker steps back by the
    overlap, so the second window opens at `chunk_max_chars - overlap`, and the
    whitespace goes exactly there.
    """
    window, overlap = contract.chunk_max_chars, contract.chunk_overlap_chars
    prose = "The clerk filed the tariff schedule and the annex together. "
    lead_in = " \n Paid to "
    assert len(lead_in) + len(value) < overlap, (
        "the identifier does not fit inside the overlap under this contract"
    )
    filler = prose * (window // len(prose) + 2)
    head = filler[: window - overlap]
    tail = " and the annex was returned unsigned the following week. "
    return head + lead_in + value + tail + filler[: window // 2]


@pytest.fixture
def casefile(context):
    return context.casefiles.create("Carrier Sweep")


@pytest.fixture
def carriers(context, casefile, tmp_path):
    """A folder whose documents carry the identifier, or nearly, or not at all.

    **Ingested one file at a time, in an order that is not their sorted order.**
    A folder walk ingests `sorted(path.rglob("*"))` — `services/ingestion.py:408`
    — so handing the whole folder over makes insertion order, `created_at` order
    and `containment_path` order all the same thing, and an ordering keyed on
    the containment path becomes indistinguishable from one keyed on the
    creation time or the rowid. A reviewer established that by running it: with
    a single folder ingest, replacing `containment_path` with `created_at` in
    both `ORDER BY` clauses left every test in this file green. Ingesting file
    by file is what makes the two orders differ, and the fixture asserts below
    that they do.

    Returns the folder.
    """
    folder = tmp_path / "carrier-sweep"
    folder.mkdir()

    for index, name in enumerate(_carrier_names()):
        (folder / name).write_text(
            f"Invoice {index} was settled by transfer. Contact {CARRIED} "
            "for the remittance advice.\n",
            encoding="utf-8",
        )

    # Three occurrences, spaced far enough apart that no two share a chunk
    # boundary: this document's count must be three, and the overlap collapsing
    # is a separate claim made by `overlap.txt`.
    spacer = "The annex records the schedule of payments in full. " * 12
    (folder / HEAVY).write_text(
        f"First notice sent to {CARRIED}.\n{spacer}\n"
        f"Second notice sent to {CARRIED}.\n{spacer}\n"
        f"Third notice sent to {CARRIED}.\n",
        encoding="utf-8",
    )

    # `.txt` deliberately: `PlainTextExtractor` stores the file's text verbatim,
    # while every markup suffix goes to docling, which re-renders the document
    # and would not preserve the whitespace this fixture depends on.
    overlap_text = _overlapping_occurrence_text(context.config.contract, CARRIED)
    assert overlap_text.count(CARRIED) == 1, "the overlap fixture holds two occurrences"
    boundary = (
        context.config.contract.chunk_max_chars
        - context.config.contract.chunk_overlap_chars
    )
    assert overlap_text[boundary].isspace() and not overlap_text[0].isspace(), (
        "both windows open on the same whitespace, so this fixture cannot "
        "produce the disagreement it exists to catch"
    )
    (folder / OVERLAP).write_text(overlap_text, encoding="utf-8")

    (folder / SHOUTING).write_text(
        f"The form field was filled in capitals: {SHOUTED}\n", encoding="utf-8"
    )
    # The two near-misses must differ in content, not only in name: ingestion
    # identifies a document by its content hash, so two byte-identical files in
    # one folder are one document. Written identically at first, and the
    # fixture's own document count was the only thing that noticed.
    for index, name in enumerate(NEAR_MISSES):
        (folder / name).write_text(
            f"A different correspondent, {NEAR_MISS}, filed annex {index}.\n",
            encoding="utf-8",
        )
    (folder / SILENT).write_text(
        "The ledger for this quarter names no correspondent at all.\n",
        encoding="utf-8",
    )

    for name in _ingest_order():
        report = context.ingestion.ingest(casefile.short_id, folder / name)
        assert report.failed == 0, f"the fixture failed to ingest {name}"

    stored = context.ingestion.list_document_page(
        casefile.short_id, offset=0, limit=MAX_LISTING_PAGE
    )
    # Vacuity guards. Every assertion below is about sixty-three carriers among
    # sixty-six documents; a fixture that quietly stopped producing either would
    # leave this file passing over the wrong corpus.
    expected_documents = PLAIN_CARRIERS + 2 + len(NEAR_MISSES) + 2
    assert stored.total_matching == expected_documents, (
        f"the fixture must hold {expected_documents} documents, "
        f"not {stored.total_matching}"
    )
    # The premise, asserted against the store rather than against the write
    # order: creation order and containment-path order must genuinely differ, or
    # the ordering under test is not distinguishable from no ordering at all.
    by_creation = [
        d.containment_path
        for d in sorted(stored.documents, key=lambda d: (d.created_at, d.id))
    ]
    assert by_creation != sorted(by_creation), (
        "the store holds these documents in containment-path order, so an "
        "ordering keyed on the path cannot be told from one keyed on the "
        "creation time"
    )
    return folder


@pytest.fixture
def expected_order() -> list[str]:
    """The order the enumeration must produce, derived from the fixture's names.

    The heavy carrier leads because the ordering leads with the occurrence
    count. Everything below it holds one occurrence, so it is separated only by
    containment path — which, for a file ingested by name, is the filename.
    """
    ones = sorted([*_carrier_names(), OVERLAP, SHOUTING])
    order = [HEAVY, *ones]
    # A guard that can fail, unlike asserting `order[0] == HEAVY` on a list
    # just built as `[HEAVY, *ones]`: the heavy carrier must sort *after* the
    # first one-occurrence carrier, so leading with it is a claim about the
    # occurrence count rather than about the path.
    assert HEAVY > ones[0], (
        f"{HEAVY!r} sorts before {ones[0]!r}, so count-first and path-first "
        "orderings agree and the leading position proves nothing"
    )
    assert len(order) == EXPECTED_CARRIERS
    return order


def _sweep(context, casefile, mention, limit):
    """Follow `continue_from` to exhaustion, bounded, returning the pages."""
    pages = []
    offset = 0
    # Three times the pages the fixture needs. Bounded, because a mutation to
    # the count's predicate makes an unbounded follow run for ever.
    for _ in range(3 * (EXPECTED_CARRIERS // limit + 2)):
        page = context.search.mention_documents(
            casefile.short_id, mention, offset=offset, limit=limit
        )
        pages.append(page)
        if page.continue_from is None:
            return pages
        offset = page.continue_from
    raise AssertionError(
        f"the enumeration never ended: {len(pages)} pages for "
        f"total_matching={pages[-1].total_matching}"
    )


def _names(page) -> list[str]:
    return [carrier.document.filename for carrier in page.carriers]


# -- the whole set, exactly once -------------------------------------------


def test_every_carrier_is_enumerated_exactly_once_across_pages(
    context, casefile, carriers, expected_order
):
    """Sixty-three carriers over pages of twenty-five, each exactly once."""
    pages = _sweep(context, casefile, CARRIED, 25)

    assert [len(p.carriers) for p in pages] == [25, 25, 13]
    assert [p.offset for p in pages] == [0, 25, 50]
    assert [p.continue_from for p in pages] == [25, 50, None]
    assert [p.truncated for p in pages] == [True, True, False]
    assert all(p.total_matching == EXPECTED_CARRIERS for p in pages)

    seen = [name for page in pages for name in _names(page)]
    assert seen == expected_order
    # Neither near-miss, and not the document that carries nothing.
    for absent in (*NEAR_MISSES, SILENT):
        assert absent not in seen, f"{absent} is not a carrier and was returned"


def test_the_enumeration_agrees_with_the_inventory_it_follows_from(
    context, casefile, carriers
):
    """Two figures the same instance reports about one identifier.

    Both are also compared against literals derived from the fixture, so the
    assertion does not rest only on one production figure agreeing with another.
    """
    facets = context.search.mention_facets(casefile.short_id, "email", limit=50)
    facet = next(f for f in facets if f.value == CARRIED)

    assert facet.documents == EXPECTED_CARRIERS
    assert facet.mentions == EXPECTED_OCCURRENCES

    pages = _sweep(context, casefile, CARRIED, 25)
    carriers_found = [carrier for page in pages for carrier in page.carriers]

    assert len(carriers_found) == facet.documents
    assert sum(c.mentions for c in carriers_found) == facet.mentions


def test_an_occurrence_inside_a_chunk_overlap_is_one_occurrence(
    context, casefile, carriers
):
    """Extracted into two rows by two chunks, and one occurrence.

    The premise is asserted against the store, not inferred from the text: the
    fixture only establishes that the identifier sits at the boundary, which is
    a claim about the chunker. Without this, a chunker change that moved the
    occurrence out of the overlap would leave `mentions == 1` true for the
    uninteresting reason — extracted once — and the test would prove nothing
    while staying green. The sibling in `tests/test_mentions.py` asserts the
    same premise for the same reason; this file's copy had dropped it.
    """
    pages = _sweep(context, casefile, CARRIED, MAX_LISTING_PAGE)
    found = {c.document.filename: c for page in pages for c in page.carriers}
    overlap = found[OVERLAP]

    holding = [
        chunk
        for chunk in context.store.list_document_chunks(overlap.document.id)
        if CARRIED in chunk.text
    ]
    assert len(holding) == 2, (
        f"{OVERLAP} has {len(holding)} chunk(s) carrying the identifier, not 2 "
        "— the occurrence is not inside an overlap, so this test would pass for "
        "the wrong reason"
    )

    assert overlap.mentions == 1


def test_a_carrier_addresses_its_earliest_occurrence(context, casefile, carriers):
    """The passage cited for a carrier is the first mention, not just any of them.

    Asserted through the text the chunk actually holds rather than by comparing
    chunk ids, which no caller can do: `heavy.txt` writes the identifier three
    times, far enough apart to land in three different chunks, and only the
    first is preceded by "First notice". Ordering `_first_passages` by
    `document_offset DESC` reverses the pick and is otherwise undetectable — it
    returns a real passage of the right document, so every other assertion in
    this file stays green while an analyst following the citation lands on the
    last mention of the identifier instead of the first.
    """
    page = context.search.mention_documents(casefile.short_id, CARRIED, limit=1)
    heaviest = page.carriers[0]
    assert heaviest.document.filename == HEAVY

    cited = context.store.get_chunks([heaviest.chunk_id])[heaviest.chunk_id]
    assert cited.document_id == heaviest.document.id
    assert CARRIED in cited.text, "the cited passage does not carry the identifier"
    assert "First notice" in cited.text, (
        f"the carrier cites a later occurrence: {cited.text[:120]!r}"
    )
    assert "Third notice" not in cited.text


def test_the_heaviest_carrier_leads_the_order(context, casefile, carriers):
    page = context.search.mention_documents(casefile.short_id, CARRIED, limit=5)

    assert page.carriers[0].document.filename == HEAVY
    assert page.carriers[0].mentions == HEAVY_OCCURRENCES
    assert all(c.mentions == 1 for c in page.carriers[1:])


def test_a_similar_identifier_is_never_a_carrier(context, casefile, carriers):
    """One character apart, and a different identifier."""
    page = context.search.mention_documents(casefile.short_id, NEAR_MISS, limit=50)

    assert sorted(_names(page)) == sorted(NEAR_MISSES)
    assert page.total_matching == len(NEAR_MISSES)


# -- what the caller typed, and what was matched ---------------------------


def test_the_callers_spelling_is_normalised_before_matching(
    context, casefile, carriers, expected_order
):
    """The spelling a document used resolves to the identifier the store holds."""
    pages = _sweep(context, casefile, SHOUTED, 25)
    seen = [name for page in pages for name in _names(page)]

    assert seen == expected_order
    assert all(p.value == CARRIED for p in pages), (
        "the response must report the normalised form it matched"
    )
    assert all(p.kind == "" for p in pages), "a bare value names no kind"


def test_a_kinded_enumeration_matches_only_that_kind(context, casefile, carriers):
    """A named kind narrows; the wrong kind is empty, not refused."""
    matched = context.search.mention_documents(
        casefile.short_id, f"email:{CARRIED}", limit=MAX_LISTING_PAGE
    )
    assert matched.total_matching == EXPECTED_CARRIERS
    assert matched.kind == "email"

    other = context.search.mention_documents(
        casefile.short_id, f"iban:{CARRIED}", limit=MAX_LISTING_PAGE
    )
    assert other.carriers == []
    assert other.total_matching == 0
    assert other.kind == "iban"


def test_an_unknown_kind_is_refused_naming_the_kinds(context, casefile, carriers):
    with pytest.raises(ValidationError) as excinfo:
        context.search.mention_documents(casefile.short_id, f"passport:{CARRIED}")

    message = str(excinfo.value)
    for kind in MENTION_KINDS:
        assert kind in message, f"the refusal did not name {kind!r}"


def test_an_empty_identifier_is_refused_rather_than_answered(
    context, casefile, carriers
):
    """An empty carrier set reads as "this casefile carries no such identifier".

    Asserted as a raise rather than by inspecting a returned page, so dropping
    the guard reddens instead of returning something this test could accept.
    """
    for empty in ("", "   "):
        with pytest.raises(ValidationError):
            context.search.mention_documents(casefile.short_id, empty)


def test_an_identifier_the_casefile_does_not_carry_is_an_empty_page(
    context, casefile, carriers
):
    page = context.search.mention_documents(
        casefile.short_id, "absent@example.test", limit=25
    )

    assert page.carriers == []
    assert page.total_matching == 0
    assert page.truncated is False
    assert page.continue_from is None


def test_the_enumeration_is_confined_to_its_casefile(context, casefile, carriers, tmp_path):
    """Two casefiles carrying one identifier are two separate answers."""
    other = context.casefiles.create("Other Compartment")
    folder = tmp_path / "other"
    folder.mkdir()
    # Distinct content, for the reason the fixture records: a content hash, not
    # a filename, is what makes two files two documents.
    for index, name in enumerate(("elsewhere-a.txt", "elsewhere-b.txt")):
        (folder / name).write_text(
            f"An unrelated file {index} naming {CARRIED} once.\n", encoding="utf-8"
        )
    assert not context.ingestion.ingest(other.short_id, folder).failed

    mine = context.search.mention_documents(
        casefile.short_id, CARRIED, limit=MAX_LISTING_PAGE
    )
    theirs = context.search.mention_documents(
        other.short_id, CARRIED, limit=MAX_LISTING_PAGE
    )

    assert mine.total_matching == EXPECTED_CARRIERS
    assert theirs.total_matching == 2
    assert sorted(_names(theirs)) == ["elsewhere-a.txt", "elsewhere-b.txt"]
    assert not set(_names(mine)) & set(_names(theirs))


def test_a_mention_naming_another_casefiles_document_is_not_a_carrier(
    context, casefile, carriers, tmp_path
):
    """The confinement holds on every table read, not on `mentions` alone.

    `mentions.casefile_id` is a denormalised copy of the chunk's casefile.
    Confining the read by that column alone makes the compartment depend on the
    copy being right, and a security review of `mentions-and-facets` planted
    exactly this row and found `mention_facets` advertising another casefile's
    identifier. The disclosure here would be larger — a document id, filename,
    containment path, sizes, and a citable passage id.

    The row is written by raw SQL because `replace_chunks` cannot produce it: it
    derives both columns from the chunk being stored. That is the point. This
    asserts the read refuses it anyway, so the guarantee does not rest on one
    writer staying correct.
    """
    other = context.casefiles.create("Other Compartment")
    intruder = tmp_path / "intruder.txt"
    intruder.write_text(
        "A document of the other compartment, naming nobody.\n", encoding="utf-8"
    )
    assert not context.ingestion.ingest(other.short_id, intruder).failed

    hidden = context.store.list_documents(
        context.casefiles.resolve(other.short_id).id
    )[0]
    chunk = context.store.list_document_chunks(hidden.id)[0]
    mine = context.casefiles.resolve(casefile.short_id).id

    # The forged row: it claims this casefile while pointing at the other's
    # document and chunk.
    context.store._db.execute(
        "INSERT INTO mentions (chunk_id, document_id, casefile_id, kind, value,"
        " normalised, char_start, char_end, extractor, confidence, document_offset)"
        " VALUES (?, ?, ?, 'email', ?, ?, 0, 1, 'planted', 1.0, 0)",
        (chunk.id, hidden.id, mine, CARRIED, CARRIED),
    )
    context.store._db.commit()

    page = context.search.mention_documents(
        casefile.short_id, CARRIED, limit=MAX_LISTING_PAGE
    )

    assert hidden.filename not in _names(page), (
        "the enumeration disclosed a document of another casefile"
    )
    assert chunk.id not in [c.chunk_id for c in page.carriers], (
        "the enumeration handed back a passage id from another casefile"
    )
    assert page.total_matching == EXPECTED_CARRIERS, (
        f"the count admitted the planted row: {page.total_matching} against "
        f"{EXPECTED_CARRIERS}"
    )


# -- bounds are clamped, never refused -------------------------------------


def test_an_over_large_limit_is_clamped_rather_than_refused(context, casefile, carriers):
    """The reported bound is the one applied, and it is the ceiling.

    Asserted on `page.limit` rather than on the row count: the fixture holds
    fewer carriers than `MAX_LISTING_PAGE`, so a row count of
    `min(EXPECTED_CARRIERS, MAX_LISTING_PAGE)` is just `EXPECTED_CARRIERS` and
    holds with no clamp at all.
    """
    page = context.search.mention_documents(casefile.short_id, CARRIED, limit=10_000)

    assert page.limit == MAX_LISTING_PAGE
    assert len(page.carriers) == EXPECTED_CARRIERS


def test_an_offset_beyond_sqlite_is_clamped_rather_than_raising(
    context, casefile, carriers
):
    """A bind larger than SQLite's INTEGER is an over-large offset, not a crash."""
    page = context.search.mention_documents(casefile.short_id, CARRIED, offset=2**70)

    assert page.carriers == []
    assert page.total_matching == EXPECTED_CARRIERS


def test_the_store_reports_the_offset_it_applied(context, casefile, carriers):
    """SQLite treats a negative OFFSET as zero, so the report must say zero.

    Reached directly, because the service is the only caller that clamps and
    the hole is one positional argument away.
    """
    page = context.store.documents_with_mention(
        context.casefiles.resolve(casefile.short_id).id, "", CARRIED, -2, 5
    )

    assert page.offset == 0
    assert page.continue_from == 5


def test_the_store_refuses_to_be_unbounded_or_to_stall(context, casefile, carriers):
    """The store floors its own `limit`, as it floors its own offset.

    Reached directly, because the service is the only caller that clamps and
    the hole is one positional argument away — the same argument the offset
    floor is there for. Two values, and each fails differently without the
    floor: SQLite reads a negative `LIMIT` as unbounded, so `-1` returns the
    whole carrier set from a method whose port contract says no unbounded form
    is offered; and `0` returns no rows while the count still reports the whole
    set, so `truncated` stays true and a caller following `continue_from` never
    advances.
    """
    casefile_id = context.casefiles.resolve(casefile.short_id).id

    unbounded = context.store.documents_with_mention(casefile_id, "", CARRIED, 0, -1)
    assert unbounded.limit == 1
    assert len(unbounded.carriers) == 1, (
        f"a negative limit returned {len(unbounded.carriers)} carriers, so the "
        "store offers the unbounded form its contract denies"
    )

    stalled = context.store.documents_with_mention(casefile_id, "", CARRIED, 0, 0)
    assert stalled.limit == 1
    assert stalled.continue_from == 1, (
        "a limit of 0 returned a page that does not advance, so a caller "
        "following continue_from never terminates"
    )


# -- the agent surface -----------------------------------------------------


async def _call(server, name, args=None):
    result = await server.call_tool(name, args or {})
    return json.loads(result.content[0].text)


@pytest.mark.anyio
async def test_an_agent_enumerates_every_carrier_across_pages(
    context, casefile, carriers, expected_order
):
    """The same sweep through the tool, with the row shape asserted exactly."""
    server = build_mcp_server(context)
    seen: list[str] = []
    offset = 0
    pages = []

    for _ in range(10):
        payload = await _call(
            server,
            "case_mention_documents",
            {
                "casefile": casefile.short_id,
                "mention": CARRIED,
                "limit": 25,
                "offset": offset,
            },
        )
        pages.append(payload)
        seen.extend(row["filename"] for row in payload["results"])
        if payload["continue_from"] is None:
            break
        offset = payload["continue_from"]
    else:
        raise AssertionError("the tool never ended its listing")

    assert [p["total"] for p in pages] == [25, 25, 13]
    assert [p["total_matching"] for p in pages] == [EXPECTED_CARRIERS] * 3
    assert [p["truncated"] for p in pages] == [True, True, False]
    assert [p["continue_from"] for p in pages] == [25, 50, None]
    assert seen == expected_order
    # Exactly, not by containment: a renamed key stays truthy and passes every
    # value-by-value assertion.
    assert set(pages[0]["results"][0]) == {
        "document_id",
        "short_id",
        "filename",
        "media_type",
        "read_as",
        "characters",
        "byte_size",
        "mentions",
        "chunk_id",
    }


@pytest.mark.anyio
async def test_a_page_past_the_end_is_empty_without_denying_the_carriers(
    context, casefile, carriers
):
    """An empty page past the end must not read as "nothing carries this"."""
    server = build_mcp_server(context)
    payload = await _call(
        server,
        "case_mention_documents",
        {
            "casefile": casefile.short_id,
            "mention": CARRIED,
            "offset": EXPECTED_CARRIERS + 10,
        },
    )

    assert payload["results"] == []
    assert payload["total_matching"] == EXPECTED_CARRIERS
    assert str(EXPECTED_CARRIERS) in payload["formatted"]
    assert "No document in this casefile carries" not in payload["formatted"]


@pytest.mark.anyio
async def test_an_agent_cites_a_carrier_without_a_ranked_search(
    context, casefile, carriers
):
    """Inventory, enumerate, cite — with `case_search` taken off the surface.

    Removing the tool is what makes "without a search" provable rather than
    asserted. The gap this closes is recorded in
    `docs/implementation-notes.md`: before this change no tool handed back a
    `chunk_id` for a document reached by listing, so citing one took a search.
    """
    server = build_mcp_server(context)
    server.remove_tool("case_search")

    inventory = await _call(
        server, "case_mentions", {"casefile": casefile.short_id, "kind": "email"}
    )
    value = next(
        row["value"] for row in inventory["results"] if row["value"] == CARRIED
    )

    page = await _call(
        server,
        "case_mention_documents",
        {"casefile": casefile.short_id, "mention": value, "limit": 5},
    )
    row = page["results"][0]
    assert row["chunk_id"], "a carrier must address a passage"

    citation = await _call(
        server,
        "case_cite",
        {"casefile": casefile.short_id, "chunk_id": row["chunk_id"]},
    )
    assert "error" not in citation, citation
    # The citation resolves to the document the carrier named, and to the
    # passage its `chunk_id` addressed.
    assert citation["document_id"] == row["document_id"]
    assert citation["chunk_id"] == row["chunk_id"]
    assert citation["document"] == row["filename"]
