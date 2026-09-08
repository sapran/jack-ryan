"""What a search result says about itself, on all three surfaces.

A result's text may now be wider than the passage that matched it, so a result
carries two spans: the one it returned and the one it matched. Every adapter has
to report the same two, because an analyst reading the REST output and an agent
reading the MCP payload are looking at one fact.

The identifier inventory and the pivot that follows an entry from it are held to
the same rule: one question, one answer, whichever surface asks it.
"""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlencode

import anyio
import pytest

from jackryan import cli
from jackryan.interfaces.mcp import build_mcp_server
from jackryan.interfaces.mcp.profiles import PROFILES
from jackryan.server import create_app, serialize_hit

QUERY = "harbour lease"


SECTION = " ".join(
    f"The harbour lease clause {n} concerns the berth and the annual fee." for n in range(1, 21)
)


@pytest.fixture
def loaded(context, tmp_path):
    """Documents long enough to hold several passages, so a window has room.

    The shared fixture corpus is one passage per document, where a window would
    be the document itself and nothing would ever be widened — which would make
    these tests pass while proving nothing.
    """
    folder = tmp_path / "shapes"
    folder.mkdir()
    (folder / "lease.md").write_text(
        f"# Harbour Lease\n\n## Terms\n\n{SECTION}\n\n"
        f"## Payment\n\n{SECTION} A cormorant was noted on the mooring buoy.\n",
        encoding="utf-8",
    )
    (folder / "notes.txt").write_text(
        "Unrelated kitchen notes about baking bread and grinding coffee.\n",
        encoding="utf-8",
    )
    casefile = context.casefiles.create("Shapes")
    report = context.ingestion.ingest(casefile.short_id, folder)
    assert not report.failed
    return context, casefile


async def call(server, name, args):
    result = await server.call_tool(name, args)
    return json.loads(result.content[0].text)


# The parity test below is synchronous on purpose. It also builds a FastAPI
# `TestClient`, which runs an event loop of its own, and creating one inside an
# already-running loop aborts the interpreter at teardown: the suite reports
# every test passing and the process exits 134, which CI reads as a failure with
# nothing to show for it.


def rest_hits(context, casefile):
    """The REST shape, taken from its serialiser rather than over HTTP.

    The route itself is covered in `test_rest.py`. It is not driven here because
    a FastAPI test client and the agent surface's servers, built in one module,
    leave the interpreter aborting at teardown on macOS — the suite reports every
    test passing and the process exits 134. What this module is actually about is
    whether the three serialisers agree, and that is what it now asks.
    """
    hits = context.search.search(casefile.short_id, QUERY, limit=10)
    return {"results": [serialize_hit(h) for h in hits]}


def cli_hits(context, casefile, monkeypatch, capsys):
    monkeypatch.setattr(cli, "build_context", lambda: context)
    monkeypatch.setattr(context, "close", lambda: None)
    cli.main(["--json", "search", casefile.short_id, QUERY])
    return json.loads(capsys.readouterr().out)


def test_every_surface_reports_the_same_two_spans(loaded, monkeypatch, capsys):
    context, casefile = loaded
    service_hits = context.search.search(casefile.short_id, QUERY, limit=10)
    assert service_hits

    server = build_mcp_server(context)
    agent = anyio.run(call, server, "case_search", {"casefile": casefile.short_id, "query": QUERY})
    rest = rest_hits(context, casefile)
    command = cli_hits(context, casefile, monkeypatch, capsys)

    for hit, mcp_row, rest_row, cli_row in zip(
        service_hits, agent["results"], rest["results"], command
    ):
        assert mcp_row["chunk_id"] == rest_row["chunk_id"] == cli_row["chunk_id"]
        # The span of the text returned.
        assert mcp_row["char_start"] == rest_row["char_start"] == cli_row["char_start"]
        assert mcp_row["char_end"] == rest_row["char_end"] == cli_row["char_end"]
        assert (mcp_row["char_start"], mcp_row["char_end"]) == (hit.char_start, hit.char_end)
        # And the passage inside it that matched.
        assert rest_row["matched_char_start"] == hit.chunk.char_start
        assert rest_row["matched_char_end"] == hit.chunk.char_end
        assert cli_row["matched_char_start"] == hit.chunk.char_start


def test_the_agent_payload_names_the_matched_passage_in_provenance(loaded):
    context, casefile = loaded
    server = build_mcp_server(context)
    # One hit, so its neighbours are not themselves results and the window has
    # room to grow. With ten results from one document every passage is a hit
    # and nothing may widen — correct, but it would prove nothing here.
    payload = anyio.run(call, server, "case_search",
        {"casefile": casefile.short_id, "query": "cormorant", "limit": 1},
    )

    widened = [row for row in payload["results"] if "matched" in row["provenance"]]
    assert widened, "nothing was widened, so this test says nothing"
    for row in widened:
        matched = row["provenance"]["matched"]
        assert matched["chunk_id"] == row["chunk_id"]
        assert row["provenance"]["char_start"] <= matched["char_start"]
        assert row["provenance"]["char_end"] >= matched["char_end"]


