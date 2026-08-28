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
from importlib import metadata
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
    # The library version is corpus-coupled: fastembed changed this model from
    # CLS to mean pooling between 0.5.1 and 0.8.0, which produces vectors of the
    # declared width that are not comparable with the ones already stored. Width
    # and model name cannot tell the two apart, so the version is declared here
    # and checked against what is installed.
    "embed_library": "fastembed==0.8.0",
}


def _escaped(value: Any) -> str:
    """One component's value, made unable to read as another component.

    Corpus identity is `key=value` parts joined with `|`, and it is the one
    string whose entire job is that two different corpora never share it. A
    value carrying a separator would otherwise produce an identity asserting
    something the instance is not configured for: an `embed_model` containing
    `|embedder=model` makes `/health` and the refusal message name an embedder
    that is not in use.

    `=` is deliberately NOT escaped. `embed_library` legitimately contains `==`,
    and since the component keys are fixed identifiers containing no `=`,
    splitting on unescaped `|` and then on the first `=` still round-trips. That
    choice is also what keeps this change from invalidating anything: no value
    that is currently reachable contains `|` or a backslash, so every corpus
    identity recorded before this escaping existed is byte-identical after it.

    Control characters are escaped because an identity is printed by `/health`
    and `jackryan status`, and a value carrying a newline would forge a line in
    output an operator reads to decide what refused them.
    """
    text = str(value)
    text = text.replace("\\", "\\\\").replace("|", "\\|")
    return "".join(
        character if character.isprintable() else f"\\x{ord(character):02x}"
        for character in text
    )


@dataclass(frozen=True)
class Contract:
    """Corpus-coupled settings. Changing any of these forces a reingest."""

    chunk_max_chars: int = DEFAULT_CONTRACT["chunk_max_chars"]
    chunk_overlap_chars: int = DEFAULT_CONTRACT["chunk_overlap_chars"]
    embed_model: str = DEFAULT_CONTRACT["embed_model"]
    embed_dimensions: int = DEFAULT_CONTRACT["embed_dimensions"]
    embed_library: str = DEFAULT_CONTRACT["embed_library"]
    """The embedding library and exact version, as ``<distribution>==<version>``.

    Declared rather than read from the environment so the fingerprint stays a
    written fact reproducible from configuration alone. It is verified against
    the installed distribution at load, which is what makes the declaration
    trustworthy.
    """

    def fingerprint(self) -> str:
        """A stable identity for this contract.

        This is a *component* of corpus identity, not the whole of it: two
        instances can agree on every value here and still fill a corpus with
        vectors that are not comparable, because the contract does not say which
        embedder produced them. See ``corpus_fingerprint``, which is what the
        store records.
        """
        parts = (
            f"chunk_max_chars={_escaped(self.chunk_max_chars)}",
            f"chunk_overlap_chars={_escaped(self.chunk_overlap_chars)}",
            f"embed_model={_escaped(self.embed_model)}",
            f"embed_dimensions={_escaped(self.embed_dimensions)}",
            f"embed_library={_escaped(self.embed_library)}",
        )
        return "|".join(parts)


