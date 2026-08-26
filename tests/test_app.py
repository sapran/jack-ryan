"""The composition root: corpus identity is the contract plus who filled it.

These are app-wiring tests rather than store tests — they go through
``build_context``, which is the only place the two layers are combined.
"""

from __future__ import annotations

import pytest

from jackryan.app import build_context
from jackryan.config import Config, Contract, Profile, corpus_fingerprint
from jackryan.embedding.deterministic import DeterministicEmbedder
from jackryan.embedding.model import ModelEmbedder
from jackryan.errors import ConfigError


def config_for(embedder: str, data_dir) -> Config:
    return Config(
        contract=Contract(),
        profile=Profile(name="p", embedder=embedder),
        data_dir=data_dir,
    )


def test_the_two_embedders_do_not_share_a_name():
    # EmbedderPort.name is load-bearing: it decides whether a corpus opens. Two
    # implementations sharing one would let each open what the other filled,
    # which is the condition the identity guard exists to prevent. Asserted
    # rather than left to the docstring.
    assert ModelEmbedder.name != DeterministicEmbedder.name


def test_a_deterministic_corpus_is_refused_by_a_real_model_configuration(tmp_path):
    """The defect this change closes, end to end.

    One data directory. Fill it under the deterministic embedder, then open it
    under the model embedder. Before this change both produced the same
    fingerprint, the store opened, and real e5 query vectors were cosine-compared
    against blake2b hash vectors of the same width — nothing downstream can tell
    those apart, so this refusal is the last point the difference is visible.
    """
    filled = build_context(config_for(DeterministicEmbedder.name, tmp_path))
    try:
        filled.casefiles.create("Some Casefile")
    finally:
        filled.close()

    with pytest.raises(ConfigError) as exc:
        build_context(config_for(ModelEmbedder.name, tmp_path))
    message = str(exc.value)
    # Matched on the `embedder=` component specifically. Asserting on the bare
    # word "model" would pass against any fingerprint at all, because
    # `embed_model=` contains it — a check that cannot fail proves nothing.
    assert f"embedder={DeterministicEmbedder.name}" in message, (
        "the refusal must name what filled the store"
    )
    assert f"embedder={ModelEmbedder.name}" in message, (
        "the refusal must name what tried to open it"
    )
    assert "reingest" in message, "the refusal must say how to proceed"


def test_the_same_embedder_still_reopens(tmp_path):
    # The guard must refuse a difference, not refuse everything.
    first = build_context(config_for(DeterministicEmbedder.name, tmp_path))
    try:
        first.casefiles.create("Some Casefile")
    finally:
        first.close()

    second = build_context(config_for(DeterministicEmbedder.name, tmp_path))
    try:
        assert len(second.casefiles.list()) == 1
    finally:
        second.close()


def test_the_reported_identity_is_the_one_the_store_enforces(tmp_path):
    # Reporting a value that guards nothing leaves an operator comparing the
    # wrong string against the refusal they are trying to explain.
    config = config_for(DeterministicEmbedder.name, tmp_path)
    context = build_context(config)
    try:
        assert context.corpus_fingerprint == corpus_fingerprint(
            config.contract, context.embedder.name
        )
    finally:
        context.close()


def test_a_refused_store_does_not_stay_open(tmp_path):
    # initialize opens the connection before it verifies identity, so a refusal
    # would otherwise leave the file and its WAL held open on a corpus that was
    # just rejected.
    filled = build_context(config_for(DeterministicEmbedder.name, tmp_path))
    filled.close()

    with pytest.raises(ConfigError):
        build_context(config_for(ModelEmbedder.name, tmp_path))

    # Reopening under the original configuration must still work; a leaked
    # handle on some platforms, or a half-open store, would show up here.
    reopened = build_context(config_for(DeterministicEmbedder.name, tmp_path))
    try:
        assert reopened.corpus_fingerprint.endswith(
            f"embedder={DeterministicEmbedder.name}"
        )
    finally:
        reopened.close()
