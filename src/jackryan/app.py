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
from .services.casefiles import CasefileService
from .services.ingestion import IngestionService
from .services.search import SearchService
from .storage.sqlite import SqliteStore


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

    store: SqliteStore
    embedder: EmbedderPort
    casefiles: CasefileService
    ingestion: IngestionService
    search: SearchService

    def close(self) -> None:
        self.store.close()


def build_context(
    config: Config | None = None,
    embedder: EmbedderPort | None = None,
    gate: QualityGate | None = None,
) -> Context:
    """Open the store and construct the service layer over it.

    The gate is injectable for the same reason the embedder is: so a test can
    wire a real instance without loading models. Absent, it is built from the
    profile, and nothing about it is verified here — the recognition engine is
    built at the start of an ingest run, which is the only place that needs it.
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
    # and never sees the embedder, and `build_embedder` builds from the contract
    # so it can never disagree with it. Compared before the store is constructed
    # rather than after, because `initialize` would already have created the
    # vector table at the contract's width and recorded a valid identity —
    # leaving a wrongly sized store on disk that opens cleanly and then refuses
    # every chunk part-way through an ingest.
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
    identity = corpus_fingerprint(resolved.contract, chosen.name)
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
        ingestion=IngestionService(
            store, casefiles, chosen, resolved.contract, gate=chosen_gate
        ),
        search=SearchService(store, casefiles, chosen),
    )
