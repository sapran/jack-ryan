"""The four pattern extractors that ship.

Each finds one kind of identifier by rule alone — no model, no download, no
endpoint — which is why extraction is gated by nothing: four compiled patterns
over a document's chunks cost milliseconds, and a facet nobody switched on is a
facet nobody has.

Precision is the acceptance bar, not coverage. A facet is an inventory an
analyst scans, and one dominated by false matches costs more than an absent one:
it spends the attention it was built to save, and it teaches the analyst to stop
opening the feature. Two of the four therefore do real work beyond matching a
shape — the account extractor validates the check digits, and the registration
number extractor requires a nearby word saying what the digits are — and the
docstring on each says what it would produce without that work. An extractor
that cannot meet the bar is dropped rather than loosened.

No extractor here knows about another. Selection lives in the registry, so a
fifth is added by registering it there and by changing nothing in this module.

Every pattern spells its digits as an explicit `[0-9]` class rather than the
shorthand, which in Python also matches Arabic-Indic and other Unicode decimal
digits. A normalised form exists to be compared across documents, and two
spellings of the same digit do not compare.

No input can make an extractor raise. `find` returns nothing for text it does
not recognise and fails on nothing, and that holds by construction — a compiled
pattern over a string, and integer arithmetic over characters the pattern itself
admitted — rather than by a catch-all around each body. A catch-all here would
swallow a defect in this module and drop every mention in the chunk without
saying so, and an extractor that raised would fail a document for a reason that
has nothing to do with the document.
"""

from __future__ import annotations

import re

from .port import Found

# A local part, a domain of at least two labels, and a top-level label that is
# letters. Requiring that last label is what keeps `user@localhost` out of the
# facet, along with the `word@word` that recognition output produces from a
# smudged page.
#
# Every quantifier is bounded, at RFC 5321's own limits: a local part of 64
# octets, a domain label of 63, and a plausible ceiling on label count and
# top-level length. Two separate defects were measured against the unbounded
# version and both are closed by the bounds rather than by anything else.
#
# The first was cost. An unbounded greedy local part followed by a mandatory
# `@`, and an unbounded `(label\.)+` followed by a mandatory letters-only label,
# backtracks quadratically on text where neither ever satisfies: 4x per doubling
# of input, 21 ms for one 2,000-character chunk against 0.23 ms bounded, and
# 5.7 s per megabyte of crafted text against 0.05 s benign. A chunk is
# adversary-controlled and nothing gates extraction, so that was a free
# amplification for anyone who could get a document ingested.
#
# The second was worse and less obvious. An unbounded local part admits `.`,
# `_`, `%`, `+` and `-` as word separators, so a single match could be a
# 1,417-character sentence — and `case_mentions` reports facet values to an
# agent that the surface's own instructions tell it to read first. An adversary
# who controlled a document controlled the line content, and through the
# frequency ordering the line order too. Bounded, the longest an address can be
# is short enough not to carry a paragraph; the payload also states that its
# values are corpus material, because a bound alone is not an argument that
# nothing objectionable fits.
_EMAIL = re.compile(
    r"[A-Za-z0-9._%+\-]{1,64}"
    r"@"
    r"(?:[A-Za-z0-9](?:[A-Za-z0-9\-]{0,61}[A-Za-z0-9])?\.){1,12}"
    r"[A-Za-z]{2,24}"
)


class EmailExtractor:
    """Email addresses, whose whole normalisation is a change of case."""

    kind = "email"
    name = "pattern/email"

    def find(self, text: str) -> list[Found]:
        return [
            Found(
                value=match.group(),
                # Lowercased whole. The domain is case-insensitive by
                # specification and the local part is not, but no correspondent
                # in this corpus is two people because a document shouted their
                # address in a form field — and a pivot that matched case would
                # split one of them in two.
                normalised=match.group().lower(),
                char_start=match.start(),
                char_end=match.end(),
            )
            for match in _EMAIL.finditer(text)
        ]


# A leading plus, then digits, in one of two readings: an unbroken run, or groups
# joined by a single space, dot, hyphen or bracket pair. A single separator
# rather than a run of them, because a run would let one number reach across a
# gap into the next and produce a match belonging to neither.
_PHONE = re.compile(
    r"\+[0-9]{1,3}"
    r"(?:[0-9]{5,14}"
    r"|(?:[ .\-\u00a0]?(?:\([0-9]{1,4}\)|[0-9]{1,4})){1,7})"
)

# E.164 allows fifteen digits including the country code, and the shortest
# reachable international number is eight. Outside that range a run of digits
# behind a plus sign is an amount, a reference, or two numbers read as one.
MIN_PHONE_DIGITS = 8
MAX_PHONE_DIGITS = 15