def test_the_agent_payload_says_what_decided_the_order(loaded):
    context, casefile = loaded
    server = build_mcp_server(context)
    payload = anyio.run(call, server, "case_search", {"casefile": casefile.short_id, "query": QUERY}
    )
    assert payload["ranking"] == "fusion"
    assert all("rerank_score" not in row for row in payload["results"])


def test_the_body_still_appears_once_and_the_index_matches(loaded):
    """The fence and the index invariants survive a widened body."""
    context, casefile = loaded
    server = build_mcp_server(context)
    payload = anyio.run(call, server, "case_search", {"casefile": casefile.short_id, "query": QUERY}
    )

    assert len(payload["formatted"].splitlines()) == len(payload["results"])
    nonce = payload["fence_nonce"]
    for row in payload["results"]:
        assert row["text"].count(f"<<<UNTRUSTED {nonce}") == 1
        body = row["text"].split("\n", 1)[1].rsplit("\n", 1)[0]
        # The index carries no passage prose, so a body must not appear in it.
        assert body not in payload["formatted"]


def test_a_person_is_told_how_a_hit_was_obtained(loaded, monkeypatch, capsys):
    """REST and the CLI omitted `read_as` on a hit while the agent carried it,
    so a person was the only party not told the text came from a scan."""
    context, casefile = loaded
    rest = rest_hits(context, casefile)
    command = cli_hits(context, casefile, monkeypatch, capsys)
    assert all(row["read_as"] for row in rest["results"])
    assert all(row["read_as"] for row in command)


def test_an_over_large_limit_is_still_clamped(loaded):
    context, casefile = loaded
    server = build_mcp_server(context)
    payload = anyio.run(call, server, "case_search",
        {"casefile": casefile.short_id, "query": "the", "limit": 10_000},
    )
    assert payload["total"] <= 50


def test_a_response_stays_within_the_text_bound(loaded):
    from jackryan.services.windowing import MAX_RESPONSE_CHARS

    context, casefile = loaded
    server = build_mcp_server(context)
    payload = anyio.run(
        call,
        server,
        "case_search",
        {"casefile": casefile.short_id, "query": "the", "limit": 50},
    )
    carried = sum(len(row["text"]) for row in payload["results"])
    assert carried <= MAX_RESPONSE_CHARS + len(payload["results"]) * 64


def test_the_agent_payload_carries_a_rerank_score_when_one_ran(context, tmp_path):
    """Every other rerank assertion here is a negative one taken from an instance
    that has no reranker — the same value as a hardcoded default."""
    from jackryan.interfaces.mcp.shapes import search_payload
    from jackryan.services.search import SearchService

    class Stub:
        name = "stub"

        def check(self):
            return None

        def score(self, query, passages):
            return [float(len(passages) - index) for index in range(len(passages))]

    folder = tmp_path / "reranked"
    folder.mkdir()
    (folder / "lease.md").write_text(
        f"# Harbour Lease\n\n## Terms\n\n{SECTION}\n", encoding="utf-8"
    )
    casefile = context.casefiles.create("Reranked")
    context.ingestion.ingest(casefile.short_id, folder)

    service = SearchService(
        context.store, context.casefiles, context.embedder, reranker=Stub()
    )
    hits = service.search(casefile.short_id, QUERY, limit=5)
    assert hits

    payload = search_payload(hits, query=QUERY, casefile_id=casefile.id)

    assert payload["ranking"] == "rerank"
    for row in payload["results"]:
        assert "rerank_score" in row
        # The fusion score is still there, and is a different quantity.
        assert row["score"] != row["rerank_score"]


# -- the identifier inventory, and the pivot out of it ----------------------

ROLE = Path(__file__).resolve().parents[1] / "analyst" / "role.md"

IDENTIFIER_QUERY = "harbour invoice berth"

# The pivot is written as `case_mentions` hands it back — normalised. That is
# the whole point of normalising: the document says `Billing@Acme.example` and
# this finds it.
PIVOT = "email:billing@acme.example"

# What the fixture below actually contains, counted by hand from its own text.
# The oracle is the fixture, not any surface that reports it, so a surface which
# dropped a row or swapped the two counts has nothing to hide behind. The email
# is written twice in one document and once in another, so `mentions` and
# `documents` are different numbers for it — reported the wrong way round they
# would both still look plausible.
EXPECTED_FACETS = frozenset(
    {
        ("email", "billing@acme.example", 3, 2),
        ("iban", "GB82WEST12345698765432", 1, 1),
        ("phone", "+380441234567", 1, 1),
        ("registration_number", "20240115", 1, 1),
    }
)


