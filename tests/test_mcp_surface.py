"""The agent-facing surface: shape, chaining, bounds, and typed failures."""

from __future__ import annotations

import json

import pytest

from jackryan.errors import NotFoundError
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


@pytest.mark.anyio
async def test_every_advertised_tool_still_declares_its_parameters(server):
    """One translation for every tool must not cost the tools their signatures.

    The SDK builds each advertised input schema from the tool function's
    signature and reaches the real one through `__wrapped__`, so a decorator
    applied without `functools.wraps` leaves every tool advertising the
    wrapper's own `*args, **kwargs` — two parameters named `args` and `kwargs`,
    both required, in place of the tool's real ones. Every call then fails for
    missing required arguments.

    The pre-existing tests do notice that, loudly, because they call tools with
    real arguments. What they cannot say is *which* tool lost its schema or what
    it advertises instead, and they say nothing at all about the one tool
    nothing here calls. This names both.

    `required` is asserted beside the names because they answer different
    questions: giving `query` a default would leave the names unchanged and let
    an agent search with no query at all.
    """
    tools = {tool.name: tool for tool in await server.list_tools()}
    expected = {
        "case_list_casefiles": (set(), []),
        "case_casefile_overview": ({"casefile"}, ["casefile"]),
        "case_list_documents": ({"casefile"}, ["casefile"]),
        "case_search": ({"casefile", "query", "limit", "mention"}, ["casefile", "query"]),
        "case_mentions": ({"casefile", "kind", "limit"}, ["casefile"]),
        "case_get_passage": ({"casefile", "chunk_id"}, ["casefile", "chunk_id"]),
        "case_read_document": (
            {"casefile", "document", "offset", "limit"},
            ["casefile", "document"],
        ),
        "case_cite": ({"casefile", "chunk_id"}, ["casefile", "chunk_id"]),
    }
    assert set(tools) == set(expected), "the advertised set changed"
    for name, (parameters, required) in expected.items():
        schema = tools[name].input_schema
        declared = set(schema.get("properties", {}))
        assert declared == parameters, f"{name} advertises {declared or 'nothing'}"
        assert sorted(schema.get("required", [])) == sorted(required), (
            f"{name} requires {schema.get('required')}"
        )


@pytest.mark.anyio
async def test_every_tool_inherits_the_one_translation(server):
    """A tool is covered by being decorated, so check that each one is.

    This is the scenario `service-adapter-boundary` asks for: every tool
    translates a typed error through the same single translation, so a tool
    added without restating it still returns a typed payload.

    It needs asserting directly because the failure is silent. Applying the
    decorator *above* `@server.tool(...)` rather than below registers the
    undecorated function: the translation is still written, still reads
    correctly at the call site, and simply never runs. Done to a tool nothing
    else here calls, the whole suite stays green — which is exactly what
    happened when it was tried.

    `is_async` is the SDK's own record of what it will do with the function. A
    synchronous wrapper is registered as a plain function and run in a worker
    thread, which hands the caller an un-awaited coroutine.
    """
    # The same coupling `_defined_tool_names` isolates: the SDK's only
    # synchronous listing lives on the tool manager.
    registered = server._tool_manager.list_tools()  # noqa: SLF001
    assert registered, "no tools were registered"
    for tool in registered:
        assert getattr(tool.fn, "__wrapped__", None) is not None, (
            f"{tool.name} was registered undecorated, so its failures never reach "
            "the one translation"
        )
        assert tool.is_async, f"{tool.name} was registered as a synchronous tool"


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
async def test_the_overview_reports_the_corpus_it_was_asked_about(server, loaded):
    """The one call that tells an agent how big a casefile is.

    Nothing exercised this tool before. That matters more than it sounds:
    `case_casefile_overview` is where the surface states corpus size, and
    `CLAUDE.md` notes an agent then repeats that as coverage. A wrong figure
    here is not a wrong number, it is a false coverage claim.

    The key set is asserted exactly rather than key by key, because the failure
    this guards against is a *renamed* key, not a missing value. The store's SQL
    aliases these columns `ingested` and `expanded` while the payload calls them
    `documents_ingested` and `documents_expanded`; anything carrying the alias
    outward would still be truthy, still be counted, and quietly change the
    agent-facing contract.
    """
    context, casefile = loaded
    body = await call(server, "case_casefile_overview", {"casefile": casefile.short_id})

    assert set(body) == {
        "casefile",
        "document_count",
        "documents_ingested",
        "documents_expanded",
        "total_characters",
        "documents_by_type",
        "formatted",
    }

    documents = context.ingestion.list_documents(casefile.short_id)
    assert body["document_count"] == len(documents) == 3
    # The `corpus` fixture is three files on disk, so every document was
    # ingested directly and none came out of a container.
    assert body["documents_ingested"] == 3
    assert body["documents_expanded"] == 0
    assert body["total_characters"] == sum(len(d.extracted_text) for d in documents)
    assert sum(body["documents_by_type"].values()) == 3

    assert body["casefile"]["slug"] == casefile.slug
    assert "3 documents" in body["formatted"]
    # The expansion clause appears only when something was expanded; saying
    # "0 expanded from containers" for a plain folder is noise an agent repeats.
    assert "expanded from containers" not in body["formatted"]


