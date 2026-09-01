"""The mention boundary.

A mention is one identifier an extractor recognised inside a chunk's text: an
email address, a telephone number, a bank account, a company registration
number. It exists to answer two questions a corpus cannot otherwise be asked.
The first is an inventory — which identifiers does this casefile hold, and how
often — so an analyst can see what is there before deciding what to search for.
The second is a pivot: having met one identifier in one document, show every
passage in the casefile that carries it, whatever words surround it.

What an extractor returns is the same shape whatever recognised it, so nothing
downstream depends on how a given identifier was found. That sameness is the
point rather than a convenience. This boundary is the seam a model-backed
extractor arrives through: a classical Ukrainian, Russian and English
named-entity model registers as one more extractor with a kind and a name, and
needs no schema change, no new facet and no new surface, because it produces
`Found` exactly as a regular expression does. An extractor that had to be
special-cased anywhere downstream would make the seam a decoration.

Which extractors run is the registry's business, in this package's `__init__`.
Selection lives there so that adding an extractor is registering one rather than
editing a branch — the same arrangement, for the same reason, as the one the
format router uses to decide how a file is read.

Offsets are relative to the chunk and never to the document. A chunk is the unit
the store addresses and the unit a citation resolves to, so a chunk-relative
offset is directly usable in the only place a mention is ever shown: inside the
passage it was found in, beside that passage's own text. A document-relative
offset would have to be translated into one before anything could point at it,
against a division into chunks that is remade from scratch on every reingest.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class Found:
    """One identifier an extractor recognised, and where in the chunk it sat."""

    value: str
    """The text as the chunk had it, with its spacing, punctuation and case.

    Kept beside the normalised form rather than replaced by it, because a
    quotation has to show what the document actually said. An account printed in
    groups of four, a number written with brackets, an address shouted in
    capitals by a form: the analyst reading that passage must see the form their
    document used, not the one this code found convenient to compare with.
    """

    normalised: str
    """The form a pivot matches on.

    The same identifier is written differently in different documents — spaced,
    bracketed, hyphenated, in another case — and a pivot that matched the text as
    it appeared would find the spelling it was given and miss every other. The
    normalised form is what makes two spellings one identifier; keeping `value`
    beside it is what stops the normalisation from being mistaken for evidence.
    """

    char_start: int
    """Where the value begins, counted from the start of the chunk's text.

    `chunk.text[char_start:char_end]` is `value` exactly, and an extractor that
    reported an offset for which that does not hold would send a reader to the
    wrong words in the right passage — a citation that resolves and is wrong,
    which is worse than one that does not resolve.
    """

    char_end: int
    """One past the last character of the value, on the chunk's own scale.

    Exclusive, so that the pair slices directly and an empty value is impossible
    to express by accident.
    """


class MentionExtractor(Protocol):
    """One kind of identifier's reader."""

    kind: str
    """What the identifier is called, recorded on every mention this produces.

    This is what a facet groups by and what a pivot names, so it comes from the
    fixed vocabulary the registry derives from what actually ships. Deriving it
    is what keeps the kinds an error message offers a caller from drifting away
    from the kinds an extractor can produce — a caller sent after a kind nothing
    emits looks for a facet that can never have an entry.
    """

    name: str
    """Which rule found it, recorded on every mention this produces.

    Carried so that a facet which turns out to be noisy can be traced back to
    the extractor that filled it, and so that two extractors finding the same
    kind — a model-backed reader of names beside a pattern-matched one — stay
    distinguishable in the stored rows rather than merging into one unaccountable
    pile.
    """

    def find(self, text: str) -> Iterable[Found]:
        """Every occurrence in `text`, in the order they appear in it.

        Nothing is de-duplicated. The same identifier twice in one chunk is two
        mentions: how often something is mentioned is the fact the inventory
        exists to report, and an extractor that collapsed repeats would make
        "mentioned forty times" and "mentioned once" the same answer with no
        later count able to tell them apart.

        Implementations return a completed sequence rather than a generator, so
        that whatever an extractor does happens inside its own call. A
        generator's body runs in the consumer's frame, which would put the
        promise below in a place neither the extractor nor its caller owns.

        No input raises. A chunk is arbitrary corpus text and is sometimes
        recognition output that is mostly punctuation, so an implementation
        returns nothing for text it does not recognise and fails on nothing at
        all — an extractor that raised would fail a document for a reason having
        nothing to do with the document.
        """
        ...