@pytest.fixture
def identified(context, tmp_path):
    """Two documents carrying identifiers and one carrying none.

    The longest is 272 characters against the contract's 400-character chunk
    width, so each document is a single chunk and a mention count is exactly the
    number of times the identifier is written. The contract also sets a
    50-character overlap, and an identifier landing inside one would be found
    once per chunk that held it — the counts asserted here would then be a guess
    about the chunker rather than a fact about the text.

    The third document shares the query's vocabulary and carries no identifier
    at all. That is what makes a filtered search narrower than an unfiltered one
    here rather than accidentally equal to it, which would let a filter that
    never ran pass every assertion below.
    """
    folder = tmp_path / "identified"
    folder.mkdir()
    (folder / "invoice.md").write_text(
        "# Invoice\n\n"
        "Payment for the harbour berth is due. Remit to IBAN "
        "GB82 WEST 1234 5698 7654 32, confirm by email to Billing@Acme.example, "
        "or telephone +38 (044) 123-45.67. The supplier is registered under "
        "ЄДРПОУ 20240115. Send invoice queries to Billing@Acme.example as well.\n",
        encoding="utf-8",
    )
    (folder / "letter.md").write_text(
        "# Letter\n\n"
        "Further to the harbour invoice, the berth fee was settled in full. "
        "Address any correspondence to billing@acme.example until the lease "
        "is signed.\n",
        encoding="utf-8",
    )
    (folder / "minutes.md").write_text(
        "# Minutes\n\n"
        "The committee discussed the harbour invoice and the berth fee at "
        "length, and resolved to await the auditor before settling anything.\n",
        encoding="utf-8",
    )
    casefile = context.casefiles.create("Identified")
    report = context.ingestion.ingest(casefile.short_id, folder)
    assert not report.failed
    assert report.ingested == 3
    return context, casefile


async def rest_get(app, path, query=""):
    """One GET against the REST app itself: routing, query parsing, serialising.

    `test_rest.py` drives these routes over a FastAPI `TestClient`, and one must
    not be built in this module for the reason recorded above it. Calling the
    ASGI application inside the same single `anyio.run` the agent surface uses
    drives the shipped handler with one event loop that closes cleanly — and
    unlike lifting the route function out of `app.routes`, it goes through
    FastAPI's own query parsing, so the parameter names an analyst types
    (`?mention=`, `?kind=`) are part of what is proved.
    """
    messages: list[dict] = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        messages.append(message)

    await app(
        {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": path,
            "raw_path": path.encode(),
            "query_string": query.encode(),
            "root_path": "",
            "headers": [(b"host", b"testserver")],
            "client": ("127.0.0.1", 51234),
            "server": ("testserver", 80),
            "app": app,
        },
        receive,
        send,
    )
    status = next(m["status"] for m in messages if m["type"] == "http.response.start")
    body = b"".join(
        m.get("body", b"") for m in messages if m["type"] == "http.response.body"
    )
    assert status == 200, f"REST answered {status}: {body.decode(errors='replace')}"
    return json.loads(body)


def rest_app(context):
    """The real app, with the context the lifespan would have attached.

    The lifespan is deliberately not run: it starts the mounted agent surface's
    session manager, which is a second event loop's worth of machinery this
    module has no business starting. The REST routes read the context from
    `app.state` and nothing else from it.
    """
    app = create_app(context)
    app.state.context = context
    return app


def cli_json(context, monkeypatch, capsys, argv):
    monkeypatch.setattr(cli, "build_context", lambda: context)
    monkeypatch.setattr(context, "close", lambda: None)
    assert cli.main(["--json", *argv]) == 0
    return json.loads(capsys.readouterr().out)


def facets_of(rows):
    """A surface's inventory reduced to the four facts every surface must agree on."""
    return frozenset(
        (row["kind"], row["value"], row["mentions"], row["documents"]) for row in rows
    )


def test_every_surface_reports_the_same_identifier_inventory(
    identified, monkeypatch, capsys
):
    """One question — what identifiers does this casefile contain — asked four ways.

    Catches a surface that answers it differently from the others: a row dropped
    by one serialiser, a value normalised on one path and not another, or the two
    counts crossed. An analyst reading the CLI and an agent reading the payload
    are deciding where to look next from the same numbers, and a disagreement
    between them is invisible to whoever is reading only one.
    """
    context, casefile = identified

    service = frozenset(
        (f.kind, f.value, f.mentions, f.documents)
        for f in context.search.mention_facets(casefile.short_id)
    )
    assert service == EXPECTED_FACETS, (
        "the service layer does not report the inventory the fixture's own text "
        f"contains; expected {sorted(EXPECTED_FACETS)}, got {sorted(service)}"
    )

    rest = anyio.run(
        rest_get, rest_app(context), f"/api/casefiles/{casefile.short_id}/mentions"
    )
    server = build_mcp_server(context)
    agent = anyio.run(call, server, "case_mentions", {"casefile": casefile.short_id})
    command = cli_json(context, monkeypatch, capsys, ["mentions", casefile.short_id])

    for surface, rows in (
        ("REST", rest["results"]),
        ("the agent payload", agent["results"]),
        ("the CLI", command),
    ):
        assert facets_of(rows) == service, (
            f"{surface} reports a different inventory from the service layer: "
            f"{sorted(facets_of(rows))} against {sorted(service)}"
        )

    assert rest["total"] == agent["total"] == len(command) == len(EXPECTED_FACETS), (
        f"the surfaces count the inventory differently: REST {rest['total']}, "
        f"agent {agent['total']}, CLI {len(command)}, expected {len(EXPECTED_FACETS)}"
    )


