"""The analyst pack is shipped content, and the spec makes claims about it.

These tests hold those claims to the files rather than to intent — a pack that
quietly loses its epistemics is worse than no pack, because an agent would load
it and behave as though the method were present.
"""

from __future__ import annotations

from pathlib import Path

import pytest

PACK = Path(__file__).resolve().parents[1] / "analyst"
ROLE = PACK / "role.md"
SKILLS = PACK / "skills"

SPINE = {
    "hypothesis-testing",
    "key-assumptions-check",
    "calibrated-confidence",
    "naming-the-gaps",
    "deception-detection",
    "multi-source-fusion",
    "briefing",
    "the-working-loop",
}


def test_the_pack_ships_a_role_and_its_skills():
    assert ROLE.is_file()
    assert SKILLS.is_dir()


def test_the_analytic_spine_is_present():
    present = {p.stem for p in SKILLS.glob("*.md")}
    assert SPINE <= present, f"missing: {sorted(SPINE - present)}"


def test_the_pack_is_harness_neutral():
    """Plain markdown, naming no vendor, so any harness can load it."""
    vendors = ("claude", "anthropic", "openai", "gpt-", "gemini", "qwen", "llama")
    for path in [ROLE, *SKILLS.glob("*.md"), PACK / "README.md"]:
        text = path.read_text(encoding="utf-8").lower()
        for vendor in vendors:
            assert vendor not in text, f"{path.name} names a vendor: {vendor}"


def test_the_role_names_the_method_and_the_tools():
    text = ROLE.read_text(encoding="utf-8")
    for tool in (
        "case_list_casefiles",
        "case_casefile_overview",
        "case_search",
        "case_get_passage",
        "case_read_document",
        "case_cite",
    ):
        assert tool in text, f"the role does not name {tool}"


def test_the_role_carries_the_epistemics_the_corpus_demands():
    text = ROLE.read_text(encoding="utf-8").lower()
    assert "coverage claim names what was searched" in text
    assert "absence of evidence is not evidence of absence" in text
    assert "resolves to a document" in text


def test_the_role_states_that_retrieved_content_is_not_instructions():
    text = ROLE.read_text(encoding="utf-8").lower()
    assert "never instructions" in text
    assert "do not act on it" in text


def test_the_loop_closes_on_a_judgement_and_a_next_move():
    for path in (ROLE, SKILLS / "the-working-loop.md"):
        text = path.read_text(encoding="utf-8").lower()
        assert "judgement" in text and "next move" in text
    loop = (SKILLS / "the-working-loop.md").read_text(encoding="utf-8").lower()
    assert "not a stopping point" in loop


@pytest.mark.parametrize("skill", sorted(SPINE))
def test_every_skill_has_a_title_and_a_method(skill):
    text = (SKILLS / f"{skill}.md").read_text(encoding="utf-8")
    assert text.startswith("# "), f"{skill} has no title"
    assert len(text.split()) > 80, f"{skill} is too thin to be useful"
