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
