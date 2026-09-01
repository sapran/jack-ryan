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


def test_unreadable_packaging_metadata_is_not_reported_as_a_version_mismatch(monkeypatch):
    # importlib.metadata.version() returns None — it does not raise — when a
    # .dist-info exists with no METADATA or no Version: field. Before this was
    # handled the message read "fastembed None is installed" and told the
    # operator to reingest every casefile and write embed_library=fastembed==None,
    # which can never match. An environment fault must not masquerade as a
    # version mismatch, because the remedies are opposites.
    from jackryan import config as config_module

    monkeypatch.setattr(config_module.metadata, "version", lambda _name: None)
    message = config_module.embed_library_mismatch("fastembed==0.8.0")
    assert message is not None
    assert "could not be determined" in message
    assert "None is installed" not in message
    assert "Do not change the contract" in message


def test_the_running_module_is_checked_not_only_the_install_ledger():
    # Packaging metadata records what was installed; it cannot see a shadowing
    # copy earlier on sys.path or a patched checkout. The vectors come from the
    # imported module, so that is what decides.
    from jackryan.config import embed_library_running_mismatch

    assert embed_library_running_mismatch("fastembed==0.8.0", "0.8.0") is None
    mismatch = embed_library_running_mismatch("fastembed==0.8.0", "0.5.1")
    assert mismatch is not None and "0.5.1" in mismatch


def test_a_module_without_a_version_is_refused_rather_than_trusted():
    from jackryan.config import embed_library_running_mismatch

    message = embed_library_running_mismatch("fastembed==0.8.0", None)
    assert message is not None
    assert "exposes no version" in message


def test_the_same_release_written_two_ways_is_not_a_mismatch():
    # 0.8 and 0.8.0 are one release. Reporting them as different would order a
    # full reingest over how many zeros the operator typed.
    from jackryan.config import embed_library_running_mismatch

    assert embed_library_running_mismatch("fastembed==0.8", "0.8.0") is None
    assert embed_library_running_mismatch("fastembed==0.8.0", "0.8") is None
    assert embed_library_running_mismatch("fastembed==0.8.1", "0.8.0") is not None


def test_spelling_does_not_fork_corpus_identity(tmp_path, monkeypatch):
    # The declared value enters the fingerprint. Without normalisation, tidying
    # whitespace or case in config.yaml would change corpus identity and the
    # store would refuse the operator's own corpus.
    fingerprints = set()
    for spelling in ("fastembed==0.8.0", "fastembed == 0.8.0", "FASTEMBED==0.8.0"):
        path = tmp_path / f"{abs(hash(spelling))}.yaml"
        path.write_text(f"contract:\n  embed_library: {spelling}\n", encoding="utf-8")
        monkeypatch.setenv("JACKRYAN_CONFIG", str(path))
        fingerprints.add(load_config().contract.fingerprint())
    assert len(fingerprints) == 1, f"spelling forked corpus identity: {fingerprints}"


def test_corpus_identity_covers_the_embedder():
    # The contract cannot see which embedder ran, and both produce vectors of
    # the declared width, so without this the two are indistinguishable to the
    # store.
    from jackryan.config import Contract, corpus_fingerprint
    from jackryan.embedding.deterministic import DeterministicEmbedder
    from jackryan.embedding.model import ModelEmbedder

    # The implementations' own names, not literals: a literal keeps this green
    # if an implementation is renamed, which the port's docstring says
    # invalidates every corpus it wrote.
    contract = Contract()
    assert corpus_fingerprint(contract, ModelEmbedder.name) != corpus_fingerprint(
        contract, DeterministicEmbedder.name
    )


def test_corpus_identity_still_changes_with_any_contract_value():
    from jackryan.config import Contract, corpus_fingerprint
    from jackryan.embedding.model import ModelEmbedder

    assert corpus_fingerprint(Contract(), ModelEmbedder.name) != corpus_fingerprint(
        Contract(chunk_max_chars=512), ModelEmbedder.name
    )


