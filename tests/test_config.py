"""The contract is corpus-coupled and profiles are infrastructure, so the
loader has to fail loudly rather than substitute a default."""

from __future__ import annotations

import pytest

from jackryan.config import Contract, load_config
from jackryan.errors import ConfigError


def write_config(tmp_path, body: str) -> str:
    path = tmp_path / "config.yaml"
    path.write_text(body, encoding="utf-8")
    return str(path)


def test_defaults_apply_with_no_config_file(monkeypatch):
    monkeypatch.delenv("JACKRYAN_CONFIG", raising=False)
    monkeypatch.delenv("JACKRYAN_PROFILE", raising=False)
    config = load_config()
    assert config.contract == Contract()
    assert config.profile.name == "local"


def test_env_var_beats_config_file(tmp_path, monkeypatch):
    path = write_config(tmp_path, "default_profile: local\nprofiles:\n  local: {}\n  remote: {}\n")
    monkeypatch.setenv("JACKRYAN_CONFIG", path)
    monkeypatch.setenv("JACKRYAN_PROFILE", "remote")
    assert load_config().profile.name == "remote"


def test_empty_profile_env_var_falls_back_to_default(tmp_path, monkeypatch):
    path = write_config(tmp_path, "default_profile: local\nprofiles:\n  local: {}\n")
    monkeypatch.setenv("JACKRYAN_CONFIG", path)
    monkeypatch.setenv("JACKRYAN_PROFILE", "   ")
    assert load_config().profile.name == "local"


def test_unknown_profile_is_fatal_and_names_alternatives(tmp_path, monkeypatch):
    path = write_config(tmp_path, "profiles:\n  local: {}\n  remote: {}\n")
    monkeypatch.setenv("JACKRYAN_CONFIG", path)
    monkeypatch.setenv("JACKRYAN_PROFILE", "typo")
    with pytest.raises(ConfigError) as exc:
        load_config()
    assert "typo" in str(exc.value)
    assert "local, remote" in str(exc.value)


def test_unknown_contract_key_is_fatal(tmp_path, monkeypatch):
    path = write_config(tmp_path, "contract:\n  chunk_sizes: 512\n")
    monkeypatch.setenv("JACKRYAN_CONFIG", path)
    monkeypatch.delenv("JACKRYAN_PROFILE", raising=False)
    with pytest.raises(ConfigError, match="chunk_sizes"):
        load_config()


def test_secret_placeholder_resolves_from_environment(tmp_path, monkeypatch):
    path = write_config(
        tmp_path, "profiles:\n  remote:\n    api_key: ${JACKRYAN_TEST_KEY}\n"
    )
    monkeypatch.setenv("JACKRYAN_CONFIG", path)
    monkeypatch.setenv("JACKRYAN_PROFILE", "remote")
    monkeypatch.setenv("JACKRYAN_TEST_KEY", "resolved-value")
    assert load_config().profile.api_key == "resolved-value"


def test_unset_secret_placeholder_is_fatal(tmp_path, monkeypatch):
    path = write_config(
        tmp_path, "profiles:\n  remote:\n    api_key: ${JACKRYAN_MISSING_KEY}\n"
    )
    monkeypatch.setenv("JACKRYAN_CONFIG", path)
    monkeypatch.setenv("JACKRYAN_PROFILE", "remote")
    monkeypatch.delenv("JACKRYAN_MISSING_KEY", raising=False)
    with pytest.raises(ConfigError, match="JACKRYAN_MISSING_KEY"):
        load_config()


def test_contract_fingerprint_changes_with_any_value():
    assert Contract().fingerprint() != Contract(chunk_max_chars=512).fingerprint()


def test_the_fingerprint_covers_the_embedding_library():
    # The defect this guards: fastembed 0.5.1 and 0.8.0 embed the same model
    # with different pooling, producing vectors of the declared width that are
    # not comparable. Before this value entered the fingerprint the two were
    # indistinguishable, so the store admitted one corpus into the other.
    assert (
        Contract().fingerprint()
        != Contract(embed_library="fastembed==0.5.1").fingerprint()
    )


def test_the_default_contract_declares_the_installed_library():
    # The declaration has to be a fact, not an aspiration: if the shipped
    # default drifts from what the pins install, every fresh instance is fatal.
    from importlib import metadata

    declared = Contract().embed_library
    distribution, _, version = declared.partition("==")
    assert metadata.version(distribution) == version, (
        f"contract declares {declared!r} but {metadata.version(distribution)} is installed; "
        "update DEFAULT_CONTRACT and the pyproject pin together"
    )


def test_a_declared_library_version_that_is_not_installed_is_fatal(tmp_path, monkeypatch):
    monkeypatch.setenv(
        "JACKRYAN_CONFIG",
        write_config(tmp_path, "contract:\n  embed_library: fastembed==0.5.1\n"),
    )
    with pytest.raises(ConfigError) as exc:
        load_config()
    message = str(exc.value)
    assert "0.5.1" in message, "the declared version must be named"
    assert "reingest" in message, "the operator must be told how to proceed"


def test_a_declared_distribution_that_is_absent_is_fatal(tmp_path, monkeypatch):
    monkeypatch.setenv(
        "JACKRYAN_CONFIG",
        write_config(tmp_path, "contract:\n  embed_library: no-such-distribution==1.0\n"),
    )
    with pytest.raises(ConfigError, match="no-such-distribution"):
        load_config()


def test_a_malformed_library_declaration_is_fatal(tmp_path, monkeypatch):
    monkeypatch.setenv(
        "JACKRYAN_CONFIG",
        write_config(tmp_path, "contract:\n  embed_library: fastembed\n"),
    )
    with pytest.raises(ConfigError, match="distribution"):
        load_config()


def test_every_contract_value_is_in_the_fingerprint_and_nothing_else_is():
    # The spec's claim is that the contract declares exactly what determines
    # corpus identity: no decorative field, and none left out. A value added to
    # the dataclass but forgotten in fingerprint() would let two incompatible
    # corpora share an identity — which is how the embedding library was missed.
    import dataclasses

    from jackryan.config import DEFAULT_CONTRACT

    fields = {f.name for f in dataclasses.fields(Contract)}
    assert fields == set(DEFAULT_CONTRACT), (
        "Contract fields and DEFAULT_CONTRACT keys have drifted apart"
    )
    fingerprint = Contract().fingerprint()
    for name in fields:
        assert f"{name}=" in fingerprint, f"{name} is declared but not in the fingerprint"
