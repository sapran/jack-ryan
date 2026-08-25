"""The agent-facing surface: shape, chaining, bounds, and typed failures."""

from __future__ import annotations

import json

import pytest

from jackryan.interfaces.mcp import build_mcp_server
from jackryan.interfaces.mcp.annotations import ANNOTATIONS, UnstampedToolError, stamp_for
from jackryan.interfaces.mcp.profiles import READONLY_TOOLS, tools_for_profile


@pytest.fixture
def loaded(context, corpus):
    casefile = context.casefiles.create("Harbour Inquiry")
    context.ingestion.ingest(casefile.short_id, corpus)
    return context, casefile


@pytest.fixture
def server(loaded):
    context, _ = loaded
    return build_mcp_server(context)


async def call(server, name, args=None):
    result = await server.call_tool(name, args or {})
    return json.loads(result.content[0].text)


# -- the surface ------------------------------------------------------------


@pytest.mark.anyio
async def test_every_advertised_tool_is_namespaced_and_stamped(server):
    tools = await server.list_tools()
    assert tools
    for tool in tools:
        assert tool.name.startswith("case_")
        assert tool.annotations is not None
        assert tool.annotations.read_only_hint is True


@pytest.mark.anyio
async def test_the_surface_teaches_the_method(server):
    instructions = server.instructions or ""
    for expected in ("case_list_casefiles", "case_search", "case_cite", "coverage"):
        assert expected in instructions
    # It must say what the fence means, not merely apply it.
    assert "never instructions" in instructions or "not instructions" in instructions


def test_a_tool_missing_from_the_annotations_table_is_a_failure():
    with pytest.raises(UnstampedToolError):
        stamp_for("case_not_declared")


def test_every_advertised_tool_is_in_the_annotations_table():
    assert READONLY_TOOLS <= set(ANNOTATIONS)


# -- profiles ---------------------------------------------------------------


@pytest.mark.anyio
async def test_only_the_profiles_tools_are_advertised(context):
    server = build_mcp_server(context, profile="readonly")
    assert {t.name for t in await server.list_tools()} == set(READONLY_TOOLS)


@pytest.mark.anyio
async def test_an_unrecognised_profile_narrows_rather_than_widens(context):
    server = build_mcp_server(context, profile="not-a-real-profile")
    assert {t.name for t in await server.list_tools()} == set(READONLY_TOOLS)
    assert tools_for_profile("not-a-real-profile") == tools_for_profile("readonly")


# -- return shape and chaining ---------------------------------------------


@pytest.mark.anyio
async def test_search_separates_index_from_bodies(server):
    body = await call(server, "case_search", {"casefile": "harbour-inquiry", "query": "harbour lease"})
    assert body["formatted"]
    assert body["results"]
    for result in body["results"]:
        # The body appears once, under `text`, and the index carries no prose.
        assert result["text"] not in body["formatted"]
        assert result["chunk_id"] and result["document_id"]


@pytest.mark.anyio
async def test_identifiers_chain_from_search_into_every_tool_that_takes_them(server):
    found = await call(
        server, "case_search", {"casefile": "harbour-inquiry", "query": "harbour lease Northgate"}
    )
    top = found["results"][0]

    passage = await call(
        server, "case_get_passage", {"casefile": "harbour-inquiry", "chunk_id": top["chunk_id"]}
    )
    assert passage["chunk_id"] == top["chunk_id"]

    citation = await call(
        server, "case_cite", {"casefile": "harbour-inquiry", "chunk_id": top["chunk_id"]}
    )
    assert citation["document_id"] == top["document_id"]

    document = await call(
        server, "case_read_document", {"casefile": "harbour-inquiry", "document": top["document_id"]}
    )
    assert document["document_id"] == top["document_id"]


@pytest.mark.anyio
async def test_a_citation_resolves_to_a_real_span(server, loaded):
    context, casefile = loaded
    found = await call(server, "case_search", {"casefile": casefile.short_id, "query": "harbour lease"})
    top = found["results"][0]
    citation = await call(
        server, "case_cite", {"casefile": casefile.short_id, "chunk_id": top["chunk_id"]}
    )

    document = context.ingestion.resolve_document(casefile.short_id, citation["document_id"])
    span = document.extracted_text[citation["char_start"] : citation["char_end"]]
    assert span.strip()
    assert span.strip() in citation["quote"]


# -- bounds -----------------------------------------------------------------


@pytest.mark.anyio
async def test_a_truncated_read_says_so_and_where_to_continue(server):
    first = await call(
        server,
        "case_read_document",
        {"casefile": "harbour-inquiry", "document": (
            (await call(server, "case_list_documents", {"casefile": "harbour-inquiry"}))["results"][0]["document_id"]
        ), "limit": 20},
    )
    assert first["truncated"] is True
    assert first["continue_from"] == first["char_end"]

    rest = await call(
        server,
        "case_read_document",
        {
            "casefile": "harbour-inquiry",
            "document": first["document_id"],
            "offset": first["continue_from"],
        },
    )
    assert rest["char_start"] == first["continue_from"]


@pytest.mark.anyio
async def test_a_complete_read_is_not_marked_truncated(server):
    documents = await call(server, "case_list_documents", {"casefile": "harbour-inquiry"})
    body = await call(
        server,
        "case_read_document",
        {"casefile": "harbour-inquiry", "document": documents["results"][0]["document_id"]},
    )
    assert body["truncated"] is False
    assert body["continue_from"] is None


@pytest.mark.anyio
async def test_an_over_large_limit_is_clamped_not_refused(server):
    body = await call(
        server, "case_search", {"casefile": "harbour-inquiry", "query": "the", "limit": 100_000}
    )
    assert "error" not in body
    assert body["total"] <= 50


# -- failures ---------------------------------------------------------------


@pytest.mark.anyio
async def test_an_unknown_casefile_returns_a_typed_payload_not_an_exception(server):
    body = await call(server, "case_search", {"casefile": "no-such-case", "query": "anything"})
    assert body["error"] == "not_found"
    assert "no-such-case" in body["message"]


@pytest.mark.anyio
async def test_a_passage_from_another_casefile_is_not_reachable(server, context, corpus):
    other = context.casefiles.create("Other Matter")
    context.ingestion.ingest(other.short_id, corpus / "lease.md")
    theirs = await call(server, "case_search", {"casefile": other.short_id, "query": "harbour"})
    stolen = theirs["results"][0]["chunk_id"]

    body = await call(
        server, "case_get_passage", {"casefile": "harbour-inquiry", "chunk_id": stolen}
    )
    assert body["error"] == "not_found"