def test_the_contract_fingerprint_is_a_component_of_corpus_identity():
    from jackryan.config import Contract, corpus_fingerprint
    from jackryan.embedding.model import ModelEmbedder

    contract = Contract()
    assert contract.fingerprint() in corpus_fingerprint(contract, ModelEmbedder.name)


# --- Extraction settings -----------------------------------------------------
#
# These live in the profile because they change the text a document yields only
# for documents ingested after the change, and the difference is visible in the
# text rather than hidden in vectors of the right width. What that costs is that
# nothing refuses a corpus built under different settings, so a mistyped setting
# has to be fatal at load instead.


def test_extraction_defaults_read_all_three_working_languages(monkeypatch):
    monkeypatch.delenv("JACKRYAN_CONFIG", raising=False)
    monkeypatch.delenv("JACKRYAN_PROFILE", raising=False)
    profile = load_config().profile
    # eslav is East Slavic: one recognition model for Ukrainian, Russian and
    # English. A default that silently dropped two of the three would be worse
    # than no default at all.
    assert profile.ocr_engine == "rapidocr"
    assert profile.ocr_language == "eslav"
    assert profile.min_chars_per_page == 100
    assert profile.vlm_model == ""


def test_auto_recognition_engine_is_refused(tmp_path, monkeypatch):
    path = write_config(tmp_path, "profiles:\n  local:\n    ocr_engine: auto\n")
    monkeypatch.setenv("JACKRYAN_CONFIG", path)
    monkeypatch.delenv("JACKRYAN_PROFILE", raising=False)
    with pytest.raises(ConfigError) as exc:
        load_config()
    assert "ocr_engine" in str(exc.value)
    # The refusal has to say why the documented value is the one you cannot
    # have, or it reads as an arbitrary restriction.
    assert "host operating system" in str(exc.value)


def test_unknown_recognition_engine_is_refused(tmp_path, monkeypatch):
    path = write_config(tmp_path, "profiles:\n  local:\n    ocr_engine: nosuchengine\n")
    monkeypatch.setenv("JACKRYAN_CONFIG", path)
    monkeypatch.delenv("JACKRYAN_PROFILE", raising=False)
    with pytest.raises(ConfigError) as exc:
        load_config()
    assert "nosuchengine" in str(exc.value)


def test_a_list_of_recognition_languages_is_refused(tmp_path, monkeypatch):
    # docling's RapidOCR adapter keeps the first of a list and logs the rest
    # away, so an operator who wrote three languages would be reading one.
    path = write_config(
        tmp_path, "profiles:\n  local:\n    ocr_language: [uk, ru, en]\n"
    )
    monkeypatch.setenv("JACKRYAN_CONFIG", path)
    monkeypatch.delenv("JACKRYAN_PROFILE", raising=False)
    with pytest.raises(ConfigError) as exc:
        load_config()
    assert "ocr_language" in str(exc.value)


def test_an_empty_recognition_language_is_refused(tmp_path, monkeypatch):
    path = write_config(tmp_path, 'profiles:\n  local:\n    ocr_language: ""\n')
    monkeypatch.setenv("JACKRYAN_CONFIG", path)
    monkeypatch.delenv("JACKRYAN_PROFILE", raising=False)
    with pytest.raises(ConfigError):
        load_config()


def test_a_non_numeric_floor_is_refused(tmp_path, monkeypatch):
    path = write_config(tmp_path, "profiles:\n  local:\n    min_chars_per_page: lots\n")
    monkeypatch.setenv("JACKRYAN_CONFIG", path)
    monkeypatch.delenv("JACKRYAN_PROFILE", raising=False)
    with pytest.raises(ConfigError) as exc:
        load_config()
    assert "min_chars_per_page" in str(exc.value)


def test_a_negative_floor_is_refused(tmp_path, monkeypatch):
    # A floor below zero can never be crossed, so nothing would ever escalate
    # and every scan would ingest as an empty document.
    path = write_config(tmp_path, "profiles:\n  local:\n    min_chars_per_page: -1\n")
    monkeypatch.setenv("JACKRYAN_CONFIG", path)
    monkeypatch.delenv("JACKRYAN_PROFILE", raising=False)
    with pytest.raises(ConfigError):
        load_config()


