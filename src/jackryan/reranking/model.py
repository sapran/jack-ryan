"""The real reranker: an ONNX cross-encoder, loaded lazily.

`fastembed` is already a dependency — it is what produces the vectors — and it
carries a cross-encoder alongside the embedding models, so reranking adds
nothing to the lock file. The weights are a separate download, made on first use
and cached beside the embedder's.
"""

from __future__ import annotations

from typing import Sequence

from .port import RerankError, RerankerUnavailable


class CrossEncoderReranker:
    def __init__(
        self,
        model_name: str,
        cache_dir: str | None = None,
        local_files_only: bool = False,
    ) -> None:
        self.name = model_name
        self._cache_dir = cache_dir
        self._local_files_only = local_files_only
        self._model = None

    def check(self) -> None:
        self._load()

    def _load(self):
        if self._model is not None:
            return self._model

        try:
            from fastembed.rerank.cross_encoder import TextCrossEncoder
        except Exception as exc:
            raise RerankerUnavailable(
                f"profile names reranker_model={self.name!r}, but the reranking library "
                f"could not be imported: {type(exc).__name__}: {exc}"
            ) from exc

        try:
            self._model = TextCrossEncoder(
                model_name=self.name,
                cache_dir=self._cache_dir,
                local_files_only=self._local_files_only,
            )
        except Exception as exc:
            # Named models are listed, because the usual cause is a typo and the
            # list is the answer. An unlisted name is not necessarily wrong — a
            # custom model can be registered — so the list is offered rather
            # than asserted.
            raise RerankerUnavailable(
                f"profile sets reranker_model={self.name!r}, which could not be built: "
                f"{type(exc).__name__}: {exc}. "
                f"Known models: {', '.join(supported_models()) or 'none reported'}. "
                "Searches are not run with a reranker the instance cannot load, because "
                "an instance quietly serving worse results than configured has hidden it."
            ) from exc
        return self._model

    def score(self, query: str, passages: Sequence[str]) -> list[float]:
        if not passages:
            return []
        model = self._load()
        try:
            # `rerank` is a generator: nothing runs until it is consumed, so the
            # list() is what puts a failure inside this try rather than in the
            # caller's loop.
            scores = [float(value) for value in model.rerank(query, list(passages))]
        except Exception as exc:
            raise RerankError(
                f"reranker {self.name!r} failed while scoring: {type(exc).__name__}: {exc}"
            ) from exc
        if len(scores) != len(passages):
            raise RerankError(
                f"reranker {self.name!r} returned {len(scores)} scores for "
                f"{len(passages)} passages; the ordering cannot be trusted"
            )
        return scores


def supported_models() -> list[str]:
    """The reranker names this build knows, for an error message to offer."""
    try:
        from fastembed.rerank.cross_encoder import TextCrossEncoder

        return [str(entry["model"]) for entry in TextCrossEncoder.list_supported_models()]
    except Exception:
        return []
