"""The real embedder: an ONNX sentence model, loaded lazily.

The model is downloaded on first use and cached, so a first run needs network
access while every later one does not. An image that pre-fetches the weights is
offline from its first run.
"""

from __future__ import annotations

from .port import EmbeddingError

# The e5 family is trained with asymmetric prefixes; omitting them measurably
# degrades retrieval, so they are applied here where the model is known.
_PASSAGE_PREFIX = "passage: "
_QUERY_PREFIX = "query: "


class ModelEmbedder:
    name = "model"

    def __init__(self, model_name: str, dimensions: int, cache_dir: str | None = None) -> None:
        self._model_name = model_name
        self._dimensions = dimensions
        self._cache_dir = cache_dir
        self._model = None

    @property
    def dimensions(self) -> int:
        return self._dimensions

    def _load(self):
        """Load on first use, and fail loudly rather than substituting anything."""
        if self._model is None:
            try:
                from fastembed import TextEmbedding

                self._model = TextEmbedding(
                    model_name=self._model_name, cache_dir=self._cache_dir
                )
            except Exception as exc:
                raise EmbeddingError(
                    f"could not load embedding model {self._model_name!r}: "
                    f"{type(exc).__name__}: {exc}. "
                    "Ingestion stops here rather than storing vectors from a different model."
                ) from exc
        return self._model

    def _embed(self, texts: list[str]) -> list[list[float]]:
        model = self._load()
        try:
            vectors = [list(map(float, v)) for v in model.embed(texts)]
        except Exception as exc:
            raise EmbeddingError(
                f"embedding failed: {type(exc).__name__}: {exc}"
            ) from exc
        for vector in vectors:
            if len(vector) != self._dimensions:
                raise EmbeddingError(
                    f"model {self._model_name!r} produced width {len(vector)} but the "
                    f"contract declares {self._dimensions}"
                )
        return vectors

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        return self._embed([_PASSAGE_PREFIX + t for t in texts])

    def embed_query(self, text: str) -> list[float]:
        return self._embed([_QUERY_PREFIX + text])[0]