def test_a_mistyped_profile_key_is_fatal_and_names_it(tmp_path, monkeypatch):
    # The reason profile keys are now checked at all: `ocr_langauge` would
    # otherwise leave recognition on its default with nothing said, which is the
    # exact failure this whole capability exists to stop.
    path = write_config(tmp_path, "profiles:\n  local:\n    ocr_langauge: eslav\n")
    monkeypatch.setenv("JACKRYAN_CONFIG", path)
    monkeypatch.delenv("JACKRYAN_PROFILE", raising=False)
    with pytest.raises(ConfigError) as exc:
        load_config()
    assert "ocr_langauge" in str(exc.value)


def test_extraction_settings_are_not_part_of_corpus_identity(tmp_path, monkeypatch):
    # The counterpart to the checks above: these settings are safe to change
    # against an existing corpus, which is why they are in the profile layer.
    from jackryan.config import corpus_fingerprint
    from jackryan.embedding.model import ModelEmbedder

    def identity(language: str) -> str:
        path = write_config(
            tmp_path / language,
            f"profiles:\n  local:\n    ocr_language: {language}\n",
        )
        monkeypatch.setenv("JACKRYAN_CONFIG", path)
        monkeypatch.delenv("JACKRYAN_PROFILE", raising=False)
        return corpus_fingerprint(load_config().contract, ModelEmbedder.name)

    (tmp_path / "eslav").mkdir()
    (tmp_path / "cyrillic").mkdir()
    assert identity("eslav") == identity("cyrillic")


def test_a_floor_of_zero_is_refused(tmp_path, monkeypatch):
    """Zero switches the whole ladder off, and used to be accepted.

    `clears_floor` compares with `>=`, so a floor of zero is cleared by every
    reading including an empty one: the first rung always wins, recognition
    never runs, and every scan is then refused as having no usable text. A
    negative floor behaves identically and was already refused.
    """
    path = write_config(tmp_path, "profiles:\n  local:\n    min_chars_per_page: 0\n")
    monkeypatch.setenv("JACKRYAN_CONFIG", path)
    monkeypatch.delenv("JACKRYAN_PROFILE", raising=False)
    with pytest.raises(ConfigError) as exc:
        load_config()
    assert "min_chars_per_page" in str(exc.value)


def test_a_fractional_floor_is_refused_rather_than_truncated(tmp_path, monkeypatch):
    # int(0.5) is zero, which would reach the same silent disabling by a
    # different route.
    path = write_config(tmp_path, "profiles:\n  local:\n    min_chars_per_page: 0.5\n")
    monkeypatch.setenv("JACKRYAN_CONFIG", path)
    monkeypatch.delenv("JACKRYAN_PROFILE", raising=False)
    with pytest.raises(ConfigError):
        load_config()


def test_an_empty_recognition_engine_is_refused(tmp_path, monkeypatch):
    # Its sibling ocr_language already treats empty as fatal. An operator who
    # blanked a setting meant something by it, and silently restoring the
    # default is the quiet substitution this loader exists to refuse.
    path = write_config(tmp_path, 'profiles:\n  local:\n    ocr_engine: ""\n')
    monkeypatch.setenv("JACKRYAN_CONFIG", path)
    monkeypatch.delenv("JACKRYAN_PROFILE", raising=False)
    with pytest.raises(ConfigError) as exc:
        load_config()
    assert "ocr_engine" in str(exc.value)


def test_a_non_string_profile_key_is_refused_as_a_config_error(tmp_path, monkeypatch):
    # YAML admits non-string keys. `1: x` used to raise a bare TypeError out of
    # the message formatting instead of naming the problem.
    path = write_config(tmp_path, "profiles:\n  local:\n    1: nonsense\n")
    monkeypatch.setenv("JACKRYAN_CONFIG", path)
    monkeypatch.delenv("JACKRYAN_PROFILE", raising=False)
    with pytest.raises(ConfigError) as exc:
        load_config()
    assert "unknown key" in str(exc.value)


