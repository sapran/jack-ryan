"""Composition root.

Wires configuration to a store to the service layer, once, so no adapter has
to know how the parts fit together. Every adapter asks here for services and
gets the same wiring.
"""

from __future__ import annotations

from dataclasses import dataclass

from .config import Config, load_config
from .services.casefiles import CasefileService
from .storage.sqlite import SqliteStore


@dataclass
class Context:
    """A configured instance: config, store, and the services over it."""

    config: Config
    store: SqliteStore
    casefiles: CasefileService

    def close(self) -> None:
        self.store.close()


def build_context(config: Config | None = None) -> Context:
    """Open the store and construct the service layer over it."""
    resolved = config or load_config()
    store = SqliteStore(resolved.db_path)
    store.initialize(resolved.contract.fingerprint())
    return Context(
        config=resolved,
        store=store,
        casefiles=CasefileService(store),
    )
