"""The escalation ladder, tested without a model.

What is worth testing here is the policy — which rung runs, when, and what comes
back — not docling. The rung readers are injected so every case below runs
offline in milliseconds. What only a real model can settle is verified by
`scripts/verify_model_paths.py` and recorded in `docs/handover.md`.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from jackryan.ingestion.quality_gate import (
    OCR,
    TEXT_LAYER,
    VLM,
    QualityGate,
    Reading,
    RecognitionError,
    ocr_options_for,
)

SOMEWHERE = Path("case.pdf")


def recording_readers(**texts: tuple[str, int]):
    """Rung readers that record which rungs were actually asked.

    The record is the point: "it did not escalate" is only provable by showing
    the rung was never called, not by inspecting the result.
    """
    called: list[str] = []

    def make(source: str):
        def read(path: Path) -> tuple[str, int]:
            called.append(source)
            return texts[source]

        return read

    return {source: make(source) for source in texts}, called


def test_a_born_digital_document_stops_at_the_first_rung():
    readers, called = recording_readers(
        **{TEXT_LAYER: ("a" * 900, 1), OCR: ("should never run", 1)}
    )
    gate = QualityGate(
        ocr_engine="rapidocr", ocr_language="eslav", min_chars_per_page=100, readers=readers
    )
    reading = gate.read(SOMEWHERE)
    assert reading.source == TEXT_LAYER
    assert called == [TEXT_LAYER]


def test_a_scan_escalates_to_recognition_exactly_once():
    # Nine characters of punctuation over one page is what the shipped extractor
    # actually returns for a Ukrainian scan, so it is what the floor has to catch.
    readers, called = recording_readers(
        **{TEXT_LAYER: (".\n\n:    .", 1), OCR: ("Правління передало оренду" * 8, 1)}
    )
    gate = QualityGate(
        ocr_engine="rapidocr", ocr_language="eslav", min_chars_per_page=100, readers=readers
    )
    reading = gate.read(SOMEWHERE)
    assert reading.source == OCR
    assert called == [TEXT_LAYER, OCR]


def test_the_vision_rung_is_not_reached_unless_it_is_configured():
    readers, called = recording_readers(
        **{TEXT_LAYER: ("", 1), OCR: ("thin", 1), VLM: ("should never run", 1)}
    )
    gate = QualityGate(
        ocr_engine="rapidocr",
        ocr_language="eslav",
        min_chars_per_page=100,
        vlm_model="",
        readers=readers,
    )
    reading = gate.read(SOMEWHERE)
    assert VLM not in called
    assert reading.source == OCR


def test_the_vision_rung_runs_when_configured_and_the_rungs_above_are_thin():
    readers, called = recording_readers(
        **{TEXT_LAYER: ("", 1), OCR: ("thin", 1), VLM: ("a full page of recovered text" * 9, 1)}
    )
    gate = QualityGate(
        ocr_engine="rapidocr",
        ocr_language="eslav",
        min_chars_per_page=100,
        vlm_model="GRANITEDOCLING_TRANSFORMERS",
        readers=readers,
    )
    reading = gate.read(SOMEWHERE)
    assert called == [TEXT_LAYER, OCR, VLM]
    assert reading.source == VLM


def test_the_richest_attempt_wins_when_no_rung_clears_the_floor():
    # More recovered text is more evidence. A document thin on every rung is
    # refused a layer up by the usable-text rule, not silently dropped here.
    readers, _ = recording_readers(
        **{TEXT_LAYER: ("short", 1), OCR: ("a longer but still thin reading", 1)}
    )
    gate = QualityGate(
        ocr_engine="rapidocr", ocr_language="eslav", min_chars_per_page=1000, readers=readers
    )
    reading = gate.read(SOMEWHERE)
    assert reading.source == OCR
    assert reading.text == "a longer but still thin reading"


def test_the_richest_attempt_can_be_the_first_rung():
    readers, _ = recording_readers(
        **{TEXT_LAYER: ("a text layer that is thin for its length" * 2, 1), OCR: ("noise", 1)}
    )
    gate = QualityGate(
        ocr_engine="rapidocr", ocr_language="eslav", min_chars_per_page=5000, readers=readers
    )
    assert gate.read(SOMEWHERE).source == TEXT_LAYER


def test_the_floor_is_measured_per_page_not_per_document():
    # The same total characters, two page counts, two outcomes. An absolute
    # threshold cannot tell a full one-page letter from an empty long report.
    text = "x" * 400

    def gate_for(pages: int):
        readers, called = recording_readers(**{TEXT_LAYER: (text, pages), OCR: ("y" * 9000, pages)})
        return (
            QualityGate(
                ocr_engine="rapidocr",
                ocr_language="eslav",
                min_chars_per_page=100,
                readers=readers,
            ),
            called,
        )

    one_page, called_one = gate_for(1)
    assert one_page.read(SOMEWHERE).source == TEXT_LAYER
    assert called_one == [TEXT_LAYER]

    many_pages, called_many = gate_for(20)
    assert many_pages.read(SOMEWHERE).source == OCR
    assert called_many == [TEXT_LAYER, OCR]


def test_a_page_count_of_zero_is_scored_as_one_page():
    # A format that reports no pages must not divide by zero, and must not be
    # treated as infinitely dense either.
    assert Reading(text="x" * 50, source=TEXT_LAYER, pages=0).chars_per_page == 50


def test_the_rungs_present_depend_only_on_the_vision_model():
    without = QualityGate(ocr_engine="rapidocr", ocr_language="eslav", min_chars_per_page=100)
    with_vlm = QualityGate(
        ocr_engine="rapidocr",
        ocr_language="eslav",
        min_chars_per_page=100,
        vlm_model="GRANITEDOCLING_TRANSFORMERS",
    )
    assert without.rungs() == (TEXT_LAYER, OCR)
    assert with_vlm.rungs() == (TEXT_LAYER, OCR, VLM)


def test_auto_is_refused_by_the_engine_builder_too():
    # Refused at configuration load as well, but this function is reachable from
    # anything that builds a gate directly, and `auto` silently discards the
    # language wherever it is reached from.
    with pytest.raises(RecognitionError) as exc:
        ocr_options_for("auto", "eslav")
    assert "auto" in str(exc.value)


def test_an_unknown_engine_is_refused_by_the_engine_builder():
    with pytest.raises(RecognitionError) as exc:
        ocr_options_for("nosuchengine", "eslav")
    assert "nosuchengine" in str(exc.value)


def test_the_gate_is_importable_without_loading_a_model():
    # The module must not import docling at module scope: a caller that only
    # ingests plain text should never pay seconds of import for the model stack.
    #
    # In a subprocess, because the claim is about what importing this module
    # pulls in. Asserted in-process it would depend on whether some earlier test
    # in the run had already imported docling, which is not this module's doing.
    import subprocess
    import sys

    probe = (
        "import sys\n"
        "from jackryan.ingestion.quality_gate import QualityGate\n"
        "QualityGate(ocr_engine='rapidocr', ocr_language='eslav', min_chars_per_page=100)\n"
        "print('docling' in sys.modules or 'docling.document_converter' in sys.modules)\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, check=True
    )
    assert result.stdout.strip() == "False", result.stdout + result.stderr


# --- Verification, before an ingest reads anything ----------------------------

# Two of the checks below build a real recognition pipeline, which fetches model
# weights on a machine that has none. This suite is required to run offline, so
# they are opt-in. `scripts/verify_model_paths.py` runs the same ground for real
# and its result is recorded in docs/handover.md — the same split this repository
# already uses for the embedder.
needs_models = pytest.mark.skipif(
    os.environ.get("JACKRYAN_MODEL_TESTS", "") != "1",
    reason="builds a real recognition pipeline; set JACKRYAN_MODEL_TESTS=1 to run",
)


@needs_models
def test_verify_refuses_a_language_the_engine_cannot_serve():
    # Against the real engine, because that is the only thing that can answer.
    # `initialize_pipeline` is what makes it work: constructing the converter
    # alone returns an object quite happily for any language string, so a check
    # that stopped there would report a misconfigured instance as healthy.
    gate = QualityGate(ocr_engine="rapidocr", ocr_language="klingon", min_chars_per_page=100)
    with pytest.raises(RecognitionError) as exc:
        gate.verify()
    message = str(exc.value)
    assert "ocr_language" in message and "klingon" in message
    # And it says what it will accept, so the operator can fix it from the error.
    assert "cyrillic" in message


@needs_models
def test_verify_passes_for_the_shipped_default():
    QualityGate(ocr_engine="rapidocr", ocr_language="eslav", min_chars_per_page=100).verify()


def test_verify_does_not_look_for_an_engine_when_the_rungs_are_stand_ins():
    # The suite's own gate injects readers, so there is no engine to build and
    # verification must not go looking for one.
    readers, _ = recording_readers(**{TEXT_LAYER: ("x" * 500, 1), OCR: ("", 1)})
    QualityGate(
        ocr_engine="nosuchengine",
        ocr_language="nosuchlanguage",
        min_chars_per_page=100,
        readers=readers,
    ).verify()


def test_an_unknown_vision_model_is_refused_without_loading_weights(monkeypatch):
    # Resolving the name is all `verify` does for the vision rung, deliberately:
    # the weights are gigabytes and the rung is reached rarely. This asserts the
    # name check happens, and that it does not reach a pipeline build.
    from jackryan.ingestion import quality_gate as module

    def refuse(*args, **kwargs):
        raise AssertionError("verify must not build a vision pipeline")

    monkeypatch.setattr(module, "build_converter", refuse)
    monkeypatch.setattr(module, "check_engine", lambda engine, language: None)
    gate = QualityGate(
        ocr_engine="rapidocr",
        ocr_language="eslav",
        min_chars_per_page=100,
        vlm_model="NOT_A_REAL_SPEC",
    )
    with pytest.raises(RecognitionError) as exc:
        gate.verify()
    assert "NOT_A_REAL_SPEC" in str(exc.value)


def test_the_engine_is_built_once_however_many_runs_verify(monkeypatch):
    from jackryan.ingestion import quality_gate as module

    built: list[tuple[str, str]] = []
    monkeypatch.setattr(
        module, "check_engine", lambda engine, language: built.append((engine, language))
    )
    gate = QualityGate(ocr_engine="rapidocr", ocr_language="eslav", min_chars_per_page=100)
    gate.verify()
    gate.verify()
    gate.verify()
    # A workbench ingests repeatedly against one long-lived instance; reloading
    # the recognition models on every run would be seconds each time.
    assert built == [("rapidocr", "eslav")]
