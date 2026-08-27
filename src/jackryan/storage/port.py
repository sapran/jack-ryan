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
class Document:
    """An ingested file: its bytes' identity, and the text recovered from it."""

    id: str
    casefile_id: str
    content_hash: str
    filename: str
    media_type: str
    byte_size: int
    extracted_text: str
    extractor: str
    created_at: datetime
    updated_at: datetime
    # Which rung of the extraction quality gate produced `extracted_text`: the
    # document's own text layer, recognition, a vision model, or direct parsing
    # for a format with no page images. Empty only for a document this codebase
    # did not write. Text recovered by recognition can be fluent and wrong, so
    # this travels with the text all the way to the agent.
    text_source: str = ""
    # Absent for a file ingested directly; set for one found inside another.
    parent_id: str | None = None
    # The names from the ingested file down to this one, joined — including the
    # directories a folder walk passed through. What an analyst follows to find
    # the same evidence by hand. Display, not identity.
    containment_path: str = ""
    # The part of that path which counts toward identity: empty for a file
    # ingested directly, the containment path for one expanded out of a
    # container. Two copies in one folder are one document; the same attachment
    # on two messages is two.
    identity_path: str = ""
    # How many documents were expanded directly out of this one. Carried so a
    # listing can show that there is more to reach without fetching it.
    child_count: int = 0

    @property
    def short_id(self) -> str:
        return self.id[:8]

    @property
    def is_expanded(self) -> bool:
        """Whether this document came out of another rather than off disk."""
        return self.parent_id is not None


@dataclass(frozen=True)
class Chunk:
    """A retrievable span of a document, locatable in its extracted text."""

    id: str
    document_id: str
    casefile_id: str
    ordinal: int
    heading_path: str
    text: str
    char_start: int
    char_end: int

    @property
    def short_id(self) -> str:
        return self.id[:8]


@dataclass(frozen=True)
class SearchHit:
    """One ranked result, carrying what is needed to use and to verify it."""

    chunk: Chunk
    document: Document
    score: float
    keyword_rank: int | None
    vector_rank: int | None


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

    def initialize(self, contract_fingerprint: str, embed_dimensions: int) -> None:
        """Create or open the store, and verify it matches the contract.

        Raises if the store on disk was built under a different contract: a
        corpus is only appendable under the rules that created it. The vector
        index is sized from the contract, which is why the width is needed here.
        """
        ...

    def create_casefile(self, casefile: Casefile) -> Casefile: ...

    def get_casefile(self, casefile_id: str) -> Casefile | None: ...

    def get_casefile_by_slug(self, slug: str) -> Casefile | None: ...

    def find_casefiles_by_id_prefix(self, prefix: str) -> list[Casefile]: ...

    def list_casefiles(self) -> list[Casefile]: ...

    def update_casefile(self, casefile: Casefile) -> Casefile: ...

    def delete_casefile(self, casefile_id: str) -> bool: ...

    # -- documents and chunks ---------------------------------------------

    def upsert_document(self, document: Document) -> Document:
        """Store a document, reusing the identifier of one with the same bytes."""
        ...

    def get_document(self, document_id: str) -> Document | None: ...

    def find_document_by_hash(
        self, casefile_id: str, content_hash: str, identity_path: str = ""
    ) -> Document | None: ...

    def delete_document(self, document_id: str) -> bool: ...

    def list_children(self, document_id: str) -> list[Document]: ...

    def ancestors(self, document_id: str) -> list[Document]: ...

    def descendant_ids(self, document_id: str) -> list[str]: ...

    def find_documents_by_id_prefix(self, casefile_id: str, prefix: str) -> list[Document]: ...

    def list_documents(
        self, casefile_id: str, include_expanded: bool = False
    ) -> list[Document]: ...

    def replace_chunks(
        self, document_id: str, chunks: list[Chunk], embeddings: list[list[float]]
    ) -> None:
        """Replace a document's chunks and their vectors in one transaction."""
        ...

    def find_chunks_by_id_prefix(self, casefile_id: str, prefix: str) -> list[Chunk]: ...

    def casefile_statistics(self, casefile_id: str) -> dict[str, object]: ...

    def get_document_chunks_around(
        self, document_id: str, ordinal: int, radius: int
    ) -> list[Chunk]: ...

    def search_keyword(self, casefile_id: str, query: str, limit: int) -> list[str]: ...

    def search_vector(
        self, casefile_id: str, embedding: list[float], limit: int
    ) -> list[str]: ...

    def get_chunks(self, chunk_ids: list[str]) -> dict[str, Chunk]: ...

    def close(self) -> None: ...