_NOT_DIGIT = re.compile(r"[^0-9]")


class PhoneExtractor:
    """Telephone numbers written in the international form, with their plus."""

    kind = "phone"
    name = "pattern/phone"

    def find(self, text: str) -> list[Found]:
        found: list[Found] = []
        for match in _PHONE.finditer(text):
            value = match.group()
            digits = _NOT_DIGIT.sub("", value)
            if not MIN_PHONE_DIGITS <= len(digits) <= MAX_PHONE_DIGITS:
                # Counted after matching rather than expressed in the pattern:
                # the separators sit between the digits, so no quantifier over
                # the whole run can say how many digits the run holds.
                continue
            found.append(
                Found(
                    value=value,
                    # Plus and digits, which is the one form every spelling of a
                    # number reduces to. A pivot on a number written
                    # `+38 (044) 123-45-67` in one document has to find the same
                    # number written without a separator in the next.
                    normalised=f"+{digits}",
                    char_start=match.start(),
                    char_end=match.end(),
                )
            )
        return found


# ISO 13616: two letters for the country, two check digits, then eleven to
# thirty more alphanumerics. The optional separator before each of those is how a
# printed account is written, in groups of four. The quantifier is where the
# thirty-four character maximum lives, so no candidate is ever longer than an
# account can be. A line break is deliberately not a separator: a newline is a
# stronger break than a space, and joining across one would splice an account to
# whatever the next line began with.
_IBAN_CANDIDATE = re.compile(
    r"\b[A-Za-z]{2}[0-9]{2}(?:[ \t\u00a0]?[A-Za-z0-9]){11,30}\b"
)

# The shortest account ISO 13616 admits. Below it there is nothing left to check
# and trimming further cannot help.
IBAN_MIN_LENGTH = 15

_DIGIT_ZERO = ord("0")
_DIGIT_NINE = ord("9")
# A becomes 10 and Z becomes 35, so subtracting this from a letter's code point
# gives its ISO 7064 value.
_LETTER_VALUE_OFFSET = ord("A") - 10


def _mod97_holds(compact: str) -> bool:
    """Whether `compact` satisfies the ISO 7064 mod-97-10 check.

    The first four characters move to the end, each letter becomes its two-digit
    value, and what that spells is an account exactly when it leaves a remainder
    of one modulo ninety-seven.

    Folded ninety-seven at a time rather than assembled into one integer. An
    account is at most thirty-four characters, so either would work here; the
    fold is bounded by construction and stays bounded whatever a later pattern
    admits.
    """
    remainder = 0
    for character in f"{compact[4:]}{compact[:4]}":
        code = ord(character)
        if _DIGIT_ZERO <= code <= _DIGIT_NINE:
            remainder = (remainder * 10 + code - _DIGIT_ZERO) % 97
        else:
            remainder = (remainder * 100 + code - _LETTER_VALUE_OFFSET) % 97
    return remainder == 1


def _end_of_previous_group(text: str, start: int, end: int) -> int:
    """Where `text[start:end]` ends once its last whitespace-separated group goes.

    Returns `start` when one group is all that is left, which ends the search
    rather than trimming inside a word. Trimming by character instead would try
    twenty prefixes of every alphanumeric token in the corpus, and one prefix in
    ninety-seven passes a mod-97 check by chance — the check's precision is worth
    exactly as much as the number of things it is asked about.
    """
    index = end
    while index > start and not text[index - 1].isspace():
        index -= 1
    while index > start and text[index - 1].isspace():
        index -= 1
    return index


def _accepted_iban(text: str, start: int, end: int) -> Found | None:
    """Trim a candidate from the right until the check digits accept it.

    An account printed in groups of four is indistinguishable, to a pattern, from
    an account followed by an ordinary word: in `GB82 WEST 1234 5698 7654 32 was
    debited` the word `was` reads as one more group, and matching greedily and
    checking once would reject a real account because of what happened to follow
    it. So the candidate is taken generously and given back a group at a time
    until the check digits hold. They are the only thing that can say where a
    printed account ends.
    """
    while end > start:
        value = text[start:end]
        compact = "".join(value.split()).upper()
        if len(compact) < IBAN_MIN_LENGTH:
            return None
        if _mod97_holds(compact):
            return Found(
                value=value,
                normalised=compact,
                char_start=start,
                char_end=end,
            )
        end = _end_of_previous_group(text, start, end)
    return None