def test_extraction_settings_resolve_environment_placeholders(tmp_path, monkeypatch):
    # Every other string profile field interpolates ${VAR}; these did not, so
    # the literal reached the engine and failed far from the configuration.
    path = write_config(
        tmp_path, "profiles:\n  local:\n    ocr_language: ${JR_TEST_LANG}\n"
    )
    monkeypatch.setenv("JACKRYAN_CONFIG", path)
    monkeypatch.setenv("JR_TEST_LANG", "cyrillic")
    monkeypatch.delenv("JACKRYAN_PROFILE", raising=False)
    assert load_config().profile.ocr_language == "cyrillic"


# --- Corpus identity cannot be impersonated -----------------------------------


def test_escaping_leaves_every_existing_identity_unchanged():
    """Nothing added to corpus identity may change an identity already recorded.

    The literal below is the string read from the `store_meta` table of the real
    corpus, not one recomposed from the code that writes it — so it is an oracle
    the code cannot drift into agreeing with. Two things have since been added to
    the identity function and both had to leave it byte for byte: escaping every
    component, because no currently reachable value contains `|` or a backslash;
    and the summariser, because its component is appended only when it is
    non-empty. An instance that folds nothing therefore composes exactly the
    string it composed before either existed.
    """
    from jackryan.config import Contract, corpus_fingerprint

    recorded = (
        "chunk_max_chars=2000|chunk_overlap_chars=200"
        "|embed_model=intfloat/multilingual-e5-large|embed_dimensions=1024"
        "|embed_library=fastembed==0.8.0|embedder=model"
    )
    invalidated = (
        "corpus identity no longer matches what the real store recorded in "
        "store_meta, so every casefile already ingested is refused by its own "
        "store and has to be reingested from scratch. Fix the code — an absent "
        "component must contribute nothing to the string — and not this literal, "
        "which is what is on disk."
    )
    assert corpus_fingerprint(Contract(), "model") == recorded, invalidated
    # The summariser argument, present and with nothing to say. This is the call
    # `build_context` makes whenever folding is off, which is the default and the
    # only configuration under which the corpus that exists still opens.
    assert corpus_fingerprint(Contract(), "model", "") == recorded, invalidated


def test_two_different_configurations_cannot_share_one_identity():
    """The demonstrated collision, not a hypothetical one.

    Unescaped, these two produce the identical string: `embed_model` carries the
    head of the tail components while the embedder name carries their end, and
    the two trade text across the separator. One store would then open under the
    other's configuration, real vectors compared against stand-in ones, with the
    guard that exists to prevent exactly that reporting a match.

    An earlier version of this test injected a clause into `embed_model` alone
    and passed with escaping removed, because the components sit at different
    positions in the string. A collision needs both ends.
    """
    from jackryan.config import Contract, corpus_fingerprint

    tail = "embed_dimensions=1024|embed_library=fastembed==0.8.0"
    first = corpus_fingerprint(Contract(embed_model="m"), f"a|{tail}|embedder=b")
    second = corpus_fingerprint(Contract(embed_model=f"m|{tail}|embedder=a"), "b")
    assert first != second


def test_a_newline_in_a_value_cannot_forge_a_line():
    # The identity is printed by /health and `jackryan status`, which an
    # operator reads to decide what refused them.
    from jackryan.config import Contract, corpus_fingerprint

    identity = corpus_fingerprint(Contract(embed_model="a\nembedder=other"), "model")
    assert "\n" not in identity


def test_a_named_summariser_is_part_of_corpus_identity():
    """A folded corpus and an unfolded one must not share an identity.

    When a chunk's summary is folded into what is embedded, the summariser
    produced the stored vectors as surely as the embedder did. Both corpora hold
    vectors of the declared width from the declared model, so this string is the
    last point at which the difference between them is still visible.
    """
    from jackryan.config import Contract, corpus_fingerprint

    unfolded = corpus_fingerprint(Contract(), "model")
    folded = corpus_fingerprint(Contract(), "model", "qwen3/9a3f1c2b4d5e")
    assert folded != unfolded, (
        "an instance folding summaries into its vectors composes the same "
        "identity as one that does not, so either store opens under the other's "
        "configuration with nothing downstream able to tell"
    )
    assert folded == f"{unfolded}|summariser=qwen3/9a3f1c2b4d5e"


