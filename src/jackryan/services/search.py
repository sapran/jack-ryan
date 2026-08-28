"""Hybrid search: keyword and semantic retrieval, fused into one ranking."""

from __future__ import annotations

import re
from dataclasses import replace

from ..embedding.port import EmbedderPort
from ..errors import AmbiguousReferenceError, NotFoundError, ValidationError
from ..reranking.port import RerankerPort
from ..storage.port import Chunk, Document, SearchHit, StorePort, Window
from .casefiles import CasefileService

MAX_LIMIT = 100
DEFAULT_LIMIT = 10
MAX_QUERY_CHARS = 500
DEFAULT_RERANK_DEPTH = 50

# What a response says decided its ordering.
RANKED_BY_FUSION = "fusion"
RANKED_BY_RERANK = "rerank"
# A reranker was configured and could not score this response. Distinct from
# `fusion`, which means none was configured: the same ordering, but one of them
# is a promise that was not kept.
RANKED_BY_RERANK_UNAVAILABLE = "rerank-unavailable"

# The conventional reciprocal-rank-fusion constant. It damps the influence of
# the very top ranks so that one retriever's confident first result cannot
# dominate a chunk both retrievers agree on.
RRF_K = 60

DEFAULT_WINDOW_MAX_CHARS = 3000

# How much corpus text one response may carry, over every result together. A
# bound on the number of results was enough only while a result was one chunk;
# once a result may be widened, a permitted count no longer implies a permitted
# quantity of text.
MAX_RESPONSE_CHARS = 60_000

# A window reaches at most this many chunks either side of the matched one,
# whatever the character budget allows. The budget bounds how much text an agent
# is handed; this bounds how far a single result may wander from what actually
# matched, which is a different question.
WINDOW_MAX_CHUNKS_EITHER_SIDE = 3

# The same heading line the chunker reads when it builds a heading trail
# (`src/jackryan/ingestion/chunker.py`). Markdown only, which is the limit of
# what this codebase knows about document structure: a scan or a plain text file
# has no headings, and there the character budget is the only bound.
_HEADING_LINE = re.compile(r"^#{1,6}\s+\S", re.MULTILINE)


def _section_bounds(chunk: Chunk, neighbours: list[Chunk]) -> tuple[int, int]:
    """How far the matched chunk's section reaches, in document characters.

    Section membership is decided by the heading trail the chunker recorded, and
    only the run of chunks contiguous with the matched one counts: a document
    that repeats a heading elsewhere must not pull distant text into the window.

    A document with no headings — a scan, a plain text file — has an empty trail
    on every chunk, and every neighbour then belongs to the same section. That is
    the honest answer for a document with no sections to respect: the character
    budget is the only bound left.
    """
    low, high = chunk.char_start, chunk.char_end
    by_ordinal = {c.ordinal: c for c in neighbours}

    for step in (-1, 1):
        ordinal = chunk.ordinal + step
        while ordinal in by_ordinal:
            neighbour = by_ordinal[ordinal]
            if neighbour.heading_path != chunk.heading_path:
                break
            low = min(low, neighbour.char_start)
            high = max(high, neighbour.char_end)
            ordinal += step
    return low, high


def _clip_to_headings(text: str, span: tuple[int, int], chunk: Chunk) -> tuple[int, int]:
    """Cut the window at any heading line it would cross.

    The chunk's recorded heading trail is not enough on its own. A chunk may
    straddle a heading — it begins in one section and runs past the next
    heading — and it carries the trail of where it began, so a window built from
    trails alone reaches into a section it should not. The heading line in the
    text is the boundary itself, and it is the same `#` line the chunker read.

    A heading immediately before the matched passage is kept: it names the
    section the passage is in, which is context rather than intrusion. A heading
    inside the matched chunk is left alone — that text is the result.
    """
    start, end = span
    before = text[start : chunk.char_start]
    matches = list(_HEADING_LINE.finditer(before))
    if matches:
        start += matches[-1].start()

    after = text[chunk.char_end : end]
    following = _HEADING_LINE.search(after)
    if following:
        end = chunk.char_end + following.start()
    return start, end


