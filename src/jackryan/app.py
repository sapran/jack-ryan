"""Composition root.

Wires configuration to a store to the service layer, once, so no adapter has
to know how the parts fit together. Every adapter asks here for services and
gets the same wiring.
"""

from __future__ import annotations

from dataclasses import dataclass

from .config import Config, corpus_fingerprint, load_config
from .embedding import build_embedder
from .embedding.port import EmbedderPort
from .errors import ConfigError
from .ingestion.quality_gate import QualityGate
from .reranking import build_reranker
from .reranking.port import RerankerPort
from .services.casefiles import CasefileService
from .services.ingestion import IngestionService
from .services.search import SearchService
from .storage.port import StorePort
from .storage.sqlite import SqliteStore
from .summarising import build_summariser
from .summarising.port import SummariserPort


@dataclass
class Context:
    """A configured instance: config, store, and the services over it."""

    config: Config
    corpus_fingerprint: str
    """The identity the store records and enforces.

    Required, not defaulted: a Context built without it would report an empty
    corpus identity from /health and `jackryan status`, which is exactly the
    failure this field exists to prevent — an operator comparing a string that
    cannot explain their refusal.
    """

    store: StorePort
    """The store, as the seam rather than as the implementation.

    Declared as the port so that reaching past the service layer is a type
    error rather than something a review has to notice. The field still holds a
    `SqliteStore` — this is a claim about what a holder of a `Context` may
    assume, not about what was constructed. Nothing in this repository type-
    checks today, so the claim is documentation; the test that enforces it is
    `test_no_adapter_reaches_the_store`.
    """

    embedder: EmbedderPort
    casefiles: CasefileService
    ingestion: IngestionService
    search: SearchService
    summariser_name: str = ""
    """The summariser whose output is folded into what is embedded, or empty.

    Empty when nothing is folded, which is the default — and empty is what keeps
    `corpus_fingerprint` byte-identical to the value a corpus recorded before
    summaries existed. Held here because it is the component of corpus identity
    an operator cannot read off their own configuration: it carries a hash of
    the shipped prompt as well as the model they named.
    """

    def close(self) -> None:
        self.store.close()


def build_context(
    config: Config | None = None,
    embedder: EmbedderPort | None = None,
    gate: QualityGate | None = None,
    reranker: RerankerPort | None = None,
    summariser: SummariserPort | None = None,
) -> Context:
    """Open the store and construct the service layer over it.

    The gate is injectable for the same reason the embedder is: so a test can
    wire a real instance without loading models. Absent, it is built from the
    profile, and nothing about it is verified here — the recognition engine is
    built at the start of an ingest run, which is the only place that needs it.

    The reranker is injectable on the same terms, and is absent unless the
    profile names one. Unlike the embedder it is not part of corpus identity: it
    writes nothing, so an instance can gain or lose one without the store having
    an opinion.

    The summariser is injectable on the same terms again, and is absent unless
    the profile names one. It sits between the other two: like the reranker it
    is a deployment choice in the profile layer, and like the embedder it can
    determine what a vector means — but only when `chunk_summaries` folds its
    output into what is embedded. So it enters corpus identity exactly when
    folding is on, and not merely when a model is named.
    """
    resolved = config or load_config()
    # The embedder is built first because it is part of corpus identity: the
    # store cannot be opened until we know who would be filling it. Cheap in
    # this order because ModelEmbedder defers every load to first use, so no
    # weights are fetched before the store's guard has had its say. Note the
    # narrower claim: construction is cheap, not infallible — DeterministicEmbedder
    # rejects a non-positive width at construction, and that now surfaces from
    # the composition root rather than later.
    chosen = embedder or build_embedder(resolved)
    # Both widths are in hand here and nowhere else: the store is told a width
    # and never sees the embedder.
    #
    # Be clear about what this catches, because it reads like more than it is.
    # `build_embedder` constructs either implementation with the contract's
    # width, and both hand that value straight back, so configuration alone
    # cannot make these disagree. What this guards is the seam just above —
    # an embedder passed in directly — and it becomes the guard it looks like
    # on the day one reports a width it was not given, having learnt it from
    # the model it loaded. A contract that declares a width the real model does
    # not produce is a different failure, and `ModelEmbedder` already raises on
    # it when it loads.
    #
    # Compared before the store is constructed rather than after: once
    # `initialize` has run, the vector table exists at the contract's width and
    # a valid identity is recorded, leaving a wrongly sized store on disk that
    # opens cleanly.
    if chosen.dimensions != resolved.contract.embed_dimensions:
        raise ConfigError(
            f"embedder {chosen.name!r} produces {chosen.dimensions}-wide vectors but the "
            f"contract declares embed_dimensions={resolved.contract.embed_dimensions}. "
            "The vector index is sized from the contract, so this instance would open "
            "cleanly and then refuse every chunk part-way through an ingest. Select an "
            "embedder that matches, or change embed_dimensions — but that value is "
            "corpus-coupled, so changing it is a new corpus identity and forces a "
            "reingest of every casefile."
        )
    chosen_summariser = summariser or build_summariser(resolved)
    # Named is not the same as folded in. A summariser writing per-document
    # summaries and nothing else moves no vector, so it must leave corpus
    # identity alone and stay openable over an existing corpus; only folding
    # changes what the embedder is given, and only folding may refuse a store.
    folding = bool(resolved.profile.chunk_summaries and chosen_summariser is not None)
    # Composed here rather than in the contract because the value carries a hash
    # of the shipped prompt and sampling parameters, which an operator cannot
    # know — see `corpus_fingerprint`. Empty when folding is off, and the
    # component is then omitted entirely, so this string stays byte-identical to
    # the one a corpus recorded before summaries existed.
    summariser_name = chosen_summariser.name if folding else ""
    identity = corpus_fingerprint(resolved.contract, chosen.name, summariser_name)
    store = SqliteStore(resolved.db_path)
    try:
        store.initialize(identity, resolved.contract.embed_dimensions)
    except Exception:
        # initialize opens the connection before it verifies identity, so a
        # refusal leaves the file, its WAL and its SHM held open on a corpus we
        # have just rejected.
        store.close()
        raise
    casefiles = CasefileService(store)
    chosen_gate = gate or QualityGate.from_profile(resolved.profile)
    return Context(
        config=resolved,
        store=store,
        corpus_fingerprint=identity,
        embedder=chosen,
        casefiles=casefiles,
        summariser_name=summariser_name,
        ingestion=IngestionService(
            store,
            casefiles,
            chosen,
            resolved.contract,
            gate=chosen_gate,
            summariser=chosen_summariser,
            chunk_summaries=folding,
        ),
        search=SearchService(
            store,
            casefiles,
            chosen,
            window_max_chars=resolved.profile.window_max_chars,
            # Nothing unless the profile names one, and nothing is fetched here:
            # the model is built when the first search needs it, so a refusal
            # names the setting rather than delaying every `jackryan status`.
            reranker=reranker or build_reranker(resolved),
            rerank_depth=resolved.profile.rerank_depth,
        ),
    )
