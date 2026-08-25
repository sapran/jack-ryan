"""Layered configuration: a corpus-coupled contract plus swappable profiles.

Two layers with different lifetimes:

* ``contract`` is corpus-coupled. Changing any value invalidates an existing
  corpus and forces a reingest, so it is frozen once documents exist.
* ``profiles`` are swappable infrastructure. Changing one is always safe.

Precedence is: real environment variable > ``config.yaml`` > built-in default.
Configuration fails loudly at boot — an unknown profile or an unresolvable
secret is fatal, never silently replaced by a default.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .errors import ConfigError

_ENV_PLACEHOLDER = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")

# Every value here is consumed by chunking or by embedding. Nothing decorative
# belongs in the contract: the fingerprint must cover exactly what determines
# corpus identity, so that a change to it is always a real incompatibility.
DEFAULT_CONTRACT: dict[str, Any] = {
    "chunk_max_chars": 2000,
    "chunk_overlap_chars": 200,
    "embed_model": "intfloat/multilingual-e5-large",
    "embed_dimensions": 1024,
}


@dataclass(frozen=True)
class Contract:
    """Corpus-coupled settings. Changing any of these forces a reingest."""

    chunk_max_chars: int = DEFAULT_CONTRACT["chunk_max_chars"]
    chunk_overlap_chars: int = DEFAULT_CONTRACT["chunk_overlap_chars"]
    embed_model: str = DEFAULT_CONTRACT["embed_model"]
    embed_dimensions: int = DEFAULT_CONTRACT["embed_dimensions"]

    def fingerprint(self) -> str:
        """A stable identity for this contract.

        The store records it at creation; a mismatch at boot means the corpus
        on disk was built under different rules and must not be appended to.
        """
        parts = (
            f"chunk_max_chars={self.chunk_max_chars}",
            f"chunk_overlap_chars={self.chunk_overlap_chars}",
            f"embed_model={self.embed_model}",
            f"embed_dimensions={self.embed_dimensions}",
        )
        return "|".join(parts)


@dataclass(frozen=True)
class Profile:
    """Swappable infrastructure for one deployment shape."""

    name: str
    llm_url: str = ""
    embed_url: str = ""
    api_key: str = ""
    embedder: str = "model"
    """Which embedder to construct: ``model`` (the real one) or ``deterministic``.

    ``deterministic`` exists for tests and produces vectors that carry no
    meaning, so it is never selected implicitly.
    """


@dataclass(frozen=True)
class Config:
    contract: Contract
    profile: Profile
    data_dir: Path
    available_profiles: tuple[str, ...] = field(default=())

    @property
    def db_path(self) -> Path:
        return self.data_dir / "jackryan.db"


def _interpolate(value: Any) -> Any:
    """Resolve ``${VAR}`` placeholders from the environment.

    An unset variable is fatal rather than an empty string: a secret that
    silently resolves to nothing produces a confusing downstream failure.
    """
    if not isinstance(value, str):
        return value

    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        resolved = os.environ.get(name)
        if resolved is None:
            raise ConfigError(
                f"config references ${{{name}}} but that environment variable is not set"
            )
        return resolved

    return _ENV_PLACEHOLDER.sub(replace, value)


def _load_file(path: Path) -> dict[str, Any]:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigError(f"JACKRYAN_CONFIG points at {path}, which does not exist") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path} is not valid YAML: {exc}") from exc

    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ConfigError(f"{path} must contain a YAML mapping at the top level")
    return raw


def _select_profile(document: dict[str, Any]) -> Profile:
    """Pick the profile, config-authoritative.

    A non-empty ``JACKRYAN_PROFILE`` wins; otherwise ``default_profile``;
    otherwise the built-in ``local``. An unknown name is fatal and names both
    what was asked for and what exists, because guessing here would run the
    instance against unintended infrastructure.
    """
    profiles = document.get("profiles") or {}
    if not isinstance(profiles, dict):
        raise ConfigError("`profiles` must be a mapping of profile name to settings")

    requested = os.environ.get("JACKRYAN_PROFILE", "").strip()
    name = requested or str(document.get("default_profile") or "local").strip()

    if not profiles:
        # No profiles declared at all: run fully offline under the name asked for.
        return Profile(name=name)

    if name not in profiles:
        known = ", ".join(sorted(profiles)) or "none"
        source = "JACKRYAN_PROFILE" if requested else "default_profile"
        raise ConfigError(
            f"{source} selects profile {name!r}, which config.yaml does not define "
            f"(defined: {known})"
        )

    settings = profiles[name] or {}
    if not isinstance(settings, dict):
        raise ConfigError(f"profile {name!r} must be a mapping")

    return Profile(
        name=name,
        llm_url=str(_interpolate(settings.get("llm_url", "")) or ""),
        embed_url=str(_interpolate(settings.get("embed_url", "")) or ""),
        api_key=str(_interpolate(settings.get("api_key", "")) or ""),
        embedder=_validated_embedder(settings.get("embedder", "model"), name),
    )


def _validated_embedder(value: Any, profile: str) -> str:
    choice = str(value or "model").strip().lower()
    if choice not in ("model", "deterministic"):
        raise ConfigError(
            f"profile {profile!r} sets embedder={choice!r}; expected 'model' or 'deterministic'"
        )
    return choice


def _build_contract(document: dict[str, Any]) -> Contract:
    declared = document.get("contract") or {}
    if not isinstance(declared, dict):
        raise ConfigError("`contract` must be a mapping")

    unknown = set(declared) - set(DEFAULT_CONTRACT)
    if unknown:
        raise ConfigError(
            "unknown contract key(s): " + ", ".join(sorted(unknown)) +
            ". The contract is corpus-coupled; a typo here would silently change corpus identity."
        )

    values = {**DEFAULT_CONTRACT, **declared}
    try:
        contract = Contract(
            chunk_max_chars=int(values["chunk_max_chars"]),
            chunk_overlap_chars=int(values["chunk_overlap_chars"]),
            embed_model=str(values["embed_model"]),
            embed_dimensions=int(values["embed_dimensions"]),
        )
        if contract.chunk_overlap_chars >= contract.chunk_max_chars:
            raise ConfigError(
                "contract chunk_overlap_chars must be smaller than chunk_max_chars, "
                "otherwise chunking cannot advance through the text"
            )
        if contract.chunk_max_chars < 1 or contract.embed_dimensions < 1:
            raise ConfigError("contract chunk_max_chars and embed_dimensions must be positive")
        return contract
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"contract value is not of the expected type: {exc}") from exc


def load_config(env: dict[str, str] | None = None) -> Config:
    """Assemble the effective configuration.

    ``config.yaml`` is read only when ``JACKRYAN_CONFIG`` is set, so a bare
    checkout runs on built-in defaults with no file at all.
    """
    environ = os.environ if env is None else env
    previous = None
    if env is not None:
        previous, os.environ = os.environ, env  # type: ignore[assignment]

    try:
        document: dict[str, Any] = {}
        config_path = environ.get("JACKRYAN_CONFIG", "").strip()
        if config_path:
            document = _load_file(Path(config_path))

        data_dir = Path(environ.get("JACKRYAN_DATA_DIR", "").strip() or "./data").expanduser()
        profiles = document.get("profiles") or {}
        available = tuple(sorted(profiles)) if isinstance(profiles, dict) else ()

        return Config(
            contract=_build_contract(document),
            profile=_select_profile(document),
            data_dir=data_dir,
            available_profiles=available,
        )
    finally:
        if previous is not None:
            os.environ = previous  # type: ignore[assignment]
