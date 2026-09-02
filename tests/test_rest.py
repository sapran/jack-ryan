"""The REST layer is a translation surface: it maps typed service errors onto
status codes and adds no rule of its own."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from jackryan.server import create_app


@pytest.fixture
def client(context):
    with TestClient(create_app(context)) as test_client:
        yield test_client


def test_health_reports_profile_and_contract(client, context):
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert body["profile"] == context.config.profile.name
    # The value the store enforces, not the contract alone. An operator holding
    # a refusal has to be able to compare it against what /health showed them;
    # reporting a string that guards nothing sends them after the wrong
    # difference.
    assert body["contract"] == context.corpus_fingerprint
    assert body["contract"] != context.config.contract.fingerprint(), (
        "corpus identity must be more than the contract, or the embedder is unrecorded"
    )


def test_both_surfaces_report_one_archive_reader(client, context, monkeypatch, capsys):
    """One answer about the host, whichever surface is asked.

    Surface against surface, not each against the function they both call. The
    second shape is what stood here, and it could not fail in the way the name
    promises: a second definition introduced into one adapter would still agree
    with `rar_status()` read through the other. So both adapters are asked, and
    the vocabulary is pinned as well as the value — a version, or the one
    literal, and nothing else.
    """
    import json

    from jackryan import cli
    from jackryan.ingestion.containers import RAR_UNAVAILABLE

    monkeypatch.setattr(cli, "build_context", lambda: context)
    monkeypatch.setattr(context, "close", lambda: None)

    body = client.get("/health").json()
    assert cli.main(["--json", "status"]) == 0
    reported = json.loads(capsys.readouterr().out)

    assert body["rar"] == reported["rar"]
    assert body["rar"] == RAR_UNAVAILABLE or body["rar"].count(".") == 2, (
        "the reported reader is a dotted version or the one unavailable literal"
    )


def test_create_and_fetch_a_casefile(client):
    created = client.post("/api/casefiles", json={"title": "Harbour Leases"})
    assert created.status_code == 201
    body = created.json()
    assert body["slug"] == "harbour-leases"

    fetched = client.get(f"/api/casefiles/{body['short_id']}")
    assert fetched.status_code == 200
    assert fetched.json()["id"] == body["id"]


def test_listing_reports_a_total(client):
    client.post("/api/casefiles", json={"title": "One"})
    client.post("/api/casefiles", json={"title": "Two"})
    body = client.get("/api/casefiles").json()
    assert body["total"] == 2
    assert len(body["casefiles"]) == 2


def test_invalid_input_is_a_400(client):
    response = client.post("/api/casefiles", json={"title": "Valid", "slug": "Not A Slug"})
    assert response.status_code == 400
    assert response.json()["error"] == "validation_error"


def test_duplicate_slug_is_a_409(client):
    client.post("/api/casefiles", json={"title": "First", "slug": "shared"})
    response = client.post("/api/casefiles", json={"title": "Second", "slug": "shared"})
    assert response.status_code == 409
    assert response.json()["error"] == "conflict"


def test_unknown_casefile_is_a_404(client):
    response = client.get("/api/casefiles/does-not-exist")
    assert response.status_code == 404
    assert response.json()["error"] == "not_found"


def test_update_and_delete_round_trip(client):
    created = client.post("/api/casefiles", json={"title": "Draft"}).json()

    updated = client.patch(f"/api/casefiles/{created['slug']}", json={"title": "Final"})
    assert updated.status_code == 200
    assert updated.json()["title"] == "Final"

    deleted = client.delete(f"/api/casefiles/{created['id']}")
    assert deleted.status_code == 200
    assert deleted.json()["deleted"]["id"] == created["id"]
    assert client.get("/api/casefiles").json()["total"] == 0


# -- M1: ingest, documents, search ---------------------------------------


def test_ingest_then_list_documents(client, corpus):
    created = client.post("/api/casefiles", json={"title": "Harbour Inquiry"}).json()

    ingested = client.post(
        f"/api/casefiles/{created['short_id']}/ingest", json={"path": str(corpus)}
    )
    assert ingested.status_code == 200
    assert ingested.json()["ingested"] == 3
    assert ingested.json()["failed"] == 0

    listed = client.get(f"/api/casefiles/{created['short_id']}/documents").json()
    assert listed["total"] == 3
    assert {d["filename"] for d in listed["documents"]} == {"lease.md", "minutes.md", "notes.txt"}


def test_search_returns_ranked_results(client, corpus):
    created = client.post("/api/casefiles", json={"title": "Harbour Inquiry"}).json()
    client.post(f"/api/casefiles/{created['short_id']}/ingest", json={"path": str(corpus)})

    body = client.get(
        f"/api/casefiles/{created['short_id']}/search", params={"q": "harbour lease Northgate"}
    ).json()
    assert body["total"] > 0
    top = body["results"][0]
    assert top["document"] == "lease.md"
    assert top["chunk_id"] and top["document_id"]
    assert "text" in top


def test_search_on_an_unknown_casefile_is_a_404(client):
    response = client.get("/api/casefiles/no-such-case/search", params={"q": "anything"})
    assert response.status_code == 404


def test_an_empty_query_is_a_400(client, corpus):
    created = client.post("/api/casefiles", json={"title": "Harbour Inquiry"}).json()
    response = client.get(f"/api/casefiles/{created['short_id']}/search", params={"q": "  "})
    assert response.status_code == 400
    assert response.json()["error"] == "validation_error"


def test_fetching_a_document_by_short_id(client, corpus):
    created = client.post("/api/casefiles", json={"title": "Harbour Inquiry"}).json()
    client.post(f"/api/casefiles/{created['short_id']}/ingest", json={"path": str(corpus)})
    document = client.get(f"/api/casefiles/{created['short_id']}/documents").json()["documents"][0]

    fetched = client.get(
        f"/api/casefiles/{created['short_id']}/documents/{document['short_id']}"
    )
    assert fetched.status_code == 200
    assert fetched.json()["id"] == document["id"]


def test_search_reports_both_spans_and_what_ranked_it(client, context, corpus):
    casefile = context.casefiles.create("Spans Over Http")
    context.ingestion.ingest(casefile.short_id, corpus)

    body = client.get(
        f"/api/casefiles/{casefile.short_id}/search", params={"q": "harbour lease"}
    ).json()

    assert body["ranking"] == "fusion"
    assert body["results"]
    for row in body["results"]:
        # The span of what was returned, and the passage inside it that matched.
        assert row["char_start"] <= row["matched_char_start"]
        assert row["char_end"] >= row["matched_char_end"]
        # A person reading a hit is told how its text was obtained, exactly as
        # the agent surface is.
        assert row["read_as"]
        assert row["rerank_score"] is None
