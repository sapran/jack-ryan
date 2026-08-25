from __future__ import annotations

import pytest

from jackryan.app import Context
from jackryan.config import Config, Contract, Profile
from jackryan.services.casefiles import CasefileService
from jackryan.storage.sqlite import SqliteStore


@pytest.fixture
def config(tmp_path) -> Config:
    return Config(
        contract=Contract(),
        profile=Profile(name="test"),
        data_dir=tmp_path,
    )


@pytest.fixture
def context(config: Config) -> Context:
    store = SqliteStore(config.db_path)
    store.initialize(config.contract.fingerprint())
    ctx = Context(config=config, store=store, casefiles=CasefileService(store))
    yield ctx
    ctx.close()


@pytest.fixture
def service(context: Context) -> CasefileService:
    return context.casefiles