def test_every_surface_narrows_a_search_to_the_same_passages(
    identified, monkeypatch, capsys
):
    """The pivot out of the inventory, asked of every surface.

    Each surface threads the filter separately — positionally on the agent
    surface, by keyword on REST, through an argparse default on the CLI — and
    each returns the passages the retrievers selected, in fusion's order. This is
    the assertion that catches one surface passing the filter to the wrong
    parameter or dropping it, which on its own reads as an honest empty-handed
    answer rather than as a fault.
    """
    context, casefile = identified

    hits = context.search.search(casefile.short_id, IDENTIFIER_QUERY, mention=PIVOT)
    expected = [hit.chunk.id for hit in hits]
    # Two of the three documents carry the address, one of them writing it in a
    # different case. Fewer than three, so the filter demonstrably narrowed;
    # more than one, so "the same order" is a claim about something.
    assert len(expected) == 2, f"expected the two documents carrying the address, got {expected}"

    rest = anyio.run(
        rest_get,
        rest_app(context),
        f"/api/casefiles/{casefile.short_id}/search",
        urlencode({"q": IDENTIFIER_QUERY, "mention": PIVOT}),
    )
    server = build_mcp_server(context)
    agent = anyio.run(
        call,
        server,
        "case_search",
        {"casefile": casefile.short_id, "query": IDENTIFIER_QUERY, "mention": PIVOT},
    )
    command = cli_json(
        context,
        monkeypatch,
        capsys,
        ["search", casefile.short_id, IDENTIFIER_QUERY, "--mention", PIVOT],
    )

    for surface, rows in (
        ("REST", rest["results"]),
        ("the agent payload", agent["results"]),
        ("the CLI", command),
    ):
        assert [row["chunk_id"] for row in rows] == expected, (
            f"{surface} returned different passages for the same filtered search: "
            f"{[row['chunk_id'] for row in rows]} against {expected}"
        )

    assert rest["mention"] == PIVOT, "REST does not echo the filter it applied"


def test_the_inventory_payload_is_a_listing_that_still_declares_its_content(identified):
    """Why `listing_payload` is the right builder here, and what had to be added.

    A facet entry carries a kind, a normalised identifier and two integers, and
    no facet value can forge a row: three kinds normalise to `[0-9+]` or
    `[A-Z0-9]`, and the email charset admits no whitespace at all. That is what
    makes an unfenced listing correct, and it is invisible from the call site —
    the moment an entry carries a surrounding snippet it is corpus prose, an
    instruction can hide in it, and the payload has to move to
    `search_payload`'s fencing. Pinning the key set turns that condition into
    something a later change trips over.

    This test previously asserted `content_notice not in payload`, on the
    argument that an identifier has no room for an instruction. A reviewer
    disproved it: the email pattern's local part admitted `.`, `_`, `%`, `+` and
    `-` as word separators with no length bound, so one match could be a
    1,417-character sentence, planted at a repetition count that chose its rank
    in a payload the surface tells an agent to read first. The pattern is now
    bounded at RFC 5321's limits *and* the payload declares its content — a
    length bound alone is not an argument that nothing objectionable fits, so the
    notice is asserted here rather than its absence.
    """
    context, casefile = identified
    server = build_mcp_server(context)
    payload = anyio.run(call, server, "case_mentions", {"casefile": casefile.short_id})

    assert "formatted" in payload and "results" in payload
    assert payload["results"], "an empty inventory would satisfy every assertion below"
    # No per-value fence: the values are what a caller passes back as a filter,
    # and fencing each one would make them unusable for that.
    assert "fence_nonce" not in payload
    assert payload.get("content_notice"), (
        "the inventory does not declare that its values are corpus material. "
        "Every value in it was written by whoever wrote the documents, and an "
        "agent reading this payload first is told nothing about that"
    )

    for row in payload["results"]:
        assert set(row) == {"kind", "value", "mentions", "documents"}, (
            f"an inventory entry carries {sorted(set(row))}. An entry carrying "
            "surrounding prose is corpus text an instruction can hide in, and "
            "must be built by `search_payload` and fenced, not by `listing_payload`"
        )


