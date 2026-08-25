"""Hybrid search: keyword and semantic retrieval, fused into one ranking."""

from __future__ import annotations

from ..embedding.port import EmbedderPort
from ..errors import ValidationError
from ..storage.port import SearchHit, StorePort
from .casefiles import CasefileService

MAX_LIMIT = 100
DEFAULT_LIMIT = 10
MAX_QUERY_CHARS = 500

# The conventional reciprocal-rank-fusion constant. It damps the influence of
# the very top ranks so that one retriever's confident first result cannot
# dominate a chunk both retrievers agree on.
RRF_K = 60


class SearchService:
    def __init__(
        self, store: StorePort, casefiles: CasefileService, embedder: EmbedderPort
    ) -> None:
        self._store = store
        self._casefiles = casefiles
        self._embedder = embedder

    def search(
        self, casefile_reference: str, query: str, limit: int = DEFAULT_LIMIT
    ) -> list[SearchHit]:
        """Search one casefile, returning ranked passages.

        Both retrievers run over the same store and are fused by rank. Scores
        are never blended: keyword relevance and vector distance are not
        comparable quantities, and mixing them would need a weighting tuned per
        corpus.
        """
        casefile = self._casefiles.resolve(casefile_reference)

        cleaned = (query or "").strip()
        if not cleaned:
            raise ValidationError("a query is required")
        cleaned = cleaned[:MAX_QUERY_CHARS]

        # Clamp rather than reject: an agent surface has no validation layer of
        # its own, and an over-large limit is a harmless mistake.
        limit = max(1, min(int(limit), MAX_LIMIT))
        depth = limit * 5

        keyword_ids = self._store.search_keyword(casefile.id, cleaned, depth)
        vector_ids = self._store.search_vector(
            casefile.id, self._embedder.embed_query(cleaned), depth
        )

        keyword_rank = {cid: i + 1 for i, cid in enumerate(keyword_ids)}
        vector_rank = {cid: i + 1 for i, cid in enumerate(vector_ids)}

        scores: dict[str, float] = {}
        for ranks in (keyword_rank, vector_rank):
            for chunk_id, rank in ranks.items():
                scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (RRF_K + rank)

        ordered = sorted(
            scores,
            key=lambda cid: (
                -scores[cid],
                min(keyword_rank.get(cid, 10**6), vector_rank.get(cid, 10**6)),
                cid,
            ),
        )[:limit]

        chunks = self._store.get_chunks(ordered)
        documents = {}
        hits: list[SearchHit] = []
        for chunk_id in ordered:
            chunk = chunks.get(chunk_id)
            if chunk is None:
                continue
            if chunk.document_id not in documents:
                documents[chunk.document_id] = self._store.get_document(chunk.document_id)
            document = documents[chunk.document_id]
            if document is None:
                continue
            hits.append(
                SearchHit(
                    chunk=chunk,
                    document=document,
                    score=scores[chunk_id],
                    keyword_rank=keyword_rank.get(chunk_id),
                    vector_rank=vector_rank.get(chunk_id),
                )
            )
        return hits