class IbanExtractor:
    """Bank accounts, admitted by their check digits rather than by their shape.

    A shape match alone would turn every product code, invoice reference and
    document number into a bank account: two letters, two digits and a run of
    alphanumerics describes those at least as well as it describes an account.
    The check digits are what make the difference decidable, and they are the
    whole reason this extractor is worth shipping. Without them the facet would
    be a list of references with a few accounts hidden in it, which costs an
    analyst more than no facet at all — they scan it once, find nothing they can
    use, and do not open it again.
    """

    kind = "iban"
    name = "pattern/iban"

    def find(self, text: str) -> list[Found]:
        found: list[Found] = []
        position = 0
        while (match := _IBAN_CANDIDATE.search(text, position)) is not None:
            accepted = _accepted_iban(text, match.start(), match.end())
            if accepted is None:
                # Resume one character in rather than past the candidate. A
                # candidate that failed may have begun on something merely shaped
                # like an account and swallowed a real one starting inside it,
                # and skipping to its end would step over that account without
                # ever testing it.
                position = match.start() + 1
                continue
            found.append(accepted)
            position = accepted.char_end
        return found


# Ukrainian ЄДРПОУ and ІПН, Russian ИНН, and the Latin transliteration that
# appears in exported and translated material. Є beside Е, and І beside И, are
# deliberate: Ukrainian and Russian spell the same abbreviation with different
# letters, both spellings occur in this corpus, and recognition output mixes them
# inside a single document. Case-insensitive because a form field shouts and a
# sentence does not.
_REGISTRATION_KEYWORD = re.compile("ЄДРПОУ|ЕДРПОУ|ІПН|ИНН|EDRPOU", re.IGNORECASE)

# The digits, as a maximal run. A longer number is not a registration number with
# something after it, it is a different number, and reading twelve digits out of
# a fifteen-digit run would invent an identifier that appears in no document.
_REGISTRATION_DIGITS = re.compile(r"(?<![0-9])[0-9]{8,12}(?![0-9])")

# Any digit at all, used to establish that nothing numeric stands between the
# naming word and the number it names.
_ANY_DIGIT = re.compile(r"[0-9]")

# How far in front of the digits the naming word may sit. Room for a colon, for
# the rest of a label such as `код за ЄДРПОУ юридичної особи:`, and for a line
# break — and not room for the sentence before it.
REGISTRATION_KEYWORD_DISTANCE = 40


class RegistrationNumberExtractor:
    """Company and taxpayer registration numbers, anchored to the word for them.

    The anchor is the extractor. A bare run of eight to twelve digits fires on
    every date written 20240115, every invoice line and every page number in a
    corpus of tens of thousands of chunks, and an inventory made of those is
    worse than none: the analyst scans it once, finds nothing that is an
    identifier, and stops opening it. Requiring a word that names the number is
    what separates an identifier from a number, and it is why this extractor's
    recall is deliberately poor — a registration number written without its
    label is not found, and that is the trade a usable inventory is worth.

    The word names the *next* number after it and not every number within reach
    of it, which matters because a letterhead prints a registration number and a
    telephone number on one line. The two guards below are that rule.
    """

    kind = "registration_number"
    name = "pattern/registration_number"

    def find(self, text: str) -> list[Found]:
        found: list[Found] = []
        for match in _REGISTRATION_DIGITS.finditer(text):
            start = match.start()
            if start and text[start - 1] == "+":
                # A leading plus makes a run of digits an international
                # telephone number, and a registration number never carries one.
                # Without this, a letterhead reading `ЄДРПОУ 12345678, тел.
                # +380441234567` would file the telephone number as a second
                # registration number under the first one's keyword.
                continue
            window = text[max(0, start - REGISTRATION_KEYWORD_DISTANCE) : start]
            keyword: re.Match[str] | None = None
            for keyword in _REGISTRATION_KEYWORD.finditer(window):
                pass
            if keyword is None:
                continue
            if _ANY_DIGIT.search(window, keyword.end()) is not None:
                # The word names the next number after it, not every number
                # within reach of it. On the letterhead above, the keyword names
                # the registration number; the telephone number that follows on
                # the same line is named by nothing, and a window wide enough to
                # hold both would file it as a registration number too. Testing
                # the last keyword in the window is enough: digits standing
                # between it and the number stand between every earlier keyword
                # and the number as well.
                continue
            digits = match.group()
            found.append(
                Found(
                    # The span covers the digits and not the word in front of
                    # them: the word says what the number is and is no part of
                    # it, and a quotation carrying it would show a different
                    # string in every document. The normalised form equals the
                    # value because the pattern admits digits alone — recorded as
                    # a pair regardless, so nothing reading a mention has to know
                    # which kinds normalise to themselves.
                    value=digits,
                    normalised=digits,
                    char_start=start,
                    char_end=match.end(),
                )
            )
        return found
