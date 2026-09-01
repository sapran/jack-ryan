"""Hybrid search: keyword and semantic retrieval, fused into one ranking."""

from __future__ import annotations

import re
from dataclasses import replace

from ..embedding.port import EmbedderPort
from ..errors import AmbiguousReferenceError, ConfigError, NotFoundError, ValidationError
from ..mentions import MENTION_KINDS, default_extractors
from ..reranking.port import RerankError, RerankerPort
from ..storage.port import Chunk, Document, MentionFacet, SearchHit, StorePort, Window
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


DEFAULT_FACET_LIMIT = 50
MAX_FACET_LIMIT = 500


def _parsed_mention(reference: str) -> tuple[str, str]:
    """Split a `--mention` argument into a kind and a value.

    Accepts `<kind>:<value>` to mean that kind alone, and a bare `<value>` to
    mean any kind. Returns `("", "")` for an empty argument, which is no filter.

    An unrecognised kind is a `ValidationError` naming the kinds that exist,
    never an empty result set. An empty result would tell the analyst this
    casefile contains no such identifier, which is a different claim from "there
    is no such kind of identifier" and, unlike it, false.

    A value containing a colon is refused rather than searched for. The reviewer
    of this change found the docstring here claiming the opposite, so it is worth
    being exact: anything before the first colon is read as a kind, and if it is
    not one of them the whole argument is refused. `a:b@example.com` is therefore
    an error naming kind `a`, not a search for that address.

    That is the deliberate trade. Falling through to a value search would make
    `passport:12345` return nothing and read as an answer, which is the failure
    this function exists to prevent — and it is the more likely mistake by far.
    An identifier that genuinely contains a colon cannot be filtered on until
    this grows an escape, and no extractor currently produces one: three of the
    four normalise to `[0-9+]` or digits, and an email address has no colon.
    """
    cleaned = (reference or "").strip()
    if not cleaned:
        return "", ""

    head, separator, tail = cleaned.partition(":")
    if separator and head.strip().lower() in MENTION_KINDS:
        kind, value = head.strip().lower(), tail.strip()
    elif separator and head.strip().lower() and not tail.strip():
        # `email:` with nothing after it. Refused rather than read as a bare
        # value, because the caller plainly meant to filter by kind and gave no
        # value, and searching for the literal text "email:" is not it.
        raise ValidationError(
            f"--mention {cleaned!r} names a kind with no value. Write "
            f"<kind>:<value>, or a value alone to match any kind."
        )
    else:
        kind, value = "", cleaned

    if separator and not kind and head.strip():
        # Something that looks like a kind and is not one. Caught here rather
        # than falling through to a value search, because `passport:12345` as a
        # literal value matches nothing and would read as an answer.
        raise ValidationError(
            f"--mention names identifier kind {head.strip()!r}, which no extractor "
            f"produces. Known kinds: {', '.join(MENTION_KINDS)}."
        )
    if not value:
        raise ValidationError("--mention needs a value to match")
    return kind, _normalised_like_the_store(value, kind)


def _normalised_like_the_store(value: str, kind: str) -> str:
    """The caller's value in the form the store actually holds.

    Without this the two sides of the comparison are produced by different
    rules: the store holds `normalised`, and the caller types whatever the
    document showed them. An analyst who copies `Billing@Acme.example` out of
    the passage they just read, or `GB82 WEST 1234 5698 7654 32` off a
    statement, would get nothing back and no error — the silent empty result
    that reads as "this casefile does not mention that", which is the exact
    failure this whole feature is arranged to prevent. Three of the four kinds
    are affected; only `registration_number` normalises to itself.

    Done by asking the extractors rather than by reimplementing their rules
    here, so a fifth extractor is normalised correctly by existing. An
    extractor's answer is taken only when it recognises the *whole* value:
    a partial match would silently search for something narrower than what was
    asked for, which is a wrong answer rather than a missing one.

    A value no extractor recognises is passed through unchanged. It may be an
    identifier written in a form nothing extracts, in which case nothing was
    stored for it either and an empty result is the honest answer.
    """
    for extractor in default_extractors():
        if kind and extractor.kind != kind:
            continue
        for found in extractor.find(value):
            if found.value == value.strip():
                return found.normalised
    return value


