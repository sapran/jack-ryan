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
    from jackryan.services.search import MAX_RESPONSE_CHARS

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
