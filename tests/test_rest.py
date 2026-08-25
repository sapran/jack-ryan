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
    assert body["contract"] == context.config.contract.fingerprint()


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
