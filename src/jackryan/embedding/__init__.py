"""Embedding: the port, and the implementations behind it."""

import os

from ..config import Config
from .deterministic import DeterministicEmbedder
from .model import ModelEmbedder
from .port import EmbedderPort, EmbeddingError

__all__ = [
    "EmbedderPort",
    "EmbeddingError",
    "DeterministicEmbedder",
    "ModelEmbedder",
    "build_embedder",
]


def build_embedder(config: Config) -> EmbedderPort:
    """Construct the embedder the profile selects.

    The deterministic implementation is never chosen implicitly: an instance
    gets meaningless vectors only when its configuration says so.
    """
    dimensions = config.contract.embed_dimensions
    if config.profile.embedder == "deterministic":
        return DeterministicEmbedder(dimensions=dimensions)
    # An image that pre-fetched its weights points here; otherwise the cache
    # lives beside the corpus so it survives container restarts.
    cache_dir = os.environ.get("JACKRYAN_MODEL_CACHE", "").strip() or str(
        config.data_dir / "models"
    )
    return ModelEmbedder(
        model_name=config.contract.embed_model,
        dimensions=dimensions,
        embed_library=config.contract.embed_library,
        cache_dir=cache_dir,
    )
