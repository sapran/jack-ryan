"""The embedding boundary.

Document and query embedding are separate operations because some models —
including the default — expect asymmetric prefixes, and applying them is the
embedder's job rather than every caller's.
"""

from __future__ import annotations

from typing import Protocol

from ..errors import JackRyanError


class EmbeddingError(JackRyanError):
    """The configured embedder could not be loaded or could not embed."""

    code = "embedding_failed"


class EmbedderPort(Protocol):
    name: str

    @property
    def dimensions(self) -> int:
        """The width of every vector this embedder produces."""
        ...

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed passages for storage."""
        ...

    def embed_query(self, text: str) -> list[float]:
        """Embed a question for retrieval."""
        ...