@dataclass(frozen=True)
class Profile:
    """Swappable infrastructure for one deployment shape."""

    name: str
    llm_url: str = ""
    embed_url: str = ""
    api_key: str = ""
    mcp_allowed_hosts: tuple[str, ...] = (
        "localhost",
        "127.0.0.1",
        "localhost:8500",
        "127.0.0.1:8500",
    )
    """Host headers the agent surface will answer over HTTP.

    The MCP transport rejects unknown hosts to blunt DNS rebinding, which
    matters for a service listening locally. A deployment reached under another
    name has to say so here rather than have the protection turned off for it.
    """

    mcp_profile: str = "readonly"
    """Which agent-facing tool surface to advertise.

    Unrecognised names narrow to the smallest surface rather than widening, so
    a typo costs tools instead of granting them.
    """

    embedder: str = "model"
    """Which embedder to construct: ``model`` (the real one) or ``deterministic``.

    ``deterministic`` exists for tests and produces vectors that carry no
    meaning, so it is never selected implicitly.
    """

    ocr_engine: str = "rapidocr"
    """Which recognition engine reads page images.

    Never ``auto``. Docling's ``auto`` picks by host operating system and drops
    the configured language on the way to the engine it picks, which would make
    the extracted text — and therefore the corpus — a property of the machine
    that ingested it.
    """

    ocr_language: str = "eslav"
    """The recognition model to read pages with, in the engine's own vocabulary.

    ``eslav`` is East Slavic. It reads Ukrainian, Russian and English from one
    page, which is why it is the default rather than a per-language ladder; see
    the change's design document for the measurements.

    One language, not a list: docling's RapidOCR adapter silently keeps the
    first of a list and logs the rest away, so an operator who wrote three would
    have two dropped without knowing.
    """

    min_chars_per_page: int = 100
    """The floor below which extraction escalates to the next rung.

    Per page rather than per document, so it means the same thing for a one-page
    letter and a two-hundred-page report.
    """

    window_max_chars: int = 3000
    """How wide a search result's text may be, in characters.

    A result's text is a window around the matched passage rather than the
    passage alone, so a quotation arrives with the sentences that give it
    meaning. Set at or below the chunk size to switch widening off.

    Retrieval settings live here rather than in the contract because they write
    nothing: no vector, no chunk, no stored text. Changing one changes what the
    next search returns and leaves the corpus exactly as it was, so no store is
    ever refused for them.
    """

    vlm_model: str = ""
    """A docling vision-model spec name, or empty to leave the vision rung off.

    Off by default: it downloads model weights and is slower by a large factor,
    and the two rungs above it handle every document that is not hard.
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


def corpus_fingerprint(contract: Contract, embedder_name: str) -> str:
    """The identity the store records: the contract plus who filled it.

    The contract alone is not enough. The choice between the real embedder and
    the deterministic stand-in lives in the profile layer, which is otherwise
    safe to change, and both produce vectors of the declared width — so a corpus
    filled by one opens under the other with nothing downstream able to tell.
    Real query vectors then get compared against hash vectors. This is the last
    point at which the difference is still visible.

    Composed here rather than by copying the embedder into the contract: two
    copies of one setting can disagree with each other, which is the shape of
    the bug this closes.
    """
    # The contract's fingerprint is already escaped component by component, so
    # it is joined raw; only the embedder's own name needs escaping here.
    # `EmbedderPort.name` is an unvalidated `str`, and a third embedder whose
    # name carried a separator is exactly how the unreachable collision becomes
    # reachable.
    return f"{contract.fingerprint()}|embedder={_escaped(embedder_name)}"


def canonical_embed_library(declared: str) -> tuple[str, str] | None:
    """Split ``declared`` into a normalised ``(distribution, version)``.

    Returns ``None`` when it is not of the form ``<distribution>==<version>``.

    Normalising matters because the value enters the fingerprint: without it
    ``fastembed == 0.8.0`` and ``FASTEMBED==0.8.0`` are one library to the check
    and two different corpora to the store, so tidying whitespace in
    ``config.yaml`` would refuse an operator's own corpus.
    """
    distribution, separator, version = declared.partition("==")
    # PEP 503 name normalisation, so case and separator style do not fork identity.
    distribution = re.sub(r"[-_.]+", "-", distribution.strip().lower())
    version = version.strip()
    if not distribution or not separator or not version:
        return None
    return distribution, version


def _same_release(left: str, right: str) -> bool:
    """Whether two version strings name the same release.

    ``0.8`` and ``0.8.0`` are one release, so a difference in how many zeros the
    operator wrote must not read as a version change. Anything that is not a
    plain dotted number — a release candidate, a ``.post`` rebuild — is compared
    exactly, because guessing at their ordering is how a guard becomes wrong in
    the direction that lets bad vectors through.
    """
    try:
        left_parts = [int(part) for part in left.split(".")]
        right_parts = [int(part) for part in right.split(".")]
    except ValueError:
        return left == right
    width = max(len(left_parts), len(right_parts))
    left_parts += [0] * (width - len(left_parts))
    right_parts += [0] * (width - len(right_parts))
    return left_parts == right_parts


def _wrong_version_message(declared: str, distribution: str, declared_version: str, found: str) -> str:
    return (
        f"contract declares embed_library {declared!r} but {distribution!r} {found} "
        "is in use. These produce vectors of the same width that are not comparable, "
        "which no later check can detect. Either install "
        f"{distribution}=={declared_version}, or set embed_library to "
        f"{distribution}=={found} and reingest every casefile."
    )


def _malformed_message(declared: str) -> str:
    return (
        f"contract embed_library is {declared!r}; expected "
        "'<distribution>==<version>', for example 'fastembed==0.8.0'"
    )


def embed_library_mismatch(declared: str) -> str | None:
    """Describe how ``declared`` disagrees with the *installed* distribution.

    This is the configuration-time check: it reads packaging metadata, which is
    the right question to ask of a config file — "is the thing you declared the
    thing this environment installed?".

    It is deliberately not the only check. Installed metadata says what a package
    manager recorded, not what Python will import; a shadowing copy earlier on
    ``sys.path`` satisfies this and still produces the vectors. The embedder runs
    ``embed_library_running_mismatch`` against the imported module for that
    reason.

    Returns a message rather than raising, because the callers report the same
    fact as different typed errors — ``ConfigError`` at load, ``EmbeddingError``
    where vectors are produced.
    """
    parsed = canonical_embed_library(declared)
    if parsed is None:
        return _malformed_message(declared)
    distribution, declared_version = parsed

    try:
        installed = metadata.version(distribution)
    except metadata.PackageNotFoundError:
        return (
            f"contract declares embed_library {declared!r} but the {distribution!r} "
            "distribution is not installed, so the vectors it would produce cannot "
            "be identified"
        )
    except Exception as exc:  # unusual packaging layouts, not a missing package
        return (
            f"contract declares embed_library {declared!r} but the installed version "
            f"of {distribution!r} could not be read ({type(exc).__name__}: {exc}), so "
            "it cannot be verified"
        )

    # Broken packaging metadata — a .dist-info with no METADATA, or one with no
    # Version: field — makes version() return None rather than raise. Without
    # this branch that None falls through to the comparison and is reported as
    # "fastembed None is installed", telling the operator to reingest every
    # casefile and to write `embed_library: fastembed==None`, which can never
    # match. Unverifiable is its own failure and has to say so.
    if installed is None:
        return (
            f"contract declares embed_library {declared!r} but the installed version "
            f"of {distribution!r} could not be determined — its distribution metadata "
            "is present but unreadable. This is an environment fault, not a version "
            "mismatch: repair or reinstall the distribution. Do not change the "
            "contract, which would refuse your corpus without cause."
        )

    if not _same_release(installed, declared_version):
        return _wrong_version_message(declared, distribution, declared_version, installed)
    return None


def embed_library_running_mismatch(declared: str, running_version: str | None) -> str | None:
    """Describe how ``declared`` disagrees with the *imported module*.

    Packaging metadata records what was installed. This asks the only question
    that decides what the vectors mean: which code is actually loaded. A patched
    checkout, a ``PYTHONPATH`` shadow, an editable install of a fork, or a stale
    ``.dist-info`` left beside a replaced package all satisfy the metadata check
    and produce vectors from a different library.

    A module that exposes no version at all is a refusal, not a pass: an
    unverifiable library is exactly the condition this guard exists for.
    """
    parsed = canonical_embed_library(declared)
    if parsed is None:
        return _malformed_message(declared)
    distribution, declared_version = parsed

    if not running_version:
        return (
            f"contract declares embed_library {declared!r} but the imported "
            f"{distribution!r} module exposes no version, so the vectors it produces "
            "cannot be identified. Ingestion stops rather than storing vectors whose "
            "meaning is unknown."
        )

    if not _same_release(running_version, declared_version):
        return _wrong_version_message(declared, distribution, declared_version, running_version)
    return None


def _canonicalised_embed_library(value: Any) -> str:
    """Store the normalised spelling, so identity is the fact and not the typing.

    A malformed value is left as written rather than mangled here; the mismatch
    check that runs a few lines later reports it with a message that names what
    was expected.
    """
    raw = str(value).strip()
    parsed = canonical_embed_library(raw)
    if parsed is None:
        return raw
    distribution, version = parsed
    return f"{distribution}=={version}"


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

    # A profile key that is silently ignored is the same failure this instance
    # guards against everywhere else: the instance runs, every document ingests,
    # and only the result is wrong. `ocr_langauge: eslav` would leave recognition
    # on its default with nothing said.
    known = set(Profile.__dataclass_fields__) - {"name"}
    # Keys are stringified before sorting: YAML admits non-string keys, and
    # `1: x` in a profile block would otherwise raise a bare TypeError from the
    # join instead of the ConfigError that names the problem.
    unknown = {str(key) for key in settings} - known
    if unknown:
        raise ConfigError(
            f"profile {name!r} sets unknown key(s): " + ", ".join(sorted(unknown)) +
            ". Known keys: " + ", ".join(sorted(known))
        )

    return Profile(
        name=name,
        llm_url=str(_interpolate(settings.get("llm_url", "")) or ""),
        embed_url=str(_interpolate(settings.get("embed_url", "")) or ""),
        api_key=str(_interpolate(settings.get("api_key", "")) or ""),
        embedder=_validated_embedder(settings.get("embedder", "model"), name),
        mcp_profile=str(settings.get("mcp_profile", "readonly") or "readonly").strip().lower(),
        mcp_allowed_hosts=_validated_hosts(settings.get("mcp_allowed_hosts"), name),
        ocr_engine=_validated_ocr_engine(settings.get("ocr_engine"), name),
        ocr_language=_validated_ocr_language(settings.get("ocr_language"), name),
        min_chars_per_page=_validated_floor(settings.get("min_chars_per_page"), name),
        window_max_chars=_validated_positive(
            settings.get("window_max_chars"), name, "window_max_chars", Profile.window_max_chars
        ),
        vlm_model=str(_interpolate(settings.get("vlm_model", "")) or "").strip(),
    )


def _validated_hosts(value: Any, profile: str) -> tuple[str, ...]:
    if value is None:
        return Profile.__dataclass_fields__["mcp_allowed_hosts"].default
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, (list, tuple)) or not all(isinstance(v, str) for v in value):
        raise ConfigError(
            f"profile {profile!r} sets mcp_allowed_hosts to something other than a list of names"
        )
    cleaned = tuple(str(_interpolate(v)).strip() for v in value if str(v).strip())
    if not cleaned:
        raise ConfigError(
            f"profile {profile!r} sets an empty mcp_allowed_hosts; the agent surface would "
            "answer nothing over HTTP"
        )
    return cleaned


RECOGNITION_ENGINES = ("rapidocr", "easyocr", "tesseract", "ocrmac")
"""Engines a profile may name.