def test_an_agent_search_survives_being_given_a_filter(identified):
    """The filter reaches the service through `anyio.to_thread.run_sync`, which
    forwards positional arguments only. Passed as a keyword there the call raises
    `TypeError: run_sync() got an unexpected keyword argument 'mention'`, and it
    raises it when a search runs — never at import and never when the tool is
    defined, so the surface loads, advertises the tool and teaches it, and
    nothing before a real call notices.

    Whether that breaks every search or only a filtered one depends on how the
    argument is passed — an unconditional keyword breaks both, a keyword added
    only when a filter is present breaks only the pivot — which is why this
    asserts an unfiltered search that answers and a filtered one that narrows.
    """
    context, casefile = identified
    server = build_mcp_server(context)

    unfiltered = anyio.run(
        call, server, "case_search", {"casefile": casefile.short_id, "query": IDENTIFIER_QUERY}
    )
    assert unfiltered["total"] == 3, "the unfiltered search is the baseline and must find all three"

    filtered = anyio.run(
        call,
        server,
        "case_search",
        {"casefile": casefile.short_id, "query": IDENTIFIER_QUERY, "mention": PIVOT},
    )
    assert "error" not in filtered, f"the filtered search failed: {filtered}"
    assert 0 < filtered["total"] < unfiltered["total"], (
        f"the filter did not narrow anything: {filtered['total']} of "
        f"{unfiltered['total']} passages"
    )


def test_the_inventory_tool_is_advertised_stamped_taught_and_in_the_role(identified):
    """The four registration points a new tool has to reach, none of which the
    existing surface tests reach by name.

    `test_only_the_profiles_tools_are_advertised` compares the advertised set
    against `READONLY_TOOLS`, which is the same set on both sides: dropping this
    tool from it leaves that test green and the tool simply gone.
    `test_every_advertised_tool_is_namespaced_and_stamped` asserts that a stamp
    exists and that `read_only` is set, over whatever happens to be advertised,
    and says nothing about the other two hints.
    `test_the_surface_teaches_the_method` and the analyst pack's
    `test_the_role_names_the_method_and_the_tools` both enumerate tool names, and
    neither list includes this one — containment over a list that does not name
    you is not coverage.

    Two lines below are deliberately doubled with that first test: a stamp is one
    statement about one tool, and reading two thirds of it here and the last
    third in another module makes neither readable.
    """
    context, _ = identified

    for profile in sorted(PROFILES):
        server = build_mcp_server(context, profile=profile)
        advertised = {tool.name: tool for tool in anyio.run(server.list_tools)}
        assert "case_mentions" in advertised, (
            f"the {profile} profile does not advertise case_mentions, so an agent "
            "on it cannot ask what identifiers a casefile holds"
        )
        stamp = advertised["case_mentions"].annotations
        assert stamp is not None, "case_mentions is advertised unstamped"
        # Read from the advertised tool rather than the annotations table: the
        # table is what is stored, this is what an agent is actually told.
        assert stamp.read_only_hint is True
        assert stamp.destructive_hint is False
        assert stamp.open_world_hint is False, (
            "case_mentions counts rows in the local store and reaches nothing "
            "beyond it, so it is closed-world"
        )

    server = build_mcp_server(context)
    assert "case_mentions" in (server.instructions or ""), (
        "the surface does not teach the tool, so an agent has to discover the "
        "inventory by reading tool descriptions it was never told to read"
    )

    assert "case_mentions" in ROLE.read_text(encoding="utf-8"), (
        "the analyst role does not name the tool. Its pivot step is where an "
        "identifier becomes the next search, and that is this tool's only purpose"
    )


# -- what the two human surfaces share, and what they deliberately do not ----


def test_the_two_human_surfaces_agree_on_every_shared_document_field(context, corpus):
    """One renderer, so the fields they share cannot drift apart again.

    They had drifted: the CLI and REST document renderings differed in five
    ways, and only the surface-by-surface tests above caught the parts that
    mattered. The nine fields below are now produced once, so this asserts a
    property of the code rather than a coincidence between two copies.

    The divergence is asserted too, and asymmetrically — which is worth saying
    rather than glossing. REST's four extra fields are unconditional, so
    comparing the difference exactly pins them. The CLI's extras are all
    *conditional* — `found_at`, `children`, `summary`, `summary_by` — and this
    corpus triggers none of them, so its side of the assertion pins "the CLI
    added nothing **here**", not "the CLI's divergence is what we intend".
    Deleting the `found_at` and `children` blocks outright would keep this
    green; that gap is recorded in `docs/implementation-notes.md` rather than
    closed here, because closing it needs a container fixture this test does
    not otherwise want.

    A shared renderer is only an improvement if it makes the sharing structural
    *and* leaves the deliberate differences visible — otherwise the next reader
    deletes one of them as duplication.
    """
    from jackryan.cli import _render_document
    from jackryan.rendering import render_document
    from jackryan.server import serialize_document

    casefile = context.casefiles.create("Shared Fields")
    context.ingestion.ingest(casefile.short_id, corpus)
    document = context.ingestion.list_documents(casefile.short_id)[0]

    shared = render_document(document)
    assert len(shared) == 9, "the shared core changed size; both surfaces move with it"

    from_cli = _render_document(document)
    from_rest = serialize_document(document)
    for key, value in shared.items():
        assert from_cli[key] == value, f"the CLI disagrees about {key}"
        assert from_rest[key] == value, f"REST disagrees about {key}"

    # REST carries two fields the CLI does not, and emits the summary whether or
    # not there is one: a JSON consumer branching on a missing key is worse
    # served than one branching on an empty string.
    # Exactly these, not merely at least these: a subset check would let a fifth
    # REST-only field appear while the docstring above claims the divergence is
    # asserted in both directions.
    assert set(from_rest) - set(shared) == {
        "casefile_id",
        "updated_at",
        "summary",
        "summary_by",
    }
    # The CLI omits an empty summary so a table keeps the width the corpus
    # warrants, and this corpus was ingested with no summariser configured.
    assert not document.summary
    assert set(from_cli) - set(shared) == set()


