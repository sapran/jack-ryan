"""Mentions: the boundary, the extractors that ship, and the registry.

Selection lives here rather than in the extractors or in the caller, so that
adding an extractor is registering it in one list and nothing else. No extractor
knows about another and no caller enumerates them: ingestion asks for the
registry and runs whatever it holds. That is what makes a later model-backed
extractor an entry in this list instead of a change to ingestion, to the schema
and to three surfaces.
"""

from .patterns import (
    EmailExtractor,
    IbanExtractor,
    PhoneExtractor,
    RegistrationNumberExtractor,
)
from .port import Found, MentionExtractor

__all__ = [
    "MentionExtractor",
    "Found",
    "MENTION_KINDS",
    "default_extractors",
    "EmailExtractor",
    "PhoneExtractor",
    "IbanExtractor",
    "RegistrationNumberExtractor",
]


def default_extractors() -> list[MentionExtractor]:
    """The registry: every extractor an ingest runs over a chunk.

    Order is the order a chunk's mentions come out in, and nothing depends on
    it. There is no first-match-wins here as there is in the format router — each
    extractor reads the same text and none can hide a match from another — so the
    list is arranged to read from the least machinery to the most: a character
    class, then a digit count, then a check digit, then a word outside the number
    that has to name it.
    """
    return [
        EmailExtractor(),
        PhoneExtractor(),
        IbanExtractor(),
        RegistrationNumberExtractor(),
    ]


# Derived from the registry rather than written out beside it, because the two
# could disagree: several error messages offer these kinds to a caller who named
# one that does not exist, and a list that had drifted would send them after a
# facet no extractor can ever fill. `dict.fromkeys` keeps registry order and
# collapses repeats, since two extractors may one day find the same kind — a
# model-backed reader of addresses beside the pattern-matched one — and a caller
# is asking which kinds exist, not how many extractors produce them.
MENTION_KINDS: tuple[str, ...] = tuple(
    dict.fromkeys(extractor.kind for extractor in default_extractors())
)
