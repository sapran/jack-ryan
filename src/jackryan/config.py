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

DEFAULT_CONTRACT: dict[str, Any] = {
    "chunk_size": 1024,
    "chunk_overlap": 0,
    "embed_model_family": "bge-m3",
    "embed_dimensions": 1024,
}


@dataclass(frozen=True)
class Contract:
    """Corpus-coupled settings. Changing any of these forces a reingest."""

    chunk_size: int = DEFAULT_CONTRACT["chunk_size"]
    chunk_overlap: int = DEFAULT_CONTRACT["chunk_overlap"]
    embed_model_family: str = DEFAULT_CONTRACT["embed_model_family"]
    embed_dimensions: int = DEFAULT_CONTRACT["embed_dimensions"]

    def fingerprint(self) -> str:
        """A stable identity for this contract.

        The store records it at creation; a mismatch at boot means the corpus
        on disk was built under different rules and must not be appended to.
        """
        parts = (
            f"chunk_size={self.chunk_size}",
            f"chunk_overlap={self.chunk_overlap}",
            f"embed_model_family={self.embed_model_family}",
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
    )


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
        return Contract(
            chunk_size=int(values["chunk_size"]),
            chunk_overlap=int(values["chunk_overlap"]),
            embed_model_family=str(values["embed_model_family"]),
            embed_dimensions=int(values["embed_dimensions"]),
        )
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