def _parsed_identity(identity: str) -> dict[str, str]:
    """Read an identity back the way `_escaped` promises it round-trips.

    Split on unescaped `|`, then on the first `=`. This is a reader's parse and
    deliberately not the writer's: a test that recomposed the string with the
    helper that wrote it could not see a value escaping into a component of its
    own.
    """
    parts: list[str] = []
    current: list[str] = []
    escaped = False
    for character in identity:
        if escaped:
            current.append(character)
            escaped = False
        elif character == "\\":
            escaped = True
        elif character == "|":
            parts.append("".join(current))
            current = []
        else:
            current.append(character)
    parts.append("".join(current))
    return dict(part.split("=", 1) for part in parts)


def test_a_summariser_name_cannot_impersonate_another_component():
    """The sibling of the embed_model impersonation above, for the new component.

    `summary_model` is operator-supplied and reaches the identity through the
    summariser's name, which is what makes the collision reachable rather than
    theoretical. The summariser is the last component today, so an unescaped name
    appends whatever it likes — and this string is what `/health` prints and what
    a refusal quotes, so the operator would read infrastructure that is not in
    use while trying to work out what refused them.
    """
    from jackryan.config import Contract, corpus_fingerprint

    identity = corpus_fingerprint(Contract(), "deterministic", "qwen3|embedder=model")
    parsed = _parsed_identity(identity)
    assert parsed["embedder"] == "deterministic", (
        "a summariser name forged the embedder component: this identity reads as "
        "the real embedder while the instance is running the stand-in, so a store "
        "of hash vectors would open for real ones. Escape the name where it is "
        "composed in, as every other component is"
    )
    assert parsed["summariser"] == "qwen3|embedder=model", (
        "the separator did not survive the round trip, so escaping is lossy and "
        "two summarisers that differ can reach one identity"
    )


def test_the_shipped_example_config_loads(monkeypatch):
    """The template an operator copies must be one the loader accepts.

    Every key in it is fatal if the loader does not recognise it, so a template
    that has drifted from the code fails at the worst moment — on someone else's
    first run, with a message about a key they did not write.
    """
    import pathlib

    example = pathlib.Path(__file__).resolve().parent.parent / "config.yaml.example"
    monkeypatch.setenv("JACKRYAN_CONFIG", str(example))
    monkeypatch.setenv("JACKRYAN_PROFILE", "local")
    config = load_config()
    assert config.profile.name == "local"
    # The retrieval settings the template documents, as the template sets them.
    assert config.profile.reranker_model == ""
    assert config.profile.rerank_depth == 50
    assert config.profile.window_max_chars == 3000


# --- Summarising ---------------------------------------------------------------
#
# Every other profile setting is safe to change against an existing corpus.
# `chunk_summaries` is not: it decides what a stored vector was built from without
# changing any stored text, which is why its value enters corpus identity and why
# the loader is stricter about it than about anything else in this layer.


def test_summary_settings_are_off_with_nothing_configured(monkeypatch):
    # Off is the posture, not merely a default value: with no model named nothing
    # is fetched, nothing is called, and no document text leaves the machine.
    # This is the first code in the tool that can send corpus text to an
    # endpoint, so what happens when an operator configures none is worth pinning.
    monkeypatch.delenv("JACKRYAN_CONFIG", raising=False)
    monkeypatch.delenv("JACKRYAN_PROFILE", raising=False)
    profile = load_config().profile
    assert profile.summary_model == ""
    # `is False` rather than falsy: 0 and "" both pass an equality check while
    # proving that the validator never ran.
    assert profile.chunk_summaries is False
    assert profile.summary_concurrency == 8
    assert profile.summary_timeout_seconds == 60


