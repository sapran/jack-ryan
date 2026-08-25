"""The storage seam.

Every persistence call in the service layer goes through ``StorePort``. This
is the one deliberate abstraction in the system: it exists so a heavier engine
can replace the embedded store later without the service layer noticing.

The port speaks in domain objects, never in rows or SQL, and it performs no
validation — rules belong in the service layer so that every adapter inherits
them.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True)
class Casefile:
    """The unit of scoping, provenance, and later access control."""

    id: str
    slug: str
    title: str
    description: str
    created_at: datetime
    updated_at: datetime

    @property
    def short_id(self) -> str:
        """The 8-character prefix used as a handle across every surface."""
        return self.id[:8]


class StorePort(Protocol):
    """What the service layer requires of a store."""

    def initialize(self, contract_fingerprint: str) -> None:
        """Create or open the store, and verify it matches the contract.

        Raises if the store on disk was built under a different contract: a
        corpus is only appendable under the rules that created it.
        """
        ...

    def create_casefile(self, casefile: Casefile) -> Casefile: ...

    def get_casefile(self, casefile_id: str) -> Casefile | None: ...

    def get_casefile_by_slug(self, slug: str) -> Casefile | None: ...

    def find_casefiles_by_id_prefix(self, prefix: str) -> list[Casefile]: ...

    def list_casefiles(self) -> list[Casefile]: ...

    def update_casefile(self, casefile: Casefile) -> Casefile: ...

    def delete_casefile(self, casefile_id: str) -> bool: ...

    def close(self) -> None: ...
