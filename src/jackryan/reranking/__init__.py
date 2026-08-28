"""Reranking: the port, and the implementation behind it."""

import os

from ..config import Config
from .model import CrossEncoderReranker
from .port import RerankerPort, RerankerUnavailable, RerankError

__all__ = [
    "RerankerPort",
    "RerankError",
    "RerankerUnavailable",
    "CrossEncoderReranker",
    "build_reranker",
]


def build_reranker(config: Config) -> RerankerPort | None:
    """Construct the reranker the profile names, or nothing.

    Nothing is the default and is not a failure: an instance that names no
    reranker searches exactly as it did before, offline, with no weights to
    fetch. Reranking is an improvement to retrieval, never a condition of it.
    """
    name = config.profile.reranker_model.strip()
    if not name:
        return None
    # The same cache the embedder uses: an image that pre-fetched its weights
    # points here, and otherwise they live beside the corpus.
    cache_dir = os.environ.get("JACKRYAN_MODEL_CACHE", "").strip() or str(
        config.data_dir / "models"
    )
    return CrossEncoderReranker(model_name=name, cache_dir=cache_dir)