def test_only_the_rounding_separates_the_two_hit_renderings(context, corpus):
    """The seventeen fields agree; the CLI rounds and REST does not.

    Asserted as "everything but these two keys is equal" rather than field by
    field, so a field added to one and not the other fails here rather than
    waiting for someone to notice.
    """
    from dataclasses import replace

    from jackryan.cli import _render_hit
    from jackryan.server import serialize_hit

    casefile = context.casefiles.create("Rounding")
    context.ingestion.ingest(casefile.short_id, corpus)
    hit = context.search.search(casefile.short_id, "harbour lease", limit=1)[0]

    # A rerank score, because it is the second of the two rounded fields and
    # nothing in the suite pinned it. `dataclasses.replace` rather than a real
    # reranker: no model ships enabled, and what is under test is the rendering.
    hit = replace(hit, rerank_score=-3.14159265358979, ranking="rerank")

    from_cli = _render_hit(hit)
    from_rest = serialize_hit(hit)
    assert set(from_cli) == set(from_rest)
    assert {k: v for k, v in from_cli.items() if k not in {"score", "rerank_score"}} == {
        k: v for k, v in from_rest.items() if k not in {"score", "rerank_score"}
    }

    # Asserted against the value the service produced, not against each other.
    # `from_cli == round(from_rest, 6)` holds whether or not REST rounded, since
    # rounding an already-rounded value changes nothing — so it could only ever
    # catch the CLI. Flipping REST to round as well destroyed the one difference
    # this parameter exists for and left 55 tests green.
    assert from_rest["score"] == hit.score
    assert from_rest["rerank_score"] == hit.rerank_score
    assert from_cli["score"] == round(hit.score, 6)
    assert from_cli["rerank_score"] == round(hit.rerank_score, 6)
    # And the rounding is not a no-op on this fixture, or the four assertions
    # above would agree for a reason that has nothing to do with rounding.
    assert from_cli["rerank_score"] != from_rest["rerank_score"]


async def rest_post(app, path, payload):
    """One POST against the REST app itself, the GET helper's twin.

    Separate rather than folded into `rest_get`: a POST carries a body and a
    content-type header, and threading both through the GET helper's signature
    would make every existing caller pass two arguments it has no use for.
    """
    body = json.dumps(payload).encode()
    messages: list[dict] = []

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(message):
        messages.append(message)

    await app(
        {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "root_path": "",
            "headers": [
                (b"host", b"testserver"),
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
            ],
            "client": ("127.0.0.1", 51234),
            "server": ("testserver", 80),
            "app": app,
        },
        receive,
        send,
    )
    status = next(m["status"] for m in messages if m["type"] == "http.response.start")
    out = b"".join(
        m.get("body", b"") for m in messages if m["type"] == "http.response.body"
    )
    assert status == 200, f"REST answered {status}: {out.decode(errors='replace')}"
    return json.loads(out)


def test_the_two_human_surfaces_return_the_same_ingest_result(
    context, tmp_path, monkeypatch, capsys
):
    """One ingest, two surfaces, one answer — including why it fell short.

    The coverage fields are the ones a caller decides whether to trust the
    corpus on, so a surface missing one of them is a surface that reports a
    partial ingest as a whole one. Both surfaces built this payload
    independently before.
    """
    folder = tmp_path / "drop"
    folder.mkdir()
    (folder / "lease.md").write_text("# Lease\n\nThe harbour lease was awarded.\n", "utf-8")
    (folder / "activate.bat").write_bytes(b"@echo off\r\nnet use z: \\\\server\\share\r\n")
    (folder / "empty.txt").write_text("", encoding="utf-8")

    for_cli = context.casefiles.create("Cli Intake")
    for_rest = context.casefiles.create("Rest Intake")

    cli_payload = cli_json(
        context, monkeypatch, capsys, ["ingest", for_cli.short_id, str(folder)]
    )
    rest_payload = anyio.run(
        rest_post,
        rest_app(context),
        f"/api/casefiles/{for_rest.short_id}/ingest",
        {"path": str(folder)},
    )

    assert set(cli_payload) == set(rest_payload)
    # Two casefiles ingesting one folder, so `casefile_id` and each outcome's
    # `document_id` differ by construction. They are excluded the way `score`
    # is above, and everything that describes *coverage* is compared whole —
    # which is the part a caller decides whether to trust the corpus on.
    def without_identifiers(payload):
        return {
            **{k: v for k, v in payload.items() if k != "casefile_id"},
            "outcomes": [
                {k: v for k, v in outcome.items() if k != "document_id"}
                for outcome in payload["outcomes"]
            ],
        }

    assert without_identifiers(cli_payload) == without_identifiers(rest_payload)
    # The ids are still asserted to be *present* on both, or dropping the field
    # from one surface would pass the comparison above.
    for payload in (cli_payload, rest_payload):
        stored = [o for o in payload["outcomes"] if o["status"] == "ingested"]
        assert stored and all(o["document_id"] for o in stored)

    # And the values are the ones the run actually had, not merely equal to each
    # other: two surfaces both reporting `complete: true` would agree here.
    assert cli_payload["complete"] is False
    assert cli_payload["skipped"] == ["activate.bat"]
    assert cli_payload["refusals"] == []
    assert cli_payload["exhausted_by"] is None
    assert cli_payload["ingested"] == 1
    assert cli_payload["failed"] == 1
    assert any("no registered extractor" in line for line in cli_payload["limitations"])
    assert any("failed to be read" in line for line in cli_payload["limitations"])