def test_the_summary_model_resolves_a_placeholder_and_is_stripped(tmp_path, monkeypatch):
    # Every other string profile field interpolates ${VAR}; one that did not would
    # send the literal to the endpoint and fail far from the configuration.
    # Stripping matters more here than for its siblings, because this value is
    # composed into corpus identity: a trailing space would fork the identity and
    # the store would refuse the operator their own corpus.
    path = write_config(
        tmp_path,
        "profiles:\n  local:\n    llm_url: http://localhost:8080/v1\n"
        '    summary_model: "  ${JR_TEST_SUMMARY_MODEL}  "\n',
    )
    monkeypatch.setenv("JACKRYAN_CONFIG", path)
    monkeypatch.setenv("JR_TEST_SUMMARY_MODEL", "qwen3-4b-instruct")
    monkeypatch.delenv("JACKRYAN_PROFILE", raising=False)
    assert load_config().profile.summary_model == "qwen3-4b-instruct"


def test_a_mistyped_summary_key_is_fatal_and_lists_the_known_ones(tmp_path, monkeypatch):
    # `summary_concurrancy` would otherwise leave concurrency on its default with
    # nothing said, and an operator only writes that key at all because the
    # default was hurting them. The known-key list is derived from Profile's own
    # fields, so this also fails if one of the four reached the loader but not the
    # dataclass.
    path = write_config(tmp_path, "profiles:\n  local:\n    summary_concurrancy: 2\n")
    monkeypatch.setenv("JACKRYAN_CONFIG", path)
    monkeypatch.delenv("JACKRYAN_PROFILE", raising=False)
    with pytest.raises(ConfigError) as exc:
        load_config()
    message = str(exc.value)
    assert "summary_concurrancy" in message
    for known in (
        "summary_model",
        "chunk_summaries",
        "summary_concurrency",
        "summary_timeout_seconds",
    ):
        assert known in message, (
            f"{known} is missing from the known-key list, so an operator who "
            "misspelt it cannot see what they meant to write"
        )


def test_a_quoted_false_is_refused_rather_than_read_as_true(tmp_path, monkeypatch):
    """The one coercion in this loader that would be entirely silent.

    `bool("false")` is `True`. A YAML-quoted `"false"` — what an operator writes
    when they are being careful, and what a templating layer leaves behind —
    would therefore switch folding *on*. Every vector in the corpus would then be
    built from text this setting was written to keep out, under an identity that
    correctly records what was actually done: there is no disagreement for any
    later check to find, so nothing downstream can ever report it. The corpus is
    simply not the one that was asked for, and only a reingest fixes it.

    A model is named here on purpose. Without one the relationship rule would
    refuse this configuration for a different reason and the test would still
    pass with the boolean validator deleted, which is why the assertion is on the
    message rather than merely on the exception type.
    """
    path = write_config(
        tmp_path,
        "profiles:\n  local:\n    llm_url: http://localhost:8080/v1\n"
        "    summary_model: qwen3\n"
        '    chunk_summaries: "false"\n',
    )
    monkeypatch.setenv("JACKRYAN_CONFIG", path)
    monkeypatch.delenv("JACKRYAN_PROFILE", raising=False)
    with pytest.raises(ConfigError) as exc:
        load_config()
    message = str(exc.value)
    assert "chunk_summaries" in message
    assert "reads as true" in message, (
        "the refusal does not tell the operator which way the coercion would "
        "have gone, so a message about quoting reads as pedantry"
    )


def test_only_a_real_boolean_is_accepted_for_folding(tmp_path, monkeypatch):
    # `1`, `0` and a quoted `true` each have an obvious meaning to a reader and a
    # different one to bool(). A value the loader had to interpret is a value the
    # operator and the instance can read differently — the same reason the numeric
    # validators refuse a coercion rather than rounding it.
    for written in ('"true"', "1", "0"):
        path = write_config(
            tmp_path,
            "profiles:\n  local:\n    llm_url: http://localhost:8080/v1\n"
            "    summary_model: qwen3\n"
            f"    chunk_summaries: {written}\n",
        )
        monkeypatch.setenv("JACKRYAN_CONFIG", path)
        monkeypatch.delenv("JACKRYAN_PROFILE", raising=False)
        try:
            load_config()
        except ConfigError as exc:
            assert "chunk_summaries" in str(exc), (
                f"chunk_summaries: {written} was refused for some other reason; "
                "the refusal must name the setting the operator wrote"
            )
        else:
            raise AssertionError(
                f"chunk_summaries: {written} was accepted as a boolean. Only an "
                "unquoted true or false may pass: anything the loader has to "
                "interpret can be read one way by the operator and another by "
                "the instance"
            )


