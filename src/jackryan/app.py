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
from .services.casefiles import CasefileService
from .services.ingestion import IngestionService
from .services.search import SearchService
from .storage.sqlite import SqliteStore


@dataclass
class Context:
    """A configured instance: config, store, and the services over it."""

    config: Config
    store: SqliteStore
    embedder: EmbedderPort
    casefiles: CasefileService
    ingestion: IngestionService
    search: SearchService

    corpus_fingerprint: str = ""
    """The identity the store records and enforces.

    Held here so adapters report the value that actually guards rather than
    recomputing one beside it. Two definitions of corpus identity is how an
    operator ends up comparing a string that cannot explain their refusal.
    """

    def close(self) -> None:
        self.store.close()


def build_context(config: Config | None = None, embedder: EmbedderPort | None = None) -> Context:
    """Open the store and construct the service layer over it."""
    resolved = config or load_config()
    # The embedder is built first because it is part of corpus identity: the
    # store cannot be opened until we know who would be filling it. Safe to do
    # in this order because constructing an embedder is cheap and cannot fail —
    # ModelEmbedder defers every load to first use — so nothing expensive
    # happens before the store's own guard has had its say.
    chosen = embedder or build_embedder(resolved)
    identity = corpus_fingerprint(resolved.contract, chosen.name)
    store = SqliteStore(resolved.db_path)
    store.initialize(identity, resolved.contract.embed_dimensions)
    casefiles = CasefileService(store)
    return Context(
        config=resolved,
        store=store,
        corpus_fingerprint=identity,
        embedder=chosen,
        casefiles=casefiles,
        ingestion=IngestionService(store, casefiles, chosen, resolved.contract),
        search=SearchService(store, casefiles, chosen),
    )