# -- the exhaustive path out of the inventory --------------------------------

# Hand-counted from the `identified` fixture's own text: `invoice.md` writes the
# address twice and `letter.md` once, so two documents carry it and their counts
# sum to the three the inventory reports. Two rather than one, so an ordering by
# occurrence count is a claim about something; fewer than three, so a carrier set
# equal to the casefile would not pass.
EXPECTED_CARRIER_ROWS = frozenset({("invoice.md", 2), ("letter.md", 1)})
PIVOT_VALUE = "billing@acme.example"


def carriers_of(rows):
    """A surface's carrier page reduced to the two facts every surface must agree on."""
    return frozenset((row["filename"], row["mentions"]) for row in rows)


def test_every_surface_enumerates_the_same_carriers(identified, monkeypatch, capsys):
    """One question — which documents carry this identifier — asked four ways.

    All four are compared against `EXPECTED_CARRIER_ROWS`, hand-counted from the
    fixture's text, rather than against each other: four surfaces agreeing on a
    wrong answer is exactly what one service method behind all of them makes
    likely, and comparing them only with each other could not see it.
    """
    context, casefile = identified

    page = context.search.mention_documents(casefile.short_id, PIVOT_VALUE)
    service = frozenset(
        (c.document.filename, c.mentions) for c in page.carriers
    )
    assert service == EXPECTED_CARRIER_ROWS, (
        "the service layer does not enumerate the carriers the fixture's own "
        f"text contains; expected {sorted(EXPECTED_CARRIER_ROWS)}, got {sorted(service)}"
    )

    rest = anyio.run(
        rest_get,
        rest_app(context),
        f"/api/casefiles/{casefile.short_id}/mentions/documents",
        urlencode({"mention": PIVOT_VALUE}),
    )
    server = build_mcp_server(context)
    agent = anyio.run(
        call,
        server,
        "case_mention_documents",
        {"casefile": casefile.short_id, "mention": PIVOT_VALUE},
    )
    command = cli_json(
        context, monkeypatch, capsys, ["mention-documents", casefile.short_id, PIVOT_VALUE]
    )

    for surface, rows in (
        ("REST", rest["documents"]),
        ("the agent payload", agent["results"]),
        ("the CLI", command["documents"]),
    ):
        assert carriers_of(rows) == EXPECTED_CARRIER_ROWS, (
            f"{surface} enumerates different carriers: {sorted(carriers_of(rows))} "
            f"against {sorted(EXPECTED_CARRIER_ROWS)}"
        )

    # The four paging scalars, which are the point of a paged answer: a surface
    # that dropped `total_matching` or computed `truncated` its own way would
    # agree on the rows above and mislead about coverage.
    for surface, payload in (
        ("REST", rest),
        ("the agent payload", agent),
        ("the CLI", command),
    ):
        assert payload["offset"] == 0, surface
        assert payload["total_matching"] == len(EXPECTED_CARRIER_ROWS), surface
        assert payload["truncated"] is False, surface
        assert payload["continue_from"] is None, surface
        # The normalised form actually matched, which the caller must be able to
        # see: here it is what was typed, and the fixture writes it in two cases.
        assert payload["value"] == PIVOT_VALUE, surface
        assert payload["kind"] == "", surface