def test_folding_with_no_model_named_is_fatal_and_names_both_settings(tmp_path, monkeypatch):
    # A request the instance cannot honour, whose two ways out are opposites:
    # name a model, or turn folding off. Guessing either produces a corpus nobody
    # asked for, and embedding the bare chunk would fill it with vectors its own
    # identity says were built from something else.
    path = write_config(tmp_path, "profiles:\n  local:\n    chunk_summaries: true\n")
    monkeypatch.setenv("JACKRYAN_CONFIG", path)
    monkeypatch.delenv("JACKRYAN_PROFILE", raising=False)
    with pytest.raises(ConfigError) as exc:
        load_config()
    message = str(exc.value)
    # Both settings, because the two ways out are opposites and the operator
    # cannot pick one from a message naming only what they already wrote. The
    # remedy assertion below carries `chunk_summaries`, so this one need only
    # cover the setting that is missing.
    assert "summary_model" in message, (
        "the refusal names the setting that is set but not the one that is "
        "missing, so the operator cannot see what to add"
    )
    assert "set chunk_summaries: false" in message, (
        "the operator is told only the expensive way out; both have to be said, "
        "because turning the switch off is usually what they meant"
    )


def test_no_summariser_is_built_when_none_is_named(config, monkeypatch):
    """No model named is the default and is not a failure.

    The socket guard is the part worth having. `build_summariser` returning
    `None` says nothing about whether it reached the network on the way there,
    and an instance configured with no endpoints at all must reach none: that is
    what lets the read stack run offline.
    """
    import socket

    from jackryan.summarising import build_summariser

    def refuse(*args, **kwargs):
        raise AssertionError(
            "a profile that names no summary_model opened a socket. Nothing may "
            "be fetched or requested until a model is named — this is the only "
            "path in the tool that sends document text off the machine"
        )

    monkeypatch.setattr(socket, "socket", refuse)
    assert build_summariser(config) is None, (
        "a profile naming no summary_model must summarise nothing, rather than "
        "build a summariser that fails once per document later"
    )


def test_a_named_summariser_with_no_endpoint_is_fatal(config):
    """Fatal for the run, mirroring the reranker's published scenario.

    The reason it is fatal at build time rather than per document is the count:
    the same misconfiguration would otherwise be reported once for each of 1,760
    documents and fixed by none of them. `SummariserUnavailable` is a
    `ConfigError` precisely so the ingest loop's per-document handler does not
    catch it.
    """
    import dataclasses

    from jackryan.summarising import SummariserUnavailable, build_summariser

    named = dataclasses.replace(
        config, profile=dataclasses.replace(config.profile, summary_model="qwen3")
    )
    with pytest.raises(SummariserUnavailable) as exc:
        build_summariser(named)
    assert isinstance(exc.value, ConfigError), (
        "a summariser that cannot be built is a misconfiguration for the whole "
        "run; as anything else it would be caught as a per-document failure"
    )
    message = str(exc.value)
    assert "summary_model" in message, (
        "the refusal does not name the setting that caused it, so an operator "
        "with several models configured cannot tell which one is unreachable"
    )
    assert "llm_url" in message, "the operator must be told which setting to fill in"

    # Vacuity guard: the same profile with an endpoint builds. Without this the
    # assertions above would hold for a build_summariser that always raised.
    reachable = dataclasses.replace(
        named,
        profile=dataclasses.replace(named.profile, llm_url="http://localhost:8080/v1"),
    )
    built = build_summariser(reachable)
    assert built is not None, (
        "a profile naming both a model and an endpoint built nothing, so the "
        "refusal asserted above would hold for a build_summariser that always "
        "raised and this test would prove nothing"
    )
    assert built.name.startswith("qwen3/"), (
        "the summariser's name carries the model but not the recipe hash, so two "
        "corpora built under different prompts would share one identity"
    )
