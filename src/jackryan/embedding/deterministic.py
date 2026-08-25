"""A deterministic embedder, for tests.

This is a real embedder rather than a stub: identical text yields identical
vectors, and texts sharing vocabulary land closer together than texts sharing
none, so ranking and fusion are exercised for real without downloading a model.

It carries no semantic meaning, so it is selected only by explicit
configuration and is never used as a fallback.
"""

from __future__ import annotations

import hashlib
import math
import re

_TOKEN = re.compile(r"[\wЀ-ӿ]+", re.UNICODE)


class DeterministicEmbedder:
    name = "deterministic"

    def __init__(self, dimensions: int = 1024) -> None:
        if dimensions < 1:
            raise ValueError("dimensions must be positive")
        self._dimensions = dimensions

    @property
    def dimensions(self) -> int:
        return self._dimensions

    def _embed(self, text: str) -> list[float]:
        vector = [0.0] * self._dimensions
        for token in _TOKEN.findall(text.lower()):
            digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
            index = int.from_bytes(digest[:4], "big") % self._dimensions
            # A sign drawn from the hash keeps unrelated tokens from all
            # pushing a vector the same way.
            sign = 1.0 if digest[4] & 1 else -1.0
            vector[index] += sign
        norm = math.sqrt(sum(v * v for v in vector))
        if norm == 0.0:
            # No tokens at all: a fixed unit vector, so the width is still right.
            vector[0] = 1.0
            return vector
        return [v / norm for v in vector]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)