def test_no_surface_denies_the_carriers_on_a_page_past_the_end(
    identified, monkeypatch, capsys
):
    """An empty page past the end must never read as an absence of carriers.

    The precise false negative the exhaustive path exists to remove, and the
    one the CLI shipped: `elif not page.carriers` printed "No document in this
    casefile carries <value>" for any offset past the set, while the same call
    with `--json` reported `total_matching: 2`. The agent surface guarded it and
    the CLI did not, which is why the decision now lives on the page and both
    surfaces read it from there.

    Asserted on the human-readable output of both, because that is where the
    claim is made — the JSON envelope always carried the scalars that
    contradict it.
    """
    context, casefile = identified
    past = len(EXPECTED_CARRIER_ROWS) + 5

    agent = anyio.run(
        call,
        build_mcp_server(context),
        "case_mention_documents",
        {"casefile": casefile.short_id, "mention": PIVOT_VALUE, "offset": past},
    )
    monkeypatch.setattr(cli, "build_context", lambda: context)
    monkeypatch.setattr(context, "close", lambda: None)
    assert (
        cli.main(
            [
                "mention-documents",
                casefile.short_id,
                PIVOT_VALUE,
                "--offset",
                str(past),
            ]
        )
        == 0
    )
    printed = capsys.readouterr().out

    # Both pages really are empty, so the messages below are the empty-set
    # wording rather than a table of rows.
    assert agent["results"] == []
    assert agent["total_matching"] == len(EXPECTED_CARRIER_ROWS)
    assert agent["offset"] == past

    for surface, text in (
        ("the agent payload", agent["formatted"]),
        ("the CLI", printed),
    ):
        assert "No document in this casefile carries" not in text, (
            f"{surface} denies the carriers on a page past the end: {text!r}"
        )
        # And it says how many there really are, so the caller can recover.
        assert str(len(EXPECTED_CARRIER_ROWS)) in text, (
            f"{surface} does not report the real total: {text!r}"
        )
        assert str(past) in text, (
            f"{surface} does not say which offset was empty: {text!r}"
        )


def test_a_carrier_entry_carries_what_reads_and_cites_it(identified):
    """The row's and the payload's key sets, asserted exactly.

    Exactly rather than by containment, for the reason `test_mcp_surface.py`
    records: a renamed key stays truthy and passes every value-by-value
    assertion above. `chunk_id` is the field the whole capability turns on — it
    is what lets a document reached by enumeration be read and cited without a
    ranked search.
    """
    context, casefile = identified
    server = build_mcp_server(context)

    payload = anyio.run(
        call,
        server,
        "case_mention_documents",
        {"casefile": casefile.short_id, "mention": PIVOT_VALUE},
    )

    assert set(payload) == {
        "total",
        "formatted",
        "results",
        "mention",
        "kind",
        "value",
        "offset",
        "total_matching",
        "truncated",
        "continue_from",
        "content_notice",
    }
    for row in payload["results"]:
        assert set(row) == {
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
        assert row["chunk_id"], "a carrier that addresses no passage cannot be cited"


def test_the_enumeration_tool_is_advertised_stamped_taught_and_in_the_role(identified):
    """The same four registration points, for the tool that follows the inventory.

    Same argument as the inventory's own version above: the set-comparison test
    compares `READONLY_TOOLS` with itself, so dropping this tool from it leaves
    that test green and the tool simply gone.
    """
    context, _ = identified

    for profile in sorted(PROFILES):
        server = build_mcp_server(context, profile=profile)
        advertised = {tool.name: tool for tool in anyio.run(server.list_tools)}
        assert "case_mention_documents" in advertised, (
            f"the {profile} profile does not advertise case_mention_documents, so "
            "an agent on it cannot reach every document carrying an identifier"
        )
        stamp = advertised["case_mention_documents"].annotations
        assert stamp is not None, "case_mention_documents is advertised unstamped"
        assert stamp.read_only_hint is True
        assert stamp.destructive_hint is False
        assert stamp.open_world_hint is False, (
            "case_mention_documents reads the local store and reaches nothing "
            "beyond it, so it is closed-world"
        )

    server = build_mcp_server(context)
    assert "case_mention_documents" in (server.instructions or ""), (
        "the surface does not teach the tool, so an agent has to infer the whole "
        "carrier set from a bounded ranking"
    )

    assert "case_mention_documents" in ROLE.read_text(encoding="utf-8"), (
        "the analyst role does not name the tool. Its pivot step is where an "
        "identifier becomes the next question, and stopping at the best-matching "
        "passages is what this tool exists to prevent"
    )


def test_ranked_search_points_at_the_exhaustive_path(identified):
    """What `case_search` says about its own count, and where completeness lives.

    An agent reading `total` as a quantity of evidence is the failure the
    exhaustive path exists to remove, and a tool the agent is never told about
    does not remove it. Read from the advertised description rather than from the
    source, so this is what an agent is actually given.
    """
    context, _ = identified
    server = build_mcp_server(context)
    advertised = {tool.name: tool for tool in anyio.run(server.list_tools)}

    description = advertised["case_search"].description or ""
    assert "case_mention_documents" in description, (
        "ranked search does not name the exhaustive path, so an agent needing "
        "every carrier is left raising the limit"
    )
    assert "returned" in description and "never how many the" in description, (
        "ranked search does not say what its own count counts: "
        f"{description!r}"
    )