def _widen(chunk: Chunk, low: int, high: int, budget: int) -> tuple[int, int]:
    """Grow the chunk's span toward the section's edges, within the budget.

    Grown both ways rather than forward only: a passage is as likely to need the
    sentence before it as the one after. What one side cannot use, the other
    takes, so a chunk at the very start of a section still gains its full budget
    from below.
    """
    room = budget - (chunk.char_end - chunk.char_start)
    if room <= 0:
        return chunk.char_start, chunk.char_end

    before_available = chunk.char_start - low
    after_available = high - chunk.char_end
    before = min(room // 2, before_available)
    after = min(room - before, after_available)
    # Whatever the far side could not use comes back to this one.
    before = min(before_available, room - after)
    return chunk.char_start - before, chunk.char_end + after


def _keep_clear(
    low: int, high: int, chunk: Chunk, blocked: list[tuple[int, int]]
) -> tuple[int, int]:
    """Never grow across a passage another result in this response matched.

    Known before any widening happens, because the whole ranking is in hand: a
    window that swallowed a later result's passage would make the same text
    arrive twice, once as context and once as a hit.

    A passage that already overlaps this one — adjacent chunks share
    `chunk_overlap_chars` by configuration — still stops the window at its own
    edge, clamped so that this chunk never loses text of its own. Skipping such
    a neighbour entirely would let a window run straight through the passage it
    overlaps, which is the case this exists to prevent.
    """
    for start, end in blocked:
        if start > chunk.char_start:
            high = min(high, max(start, chunk.char_end))
        if end < chunk.char_end:
            low = max(low, min(end, chunk.char_start))
    return low, high


def _avoid(
    span: tuple[int, int], chunk_span: tuple[int, int], covered: list[tuple[int, int]]
) -> tuple[int, int] | None:
    """Pull a window back so it does not repeat text already returned.

    Never inside the matched chunk: that text is the result. When something
    already returned overlaps the chunk itself there is nothing to pull back to,
    and the caller falls back to the chunk alone.
    """
    start, end = span
    chunk_start, chunk_end = chunk_span
    for covered_start, covered_end in covered:
        if covered_end <= start or covered_start >= end:
            continue
        if covered_end <= chunk_start:
            start = max(start, covered_end)
        elif covered_start >= chunk_end:
            end = min(end, covered_start)
        else:
            return None
    return start, end


class SearchService:
    def __init__(
        self,
        store: StorePort,
        casefiles: CasefileService,
        embedder: EmbedderPort,
        window_max_chars: int = DEFAULT_WINDOW_MAX_CHARS,
        reranker: RerankerPort | None = None,
        rerank_depth: int = DEFAULT_RERANK_DEPTH,
    ) -> None:
        self._store = store
        self._casefiles = casefiles
        self._embedder = embedder
        self._window_max_chars = int(window_max_chars)
        self._reranker = reranker
        self._rerank_depth = int(rerank_depth)

    def resolve_passage(
        self, casefile_reference: str, reference: str
    ) -> tuple[Chunk, Document]:
        """Resolve a passage by full id or 8-character prefix, within a casefile.

        Chunk lookup lives here rather than in an adapter for the same reason
        every other rule does: the casefile boundary and the ambiguity refusal
        must hold identically on every surface, and an agent-facing adapter has
        no validation layer of its own to fall back on.
        """
        casefile = self._casefiles.resolve(casefile_reference)
        candidate = (reference or "").strip()
        if not candidate:
            raise ValidationError("a passage reference is required")

        chunk = self._store.get_chunks([candidate]).get(candidate)
        if chunk is None:
            matches = self._store.find_chunks_by_id_prefix(casefile.id, candidate)
            if len(matches) > 1:
                shown = ", ".join(m.short_id for m in matches[:5])
                raise AmbiguousReferenceError(
                    f"{reference!r} matches {len(matches)} passages ({shown}); use the full id"
                )
            if not matches:
                raise NotFoundError(f"no passage matches {reference!r}")
            chunk = matches[0]

        if chunk.casefile_id != casefile.id:
            # Said distinctly from "no such passage", so an agent is never told
            # something false about the compartment boundary.
            raise NotFoundError(
                f"passage {reference!r} belongs to a different casefile"
            )

        document = self._store.get_document(chunk.document_id)
        if document is None:
            raise NotFoundError("the passage's document is missing from the store")
        return chunk, document

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
        # Deep enough to fill the reranker's pool when there is one. A reranker
        # shown only as many candidates as the caller asked for cannot improve
        # anything: the ordering it is handed is already the answer.
        depth = limit * 5
        if self._reranker is not None:
            depth = max(depth, self._rerank_depth)

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

        # Fetched before the ordering, not after, because the ordering needs a
        # tie-break that does not vary. Reciprocal rank fusion produces exact
        # ties routinely — two chunks at ranks 2 and 3 in one retriever and 3 and
        # 2 in the other score identically — and no identifier can break them:
        # chunk ids are minted afresh on every reingest, and document ids differ
        # between one store and another built from the same documents. Either
        # would make the same corpus rank differently for no reason anyone can
        # see, and no measurement of retrieval could be reproduced.
        #
        # The position within a document and the passage text are properties of
        # the corpus itself, so two stores built from the same documents order a
        # tie the same way.
        chunks = self._store.get_chunks(list(scores))

        def ordering(chunk_id: str) -> tuple[float, int, int, str, str]:
            chunk = chunks.get(chunk_id)
            return (
                -scores[chunk_id],
                min(keyword_rank.get(chunk_id, 10**6), vector_rank.get(chunk_id, 10**6)),
                chunk.ordinal if chunk else 0,
                chunk.text if chunk else "",
                chunk_id,
            )

        fused = sorted(scores, key=ordering)
        ordered, rerank_scores, ranking = self._reranked(cleaned, fused, chunks, limit)

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
                    rerank_score=rerank_scores.get(chunk_id),
                    ranking=ranking,
                )
            )
        return self._widened(hits)

    # -- reranking ---------------------------------------------------------

    def _reranked(
        self,
        query: str,
        fused: list[str],
        chunks: dict[str, Chunk],
        limit: int,
    ) -> tuple[list[str], dict[str, float], str]:
        """Reorder the fused candidates, or leave them alone and say so.

        Scored on the matched passage's own text, never on a widened window: the
        cross-encoder truncates the query-and-passage pair at its own limit with
        no way to ask for more, so handing it a window means a silent cut inside
        the library and a score describing a fragment nobody chose. A chunk is
        already bounded by the corpus contract.
        """
        if self._reranker is None:
            return fused[:limit], {}, RANKED_BY_FUSION

        # Raises if the named model cannot be built. Not caught: an instance
        # configured for a reranker it cannot load must say so rather than serve
        # the fused order as though nothing were wrong.
        self._reranker.check()

        pool = [chunk_id for chunk_id in fused[: self._rerank_depth] if chunk_id in chunks]
        if not pool:
            return fused[:limit], {}, RANKED_BY_RERANK

        try:
            values = self._reranker.score(query, [chunks[cid].text for cid in pool])
        except Exception:
            # Transient. The search still has a ranking — the fused one — and
            # refusing to answer would make retrieval quality a condition of
            # retrieval. The response carries the disclosure; this codebase has
            # no logger, and a payload an agent reads is the stronger record.
            return fused[:limit], {}, RANKED_BY_RERANK_UNAVAILABLE

        scored = dict(zip(pool, values))
        # The fused order breaks ties, so two passages the reranker cannot
        # separate stay in the order the retrievers put them — and that order is
        # already stable across rebuilds.
        position = {chunk_id: index for index, chunk_id in enumerate(pool)}
        ordered = sorted(pool, key=lambda cid: (-scored[cid], position[cid]))
        return ordered[:limit], scored, RANKED_BY_RERANK

    # -- windows -----------------------------------------------------------

    def passage_window(self, chunk: Chunk, document: Document) -> Window | None:
        """The window around one passage, by the same rule a search result gets.

        Exposed so the agent surface does not carry a second answer to "what
        surrounds this passage". A retrieval rule living in an adapter is the
        divergent definition the service layer exists to prevent.
        """
        return self._window_for(chunk, document, self._window_max_chars)

    def _window_for(
        self,
        chunk: Chunk,
        document: Document,
        budget: int,
        blocked: list[tuple[int, int]] | None = None,
    ) -> Window | None:
        if budget <= chunk.char_end - chunk.char_start:
            return None
        neighbours = self._store.get_document_chunks_around(
            chunk.document_id, chunk.ordinal, WINDOW_MAX_CHUNKS_EITHER_SIDE
        )
        low, high = _section_bounds(chunk, neighbours)
        low, high = _keep_clear(low, high, chunk, blocked or [])
        span = _widen(chunk, low, high, budget)
        span = _clip_to_headings(document.extracted_text, span, chunk)
        return self._slice(document, chunk, span)

    def _slice(
        self, document: Document, chunk: Chunk, span: tuple[int, int]
    ) -> Window | None:
        """One contiguous slice of the document's own text, or nothing.

        Nothing when the span is the chunk's own: a window identical to the
        passage is not a window, and saying so keeps "was this widened" a
        question with an answer.
        """
        text = document.extracted_text
        start = max(0, span[0])
        end = min(len(text), span[1])
        if start >= end or (start, end) == (chunk.char_start, chunk.char_end):
            return None
        return Window(text=text[start:end], char_start=start, char_end=end)

    def _widened(self, hits: list[SearchHit]) -> list[SearchHit]:
        """Widen each result in rank order, repeating no text and staying bounded.

        Rank order matters: the best result gets its full window, and a lower one
        gives way. The alternative — widening everything and merging afterwards —
        would let a weak result decide what a strong one is allowed to carry.
        """
        covered: dict[str, list[tuple[int, int]]] = {}
        spent = 0
        widened: list[SearchHit] = []

        # Every matched passage in this response, so no window grows across one.
        matched: dict[str, list[tuple[int, int]]] = {}
        for hit in hits:
            matched.setdefault(hit.document.id, []).append(
                (hit.chunk.char_start, hit.chunk.char_end)
            )

        for hit in hits:
            narrowed = False
            others = [
                span
                for span in matched.get(hit.document.id, [])
                if span != (hit.chunk.char_start, hit.chunk.char_end)
            ]
            window = self._window_for(
                hit.chunk, hit.document, self._window_max_chars, blocked=others
            )

            if window is not None:
                kept = _avoid(
                    (window.char_start, window.char_end),
                    (hit.chunk.char_start, hit.chunk.char_end),
                    covered.get(hit.document.id, []),
                )
                if kept is None:
                    window, narrowed = None, True
                elif kept != (window.char_start, window.char_end):
                    window = self._slice(hit.document, hit.chunk, kept)
                    narrowed = True

            if window is not None and spent + len(window.text) > MAX_RESPONSE_CHARS:
                window, narrowed = None, True

            hit = replace(hit, window=window, narrowed=narrowed)
            spent += len(hit.text)
            covered.setdefault(hit.document.id, []).append((hit.char_start, hit.char_end))
            widened.append(hit)

        return widened
