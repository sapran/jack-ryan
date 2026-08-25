"""Casefile rules live in the service layer so every adapter inherits them."""

from __future__ import annotations

import pytest

from jackryan.errors import (
    AmbiguousReferenceError,
    ConflictError,
    NotFoundError,
    ValidationError,
)
from jackryan.services.casefiles import slugify


def test_create_derives_a_slug_from_the_title(service):
    casefile = service.create("Port Authority Contracts 2021")
    assert casefile.slug == "port-authority-contracts-2021"
    assert casefile.short_id == casefile.id[:8]


def test_explicit_slug_is_honoured(service):
    assert service.create("Anything", slug="my-handle").slug == "my-handle"


@pytest.mark.parametrize("bad", ["Has Spaces", "double--hyphen", "-leading", "trailing-", "under_score"])
def test_malformed_slug_is_rejected(service, bad):
    with pytest.raises(ValidationError):
        service.create("Title", slug=bad)


def test_slug_case_is_normalised_rather_than_rejected(service):
    # A handle typed in mixed case is a typo worth absorbing, not an error:
    # it has exactly one sensible interpretation.
    assert service.create("Title", slug="MixedCase").slug == "mixedcase"


def test_duplicate_slug_is_a_conflict(service):
    service.create("First", slug="shared")
    with pytest.raises(ConflictError):
        service.create("Second", slug="shared")


def test_empty_title_is_rejected(service):
    with pytest.raises(ValidationError):
        service.create("   ")


def test_title_that_yields_no_slug_asks_for_one(service):
    with pytest.raises(ValidationError, match="supply one explicitly"):
        service.create("!!!")


def test_resolve_accepts_full_id_short_id_and_slug(service):
    created = service.create("Shell Companies", slug="shells")
    assert service.resolve(created.id).id == created.id
    assert service.resolve(created.short_id).id == created.id
    assert service.resolve("shells").id == created.id


def test_resolve_rejects_an_unknown_reference(service):
    with pytest.raises(NotFoundError):
        service.resolve("nothing-here")


def test_resolve_requires_a_reference(service):
    with pytest.raises(ValidationError):
        service.resolve("")


def test_ambiguous_short_id_is_an_error_not_a_guess(service, monkeypatch):
    a = service.create("Alpha", slug="alpha")
    b = service.create("Beta", slug="beta")
    # Force a collision rather than hunting for one: what matters is that two
    # matches refuse to resolve, not how likely a real collision is.
    monkeypatch.setattr(service._store, "find_casefiles_by_id_prefix", lambda prefix: [a, b])
    with pytest.raises(AmbiguousReferenceError, match="matches 2 casefiles"):
        service.resolve("abcdef12")


def test_update_changes_fields_and_bumps_the_timestamp(service):
    created = service.create("Original", slug="original")
    updated = service.update(created.short_id, title="Renamed", description="Now with context")
    assert updated.title == "Renamed"
    assert updated.description == "Now with context"
    assert updated.slug == "original"
    assert updated.created_at == created.created_at
    assert updated.updated_at >= created.updated_at


def test_delete_removes_the_casefile(service):
    created = service.create("Temporary", slug="temp")
    service.delete("temp")
    assert service.list() == []
    with pytest.raises(NotFoundError):
        service.resolve(created.id)


def test_list_is_newest_first(service):
    service.create("One", slug="one")
    service.create("Two", slug="two")
    assert [c.slug for c in service.list()] == ["two", "one"]


@pytest.mark.parametrize(
    "title,expected",
    [
        ("Simple Title", "simple-title"),
        ("  Padded  ", "padded"),
        ("Mixed 123 Case", "mixed-123-case"),
        ("Punctuation!!! Here?", "punctuation-here"),
    ],
)
def test_slugify(title, expected):
    assert slugify(title) == expected
