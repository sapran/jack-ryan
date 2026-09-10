"""Hybrid search: keyword and semantic retrieval, fused into one ranking."""

from __future__ import annotations

from ..embedding.port import EmbedderPort
from ..errors import AmbiguousReferenceError, ConfigError, NotFoundError, ValidationError
from ..mentions import MENTION_KINDS, default_extractors
from ..reranking.port import RerankError, RerankerPort
from ..storage.port import (
    Chunk,
    Document,
    MentionDocumentPage,
    MentionFacet,
    SearchHit,
    StorePort,
    Window,
)
from .casefiles import CasefileService
from .ingestion import DEFAULT_LISTING_PAGE, MAX_DOCUMENT_OFFSET, MAX_LISTING_PAGE
from .windowing import DEFAULT_WINDOW_MAX_CHARS, Windower

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
        self._reranker = reranker
        self._rerank_depth = int(rerank_depth)
        # The window rule is given the one store question it asks, rather than
        # the store: nineteen port methods would overstate what it depends on,
        # and a test of the rule would then have to build a corpus to answer one
        # of them.
        self._windows = Windower(store.get_document_chunks_around, window_max_chars)

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
        return self._windows.for_results(hits)

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

    def mention_documents(
        self,
        casefile_reference: str,
        mention: str,
        offset: int = 0,
        limit: int = DEFAULT_LISTING_PAGE,
    ) -> MentionDocumentPage:
        """Every document carrying one identifier, a bounded page at a time.

        The exhaustive counterpart to `search`, and deliberately not a mode of
        it. `search` ranks and stops: both retrievers are asked for a bounded
        depth and the result is cut to the caller's limit, so an identifier
        carried by three hundred documents comes back as ten passages and
        nothing in that answer says so. This asks the store which documents
        carry it and pages the answer, which is a different question with a
        different bound — how many pages the caller reads.

        It embeds nothing and ranks nothing. Paging by raising the retrieval
        depth was the obvious alternative and is unusable: reciprocal rank
        fusion ties routinely, so two requests at different depths do not agree
        about which candidate sits at a given position, and pages cut from such
        an ordering repeat and omit entries silently.

        The identifier is parsed by the same function `search` uses, so
        `<kind>:<value>` and a bare value mean here exactly what they mean
        there, an unknown kind is refused naming the kinds, and the caller's
        spelling is normalised the way the store holds it.

        An empty identifier is refused. `_parsed_mention` returns no filter for
        it, which is right for a search and wrong here: the store would match
        `normalised = ''`, find nothing, and the caller would read an empty
        carrier set as "this casefile carries no such identifier" — the silent
        false negative this whole capability exists to remove.

        Both bounds are clamped at both ends, as every bound on this surface is.
        """
        casefile = self._casefiles.resolve(casefile_reference)
        kind, value = _parsed_mention(mention)
        if not value:
            raise ValidationError(
                "an identifier is required. Write <kind>:<value>, or a value "
                "alone to match any kind; take one from the identifier inventory."
            )
        bounded = max(1, min(int(limit), MAX_LISTING_PAGE))
        start = min(max(0, int(offset)), MAX_DOCUMENT_OFFSET)
        return self._store.documents_with_mention(
            casefile.id, kind, value, start, bounded
        )

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

    @property
    def _window_max_chars(self) -> int:
        """The window budget in force, read from the rule that applies it.

        A property rather than a field. Storing the value here as well would
        leave a copy nothing reads: two reviewers of the change that moved the
        window rule out of this file each showed that discarding the operator's
        setting when building the `Windower` — or silently doubling it — passed
        the whole suite, because the composition-root wiring test asserted on
        the copy. An operator would have got a default-sized window while
        `jackryan status` reported the value they configured.
        """
        return self._windows.budget

    def passage_window(self, chunk: Chunk, document: Document) -> Window | None:
        """The window around one passage, by the same rule a search result gets.

        Exposed so the agent surface does not carry a second answer to "what
        surrounds this passage". A retrieval rule living in an adapter is the
        divergent definition the service layer exists to prevent.

        The rule itself lives in `windowing.py`; this is the service layer's
        door to it.
        """
        return self._windows.for_passage(chunk, document)