def _validated_kind(kind: str) -> str:
    """A facet's kind: one the registry produces, or empty for all of them."""
    cleaned = (kind or "").strip().lower()
    if cleaned and cleaned not in MENTION_KINDS:
        raise ValidationError(
            f"identifier kind {cleaned!r} is not one any extractor produces. "
            f"Known kinds: {', '.join(MENTION_KINDS)}."
        )
    return cleaned


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
        self,
        casefile_reference: str,
        query: str,
        limit: int = DEFAULT_LIMIT,
        mention: str = "",
    ) -> list[SearchHit]:
        """Search one casefile, returning ranked passages.

        Both retrievers run over the same store and are fused by rank. Scores
        are never blended: keyword relevance and vector distance are not
        comparable quantities, and mixing them would need a weighting tuned per
        corpus.

        `mention` narrows the search to passages carrying an identifier, as
        `<kind>:<value>` or a bare value matching any kind. It is a predicate the
        retrievers apply, not a filter over what they return, and the difference
        is the whole of it: both are asked for a bounded `depth`, so removing
        non-matching candidates afterwards would discard every matching passage
        that ranked below that depth unfiltered. A caller pivoting on an
        identifier that appears in one passage of ten thousand would be handed
        nothing while the store held exactly what they asked for — and would read
        it as "this casefile does not mention that".

        It adds no rank leg and touches no score. It decides which passages are
        candidates; fusion then ranks them exactly as it ranks any others, which
        is also why reranking still only reorders what fusion produced.
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

        mention_kind, mention_value = _parsed_mention(mention)

        keyword_ids = self._store.search_keyword(
            casefile.id, cleaned, depth, mention_kind, mention_value
        )
        vector_ids = self._store.search_vector(
            casefile.id,
            self._embedder.embed_query(cleaned),
            depth,
            mention_kind,
            mention_value,
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

    def mention_facets(
        self,
        casefile_reference: str,
        kind: str = "",
        limit: int = DEFAULT_FACET_LIMIT,
    ) -> list[MentionFacet]:
        """What identifiers a casefile contains, counted.

        The question an analyst cannot otherwise ask. Search answers "does this
        corpus mention X", which needs X in hand; this answers "what does it
        mention", which is the step the role's own method calls *pivot* — the
        corpus telling the analyst what it calls things.

        Both counts are carried because neither substitutes for the other: an
        identifier mentioned forty times in one document is a different fact from
        one mentioned once in each of forty, and an analyst deciding where to
        look has to be able to tell them apart.

        A separate path rather than an envelope on `search`, which returns a bare
        list of hits: an envelope would change three surfaces for a question none
        of them asked.

        The inventory is what was *found*, never a claim about what is *there*.
        The shipped extractors prefer precision, so an identifier written without
        its keyword or with a transposed digit is absent from this — and the
        analyst pack's own rule that absence of evidence is not evidence of
        absence applies to this list exactly.
        """
        casefile = self._casefiles.resolve(casefile_reference)
        # Clamped rather than refused, as every other bound on this surface is.
        bounded = max(1, min(int(limit), MAX_FACET_LIMIT))
        return self._store.mention_facets(casefile.id, _validated_kind(kind), bounded)

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

        # Never shallower than the caller asked for. A pool of `rerank_depth`
        # alone would withhold results fusion had found whenever the caller
        # wanted more than the pool holds — reranking reorders what was found,
        # and must not decide how much is found.
        depth = max(limit, self._rerank_depth)
        pool = [chunk_id for chunk_id in fused[:depth] if chunk_id in chunks]
        if not pool:
            return fused[:limit], {}, RANKED_BY_RERANK

        try:
            values = list(self._reranker.score(query, [chunks[cid].text for cid in pool]))
            if len(values) != len(pool):
                # Checked here rather than trusted: a short list would pair
                # scores with the wrong passages, and zip() would hide it.
                raise RerankError(
                    f"reranker returned {len(values)} scores for {len(pool)} passages"
                )
            scored = dict(zip(pool, values))
            # The fused order breaks ties, so two passages the reranker cannot
            # separate stay in the order the retrievers put them — and that
            # order is already stable across rebuilds.
            position = {chunk_id: index for index, chunk_id in enumerate(pool)}
            ordered = sorted(pool, key=lambda cid: (-scored[cid], position[cid]))
        except ConfigError:
            # A misconfiguration, whichever method raised it. Re-raised rather
            # than degraded: the split between fatal and transient has to hold
            # by type, not by which call happened to come first.
            raise
        except Exception:
            # Transient. The search still has a ranking — the fused one — and
            # refusing to answer would make retrieval quality a condition of
            # retrieval. The response carries the disclosure; this codebase has
            # no logger, and a payload an agent reads is the stronger record.
            return fused[:limit], {}, RANKED_BY_RERANK_UNAVAILABLE

        # Anything deeper than the pool keeps its fused position behind the
        # reranked ones, so a caller asking for more than the pool holds still
        # receives everything fusion found.
        seen = set(pool)
        rest = [chunk_id for chunk_id in fused if chunk_id not in seen]
        return (ordered + rest)[:limit], scored, RANKED_BY_RERANK

    # -- windows -----------------------------------------------------------

    def passage_window(self, chunk: Chunk, document: Document) -> Window | None:
        """The window around one passage, by the same rule a search result gets.

        Exposed so the agent surface does not carry a second answer to "what
        surrounds this passage". A retrieval rule living in an adapter is the
        divergent definition the service layer exists to prevent.
        """
        window, _ = self._window_for(chunk, document, self._window_max_chars)
        return window

    def _window_for(
        self,
        chunk: Chunk,
        document: Document,
        budget: int,
        blocked: list[tuple[int, int]] | None = None,
    ) -> tuple[Window | None, bool]:
        """The window, and whether other results in the response reduced it.

        The second value is what a caller reports as `narrowed`. Without it a
        result cut back to make room for a neighbour looks exactly like one that
        had no more context to give, which is the confusion the flag exists to
        prevent.
        """
        if budget <= chunk.char_end - chunk.char_start:
            return None, False

        neighbours = self._store.get_document_chunks_around(
            chunk.document_id, chunk.ordinal, WINDOW_MAX_CHUNKS_EITHER_SIDE
        )
        low, high = _section_bounds(chunk, neighbours)
        text = document.extracted_text

        kept_low, kept_high = _keep_clear(low, high, chunk, blocked or [])
        span = _clip_to_headings(text, _widen(chunk, kept_low, kept_high, budget), chunk)
        window = self._slice(document, chunk, span)

        if (kept_low, kept_high) == (low, high):
            return window, False
        # Cheap because both are pure arithmetic over spans already in hand: ask
        # what this result would have carried with the response to itself.
        alone = _clip_to_headings(text, _widen(chunk, low, high, budget), chunk)
        return window, alone != span

    def _slice(
        self, document: Document, chunk: Chunk, span: tuple[int, int]
    ) -> Window | None:
        """One contiguous slice of the document's own text, or nothing.

        Nothing when the span is the chunk's own: a window identical to the
        passage is not a window, and saying so keeps "was this widened" a
        question with an answer.

        Nothing, too, when the stored offsets no longer select the stored
        passage. Ingestion writes a document and its chunks in two transactions
        with a fallible embedding call between them, so a run that fails in the
        middle leaves new text against old offsets. Widening on those would
        return a passage from elsewhere in the document as the result's body,
        fenced as evidence, under provenance naming a span it never occupied.
        The chunk's own text is still right, so the result falls back to it.
        """
        text = document.extracted_text
        if text[chunk.char_start : chunk.char_end].strip() != chunk.text:
            return None
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
            others = [
                span
                for span in matched.get(hit.document.id, [])
                if span != (hit.chunk.char_start, hit.chunk.char_end)
            ]
            # `narrowed` starts from whether another result's passage already
            # cost this one context — not only from the two checks below.
            window, narrowed = self._window_for(
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
