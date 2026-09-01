"""Which tools a profile advertises.

Allow-sets are explicit rather than derived from a tool's properties, so a tool
added later is hidden until someone admits it deliberately. An unrecognised
profile name resolves to the narrowest surface: a configuration typo should cost
tools, never grant them.
"""

from __future__ import annotations

READONLY_TOOLS = frozenset(
    {
        "case_list_casefiles",
        "case_casefile_overview",
        "case_list_documents",
        "case_search",
        "case_get_passage",
        "case_read_document",
        "case_cite",
        "case_mentions",
    }
)

# Attributed writes arrive in M4; the profile exists now so that configuration
# and documentation do not have to change shape when they do.
ANALYST_TOOLS = READONLY_TOOLS
ADMIN_TOOLS = READONLY_TOOLS

PROFILES: dict[str, frozenset[str]] = {
    "readonly": READONLY_TOOLS,
    "analyst": ANALYST_TOOLS,
    "admin": ADMIN_TOOLS,
}

NARROWEST = "readonly"


def tools_for_profile(name: str) -> frozenset[str]:
    """The allow-set for a profile, narrowing anything unrecognised."""
    return PROFILES.get((name or "").strip().lower(), PROFILES[NARROWEST])


def resolve_profile_name(name: str) -> str:
    cleaned = (name or "").strip().lower()
    return cleaned if cleaned in PROFILES else NARROWEST