``auto`` is deliberately absent; it is refused with its own message below, since
"unknown engine" would not tell an operator why the one docling documents is the
one they cannot have.
"""


def _validated_ocr_engine(value: Any, profile: str) -> str:
    if value is None:
        return Profile.ocr_engine
    choice = str(_interpolate(value)).strip().lower()
    if not choice:
        # An empty value used to fall through to the default. Its sibling
        # ocr_language treats empty as fatal, and an operator who blanked a
        # setting meant something by it — silently restoring the default is the
        # quiet-substitution this loader exists to refuse.
        raise ConfigError(
            f"profile {profile!r} sets an empty ocr_engine; name one of "
            f"{', '.join(RECOGNITION_ENGINES)}, or remove the key to take the default"
        )
    if choice == "auto":
        raise ConfigError(
            f"profile {profile!r} sets ocr_engine='auto'. The recognition engine must be "
            "named: 'auto' picks by host operating system and discards the configured "
            "language, so the same evidence read on two machines would produce two "
            f"different corpora. Name one of: {', '.join(RECOGNITION_ENGINES)}."
        )
    if choice not in RECOGNITION_ENGINES:
        raise ConfigError(
            f"profile {profile!r} sets ocr_engine={choice!r}; expected one of "
            f"{', '.join(RECOGNITION_ENGINES)}"
        )
    return choice


def _validated_ocr_language(value: Any, profile: str) -> str:
    """Take exactly one language.

    Whether the engine can serve it is settled when the engine is built, which
    is the only place that can answer authoritatively. This checks the shape: a
    list would be silently reduced to its first element by docling's RapidOCR
    adapter, leaving an operator who wrote three languages reading one.
    """
    if isinstance(value, (list, tuple, set)):
        raise ConfigError(
            f"profile {profile!r} sets ocr_language to a list. The engine recognises one "
            "language at a time and would keep only the first, so name the single one to "
            "use — 'eslav' reads Ukrainian, Russian and English together."
        )
    choice = str(_interpolate(value) if value is not None else Profile.ocr_language).strip()
    if not choice:
        raise ConfigError(
            f"profile {profile!r} sets an empty ocr_language; scans would be read with no "
            "recognition model named"
        )
    return choice


def _validated_floor(value: Any, profile: str) -> int:
    """The floor, which must be at least one character per page.

    Zero is refused, not accepted. `clears_floor` compares with `>=`, so a floor
    of zero is cleared by every reading including an empty one: the first rung
    always wins, recognition never runs, and every scan is then refused as
    having no usable text. That is the whole capability switched off by a value
    that looks like "no minimum", which is exactly the quiet misconfiguration
    this loader exists to refuse. A negative floor behaves identically and was
    already refused; the two now give the same answer.

    A fractional value is refused rather than truncated, because `int(0.5)` is
    zero and would reach the same silent disabling by a different route.
    """
    if value is None:
        return Profile.min_chars_per_page
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ConfigError(
            f"profile {profile!r} sets min_chars_per_page={value!r}, which is not a number"
        )
    try:
        floor = int(str(value).strip())
    except (TypeError, ValueError):
        raise ConfigError(
            f"profile {profile!r} sets min_chars_per_page={value!r}; expected a whole "
            "number of characters per page"
        ) from None
    if floor < 1:
        raise ConfigError(
            f"profile {profile!r} sets min_chars_per_page={floor}. A floor below one is "
            "cleared by every reading, including an empty one, so the first rung always "
            "wins, recognition never runs, and every scan is refused as having no usable "
            "text. Use 1 to escalate only a page with nothing on it at all."
        )
    return floor


def _validated_positive(value: Any, profile: str, key: str, default: int) -> int:
    """A whole number of at least one, refused rather than coerced.

    Zero is the interesting case. It reads as "no limit" and would behave as its
    opposite — a window of no characters, a rerank pool of nothing — which is the
    quiet misconfiguration this loader exists to refuse. A fractional value is
    refused for the same reason `min_chars_per_page` refuses one: `int(0.5)` is
    zero and reaches the same place by another route.
    """
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ConfigError(f"profile {profile!r} sets {key}={value!r}, which is not a number")
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError):
        raise ConfigError(
            f"profile {profile!r} sets {key}={value!r}; expected a whole number"
        ) from None
    if number < 1:
        raise ConfigError(
            f"profile {profile!r} sets {key}={number}. A value below one disables the "
            "setting while reading as though it removed a limit; leave the key out to "
            "take the default."
        )
    return number


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
            embed_library=_canonicalised_embed_library(values["embed_library"]),
        )
        if contract.chunk_overlap_chars >= contract.chunk_max_chars:
            raise ConfigError(
                "contract chunk_overlap_chars must be smaller than chunk_max_chars, "
                "otherwise chunking cannot advance through the text"
            )
        if contract.chunk_max_chars < 1 or contract.embed_dimensions < 1:
            raise ConfigError("contract chunk_max_chars and embed_dimensions must be positive")
        mismatch = embed_library_mismatch(contract.embed_library)
        if mismatch:
            raise ConfigError(mismatch)
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
