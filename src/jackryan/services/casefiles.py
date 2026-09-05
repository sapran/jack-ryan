"""Casefile business logic.

Every rule about what a casefile is lives here rather than in an adapter, so
REST, CLI, and later MCP all inherit the same validation and the same
reference-resolution behaviour. An adapter that skipped this layer would be a
second, divergent definition of the domain.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone

from ..errors import AmbiguousReferenceError, NotFoundError, ValidationError
from ..storage.port import Casefile, CasefileStatistics, StorePort

SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
SHORT_ID_LENGTH = 8
MAX_TITLE_LENGTH = 200
MAX_DESCRIPTION_LENGTH = 2000
MAX_SLUG_LENGTH = 64


def _now() -> datetime:
    return datetime.now(timezone.utc)


def slugify(title: str) -> str:
    """Derive a slug from a title.

    Kept deliberately conservative: lowercase, ASCII alphanumerics, single
    hyphens. A slug is a handle people type, so predictability beats fidelity.
    """
    lowered = title.strip().lower()
    slug = re.sub(r"[^a-z0-9]+", "-", lowered).strip("-")
    return slug[:MAX_SLUG_LENGTH].strip("-")


class CasefileService:
    """Create, read, update, and delete casefiles."""

    def __init__(self, store: StorePort) -> None:
        self._store = store

    # -- validation --------------------------------------------------------

    def _validate_title(self, title: str) -> str:
        cleaned = title.strip()
        if not cleaned:
            raise ValidationError("title must not be empty")
        if len(cleaned) > MAX_TITLE_LENGTH:
            raise ValidationError(f"title must be at most {MAX_TITLE_LENGTH} characters")
        return cleaned

    def _validate_description(self, description: str) -> str:
        cleaned = (description or "").strip()
        if len(cleaned) > MAX_DESCRIPTION_LENGTH:
            raise ValidationError(
                f"description must be at most {MAX_DESCRIPTION_LENGTH} characters"
            )
        return cleaned

    def _validate_slug(self, slug: str) -> str:
        cleaned = slug.strip().lower()
        if not cleaned:
            raise ValidationError("slug must not be empty")
        if len(cleaned) > MAX_SLUG_LENGTH:
            raise ValidationError(f"slug must be at most {MAX_SLUG_LENGTH} characters")
        if not SLUG_PATTERN.match(cleaned):
            raise ValidationError(
                "slug must be lowercase alphanumerics separated by single hyphens"
            )
        return cleaned

    # -- commands ----------------------------------------------------------

    def create(self, title: str, description: str = "", slug: str | None = None) -> Casefile:
        title = self._validate_title(title)
        description = self._validate_description(description)
        candidate = self._validate_slug(slug) if slug else slugify(title)
        if not candidate:
            raise ValidationError(
                "could not derive a slug from that title; supply one explicitly"
            )

        now = _now()
        casefile = Casefile(
            id=uuid.uuid4().hex,
            slug=candidate,
            title=title,
            description=description,
            created_at=now,
            updated_at=now,
        )
        return self._store.create_casefile(casefile)

    def update(
        self,
        reference: str,
        *,
        title: str | None = None,
        description: str | None = None,
        slug: str | None = None,
    ) -> Casefile:
        existing = self.resolve(reference)
        updated = Casefile(
            id=existing.id,
            slug=self._validate_slug(slug) if slug is not None else existing.slug,
            title=self._validate_title(title) if title is not None else existing.title,
            description=(
                self._validate_description(description)
                if description is not None
                else existing.description
            ),
            created_at=existing.created_at,
            updated_at=_now(),
        )
        return self._store.update_casefile(updated)

    def delete(self, reference: str) -> Casefile:
        existing = self.resolve(reference)
        self._store.delete_casefile(existing.id)
        return existing

    # -- queries -----------------------------------------------------------

    def list(self) -> list[Casefile]:
        return self._store.list_casefiles()

    def statistics(self, reference: str) -> CasefileStatistics:
        """The size and shape of one casefile, by any handle that names it.

        Here rather than reached for directly by a surface, because resolving a
        reference is a domain rule and `storage-seam` says no adapter reaches a
        store. Until this existed the agent surface was the only caller of
        `casefile_statistics`, and it held the store to make the call — the one
        place in the codebase where an adapter did.

        Takes a reference and resolves it, like every other query here, so a
        caller needs no id it did not already have.
        """
        casefile = self.resolve(reference)
        return self._store.casefile_statistics(casefile.id)

    def resolve(self, reference: str) -> Casefile:
        """Resolve a casefile from a full id, an 8-char id prefix, or a slug.

        Short-prefix handles are the convention across every surface, so the
        resolution rule lives here once. An ambiguous prefix is an error rather
        than a silent first-match: picking one would hand back the wrong
        casefile with no signal that a choice was made.
        """
        candidate = (reference or "").strip()
        if not candidate:
            raise ValidationError("a casefile reference is required")

        exact = self._store.get_casefile(candidate)
        if exact is not None:
            return exact

        by_slug = self._store.get_casefile_by_slug(candidate.lower())
        if by_slug is not None:
            return by_slug

        if len(candidate) >= SHORT_ID_LENGTH:
            matches = self._store.find_casefiles_by_id_prefix(candidate)
            if len(matches) == 1:
                return matches[0]
            if len(matches) > 1:
                shown = ", ".join(m.short_id for m in matches[:5])
                raise AmbiguousReferenceError(
                    f"{candidate!r} matches {len(matches)} casefiles ({shown}); "
                    "use the full id"
                )

        raise NotFoundError(f"no casefile matches {reference!r}")