@pytest.mark.anyio
async def test_search_separates_index_from_bodies(server):
    body = await call(server, "case_search", {"casefile": "harbour-inquiry", "query": "harbour lease"})
    assert body["formatted"]
    assert body["results"]
    nonce = body["fence_nonce"]
    for result in body["results"]:
        # Compare the *unfenced* body: comparing the fenced string would pass
        # trivially, since the fence wrapper never appears in the index.
        inner = result["text"]
        inner = inner[len(f"<<<UNTRUSTED {nonce}") : -len(f"{nonce} UNTRUSTED>>>")].strip()
        assert inner
        assert inner not in body["formatted"]
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


@pytest.mark.anyio
async def test_a_typed_failure_after_the_opening_calls_is_still_a_payload(
    server, loaded, monkeypatch
):
    """A tool returns a payload however far through its work it fails.

    `mcp-tool-surface` says a tool SHALL NOT raise. `case_get_passage` asks the
    service for a window *after* resolving the passage, and that call used to
    sit outside the tool's own `try` — so a typed failure from it left the tool
    as an exception, which an agent can only retry rather than branch on.

    Reached through the real service object the server closed over, so this
    exercises the tool's whole body rather than a re-implementation of it.
    """
    context, casefile = loaded

    def refuses(*_args, **_kwargs):
        raise NotFoundError("the passage window went away")

    hits = await call(
        server, "case_search", {"casefile": casefile.short_id, "query": "harbour lease"}
    )
    chunk_id = hits["results"][0]["chunk_id"]
    monkeypatch.setattr(context.search, "passage_window", refuses)

    body = await call(
        server, "case_get_passage", {"casefile": casefile.short_id, "chunk_id": chunk_id}
    )
    assert body["error"] == "not_found"
    assert "the passage window went away" in body["message"]


@pytest.mark.anyio
async def test_a_passage_declares_the_span_of_everything_it_returns(
    context, sectioned_corpus
):
    """The payload's position must cover the text beside it.

    This tool used to return a passage together with its neighbouring chunks
    while its provenance described only the passage — a declared position that
    covered less than the payload carried, which cannot be checked against the
    source by hand.
    """
    casefile = context.casefiles.create("Spans")
    context.ingestion.ingest(casefile.short_id, sectioned_corpus)
    server = build_mcp_server(context)
    # One hit, so the passage has unmatched neighbours to grow into.
    hits = await call(
        server,
        "case_search",
        {"casefile": casefile.short_id, "query": "cormorant", "limit": 1},
    )
    top = hits["results"][0]

    passage = await call(
        server,
        "case_get_passage",
        {"casefile": casefile.short_id, "chunk_id": top["chunk_id"]},
    )

    document = context.ingestion.resolve_document(casefile.short_id, passage["document_id"])
    body = passage["text"].split("\n", 1)[1].rsplit("\n", 1)[0]
    declared = document.extracted_text[passage["char_start"] : passage["char_end"]]
    assert body == declared

    matched = passage["provenance"].get("matched")
    assert matched is not None, "nothing was widened, so this test says nothing"
    assert matched["chunk_id"] == passage["chunk_id"]
    assert passage["char_start"] <= matched["char_start"]
    assert passage["char_end"] >= matched["char_end"]
    assert (passage["char_start"], passage["char_end"]) != (
        matched["char_start"],
        matched["char_end"],
    )


@pytest.mark.anyio
async def test_a_passage_body_appears_once(loaded):
    """No second copy of the passage arrives as a neighbour."""
    context, casefile = loaded
    server = build_mcp_server(context)
    hits = await call(
        server, "case_search", {"casefile": casefile.short_id, "query": "harbour lease"}
    )
    passage = await call(
        server,
        "case_get_passage",
        {"casefile": casefile.short_id, "chunk_id": hits["results"][0]["chunk_id"]},
    )
    assert "neighbours" not in passage
    assert passage["text"].count("<<<UNTRUSTED") == 1


@pytest.mark.anyio
async def test_a_citation_of_a_widened_result_still_quotes_the_passage(
    context, sectioned_corpus
):
    """Widening what is read must not widen what is quoted.

    Every other citation test runs on results that were never widened, where a
    citation of the window and a citation of the passage are the same string.
    """
    casefile = context.casefiles.create("Cited")
    context.ingestion.ingest(casefile.short_id, sectioned_corpus)
    server = build_mcp_server(context)

    hits = await call(
        server,
        "case_search",
        {"casefile": casefile.short_id, "query": "cormorant", "limit": 1},
    )
    result = hits["results"][0]
    assert "matched" in result["provenance"], "the result was not widened"
    matched = result["provenance"]["matched"]

    citation = await call(
        server,
        "case_cite",
        {"casefile": casefile.short_id, "chunk_id": result["chunk_id"]},
    )

    # The citation names the passage's span, not the wider one that was read.
    assert citation["char_start"] == matched["char_start"]
    assert citation["char_end"] == matched["char_end"]
    assert (citation["char_start"], citation["char_end"]) != (
        result["char_start"],
        result["char_end"],
    )
    quoted = citation["quote"].split("\n", 1)[1].rsplit("\n", 1)[0]
    body = result["text"].split("\n", 1)[1].rsplit("\n", 1)[0]
    assert quoted in body and quoted != body
