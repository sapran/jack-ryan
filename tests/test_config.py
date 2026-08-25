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
