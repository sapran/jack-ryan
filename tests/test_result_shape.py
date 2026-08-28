"""What a search result says about itself, on all three surfaces.

A result's text may now be wider than the passage that matched it, so a result
carries two spans: the one it returned and the one it matched. Every adapter has
to report the same two, because an analyst reading the REST output and an agent
reading the MCP payload are looking at one fact.
"""

from __future__ import annotations

import json

import anyio
import pytest

from jackryan import cli
from jackryan.interfaces.mcp import build_mcp_server
from jackryan.server import serialize_hit

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
