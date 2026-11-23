"""M9 - qualification: the dealer's requirements, and what they narrow.

Why this module exists
-----------------------
M8 can rank the verified alternatives. It cannot tell the difference
between two dealers who asked for the same thing:

    "I need a 5 marla plot in Block C"
    "I need a 5 marla plot in Block C, budget around 60 lakh, for
     investment, and I want to close within three months"

The second dealer has stated **requirements**. Those requirements can
only ever **narrow** the set M8 already verified - they can never add a
cell the approved master does not cover, and they can never turn a "no"
into a "yes". This module is where that narrowing happens.

The four requirements the project actually supports
---------------------------------------------------
The approved master and the existing extractor support exactly these,
and M9 adds nothing beyond them:

  * ``budget``       - a price or price range the dealer stated, in PKR;
  * ``purpose``      - what the dealer intends ("investment",
    "personal use", "residential", "commercial");
  * ``block``        - a preferred block;
  * ``size_marla``   - a preferred plot size;
  * ``timeline``     - a purchase horizon ("immediately", "within three
    months").

**Every one of them is optional.** A requirement that was not stated
stays ``None``. It is never guessed, defaulted, or inferred from the
absence of other information. That is the single most important rule
in this file: an unknown requirement is a *known unknown*, and a known
unknown is the reason to ask a question, not the reason to assume.

The narrowing-only rule
-----------------------
Qualification is **strictly narrowing**. It may:

  * remove an option that conflicts with a stated requirement;
  * re-rank the remaining options so the better match comes first.

It may **never**:

  * add an option that M8 did not already produce from the approved
    master;
  * lower the evidence threshold, so a thin cell can never become an
    option;
  * introduce a price, a block, a size or a property attribute that the
    approved master does not hold;
  * turn a missing requirement into a guessed one.

The implementation enforces this by construction: this module receives
the **already-verified** option list from M8 and returns a **subset** of
it. It never calls the lookup, never reads the master, and never
produces an option of its own. A qualification that would empty the set
returns an empty set with a reason - it does not fall back to the
unfiltered list.

Where the requirements come from
--------------------------------
Requirements are extracted from the dealer's own words by
:func:`extract_requirements`, which is a **rules** extractor over the
message text. It reads no dealer identity, no chat history and no
master field, so it cannot leak anything.

The application may later ask a model to interpret dealer language, but
a model-generated requirement must be **validated** before it is used:
it must match a known requirement shape and it must be traceable to a
span of the dealer's own message. :func:`validate_requirement` is that
gate, and the customer-model port's output is only accepted through it.

The module is stdlib-only (RULES_SHORT #5), reads nothing, writes
nothing, and never calls a model.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

__all__ = [
    "PURPOSES",
    "RequirementError",
    "apply_requirements",
    "clarifying_question",
    "empty_requirements",
    "extract_requirements",
    "merge_requirements",
    "validate_requirement",
]


def empty_requirements(**overrides: Any) -> Dict[str, Any]:
    """A requirements dict with every field UNKNOWN.

    Every field is ``None`` unless the caller states one. This is the
    shape the rest of M9 works with, and it is what "the dealer stated
    nothing" looks like - a known unknown, never a guess.

    Usage::

        requirements = empty_requirements(budget_max_pkr=6_000_000.0)
    """
    requirements: Dict[str, Any] = {
        "budget_min_pkr": None,
        "budget_max_pkr": None,
        "purpose": None,
        "block": None,
        "size_marla": None,
        "timeline": None,
        "source": "none",
    }
    for key, value in overrides.items():
        if key not in requirements:
            raise RequirementError(
                "%r is not a supported requirement." % key
            )
        requirements[key] = value
    if any(
        requirements[key] is not None
        for key in ("budget_min_pkr", "budget_max_pkr", "purpose", "block",
                    "size_marla", "timeline")
    ):
        requirements["source"] = "stated"
    return requirements


class RequirementError(ValueError):
    """Raised when a requirement cannot be used safely.

    The caller must treat this as a refusal to use the requirement, and
    therefore as a reason to ask a clarifying question - never as a
    reason to guess one.
    """


# ---------------------------------------------------------------------------
# The requirement shapes the project supports
# ---------------------------------------------------------------------------

# The purposes the approved data can actually inform a decision about.
# The master carries a ``category`` (residential / commercial) and the
# dealer conversation carries an intent side (buy / sell / inquiry), so
# these are the only purposes M9 will act on.
PURPOSES: Tuple[str, ...] = (
    "investment",
    "personal_use",
    "residential",
    "commercial",
    "resale",
)

# A purpose phrase -> the canonical purpose. The phrases are the ones a
# Faisal Hills dealer actually uses, in English and Roman Urdu.
_PURPOSE_PATTERNS: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("investment", (
        r"\binvestment\b", r"\binvest\b", r"\bfor investment\b",
        r"\brental (?:income|yield|purpose)\b", r"\bto let out\b",
        r"\bcapital appreciation\b", r"\bapreciation\b",
        r"\bsena\b",
    )),
    ("resale", (
        r"\bresale\b", r"\bre-?sell\b", r"\bflip\b",
        r"\bsell (?:it |this )?on\b",
    )),
    ("personal_use", (
        r"\bpersonal use\b", r"\bself use\b", r"\bown use\b",
        r"\bfor myself\b", r"\bfor family\b", r"\bliving in it\b",
        r"\bapna\b", r"\bkhud\b",
    )),
    ("commercial", (
        r"\bcommercial\b", r"\bshop\b", r"\boffice\b", r"\bwarehouse\b",
        r"\bplaza\b", r"\bcommercial use\b",
    )),
    ("residential", (
        r"\bresidential\b", r"\bresidence\b", r"\bto live in\b",
        r"\bto build a house\b", r"\bconstruction\b",
    )),
)

# A timeline phrase -> a canonical horizon. These are the horizons the
# product can act on: how soon the dealer wants to move.
_TIMELINE_PATTERNS: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("immediate", (
        r"\bimmediate(?:ly)?\b", r"\bright now\b", r"\basap\b", r"\bnow\b",
        r"\bthis (?:week|month)\b", r"\burgent(?:ly)?\b",
    )),
    ("one_month", (
        r"\bwithin (?:a |one |1 )?month\b", r"\bin a month\b",
        r"\bnext month\b", r"\b1 month\b", r"\bone month\b",
    )),
    ("three_months", (
        r"\bwithin (?:three |3 )?months?\b", r"\bin three months\b",
        r"\bnext (?:three|3) months\b", r"\b3 months\b",
        r"\bquarter\b",
    )),
    ("six_months", (
        r"\bwithin (?:six |6 )?months?\b", r"\bin six months\b",
        r"\b6 months\b", r"\bhalf a year\b", r"\bsix months\b",
    )),
)

# A budget phrase. The patterns capture the number and the unit; the
# unit decides the multiplier. The unit group deliberately lists only
# MONEY units - a "marla" is a size, never a budget.
_MONEY_UNIT = r"(?:crore|cr|million|lacs?|lakhs?|thousand|hazar|k)"

_BUDGET_PATTERNS: Tuple[str, ...] = (
    # "budget 60 lakh", "around 60 lac", "60 lakh budget"
    r"\b(?:budget|budjet|price|cost|rate|afford|maximum|max|upto|up to|"
    r"within|below|under|around|about|approx(?:imately)?|near|offer me|"
    r"i can (?:pay|give|spend)|i have|my budget is|cheapest|rate of)\s*"
    r"(?:is|of|around|about|approx(?:imately)?|near|at)?\s*"
    r"([\d,]+(?:\.\d+)?)\s*"
    + _MONEY_UNIT + r"?",
    # "60 lakh budget", "60 lac ka budget"
    r"([\d,]+(?:\.\d+)?)\s*"
    + _MONEY_UNIT + r"\s*"
    r"(?:ka |ki |my )?(?:budget|budjet|price|rate)",
    # M9 D-51: the ambiguous "m" is a MONEY unit only when a money word
    # is next to it. "5 m budget" is five million; "5 m plot" is five
    # marla. The word may come before or after the figure.
    r"\b(?:budget|budjet|price|cost|rate|afford|pay|spend|max|maximum|"
    r"upto|up to|cheapest|offer|million)\b[^.]{0,24}?"
    r"(?<![\w.])(\d[\d,]*(?:\.\d+)?)\s*m\b",
    r"(?<![\w.])(\d[\d,]*(?:\.\d+)?)\s*m\s*"
    r"(?:ka |ki |my )?(?:budget|budjet|price|rate)",
    # M9 D-50: a MONEY UNIT ON ITS OWN is a budget. "I can do 60 lakh",
    # "my limit is 1.2 crore" and "60 lakh please" all state a budget,
    # but none of them uses the word "budget" - the old extractor found
    # nothing and the dealer was asked a question about a budget they
    # had already stated. The unit is what makes it a budget: "marla"
    # and "kanal" are NOT money units, so a size is still never read as
    # a price. The ambiguous "m" is excluded here and handled by the
    # context-sensitive patterns below.
    r"(?<![\w.])(\d[\d,]*(?:\.\d+)?)\s*"
    r"(?:crore|cr|lacs?|lakhs?|million|thousand|hazar)\b",
)

# A money unit that must NEVER be read as a budget. "10 marla" is a
# size, not a 10-lakh budget; "7 marla" likewise. A number followed by
# one of these is a size and is skipped by the budget extractor.
#
# "m" is listed here because in this market a bare "5 m" means five
# MARLA far more often than five million - see _MONEY_UNIT_TABLE.
_NOT_A_MONEY_UNIT: Tuple[str, ...] = (
    "marla", "marlas", "marlay", "marley", "kanal", "kanals",
    "sqft", "square", "feet", "ft",
)

# The unit table. An UNAMBIGUOUS money unit is always a money unit; the
# ambiguous ones ("m") are only a money unit when the sentence says
# something money-shaped. "5 m" is five marla; "5 m budget" is five
# million. The table is the single place that decides.
_MONEY_UNIT_TABLE: Dict[str, float] = {
    "crore": 10_000_000.0,
    "cr": 10_000_000.0,
    "million": 1_000_000.0,
    "lacs": 100_000.0,
    "lac": 100_000.0,
    "lakhs": 100_000.0,
    "lakh": 100_000.0,
    "thousand": 1_000.0,
    "hazar": 1_000.0,
    "k": 1_000.0,
}

# The ambiguous single-letter money unit. "m" is a MONEY unit only when
# the text around it is money-shaped; otherwise it is a marla.
_AMBIGUOUS_MONEY_UNIT = "m"
_AMBIGUOUS_MONEY_MULTIPLIER = 1_000_000.0

# The multiplier for a budget unit. A bare number with no unit is NOT
# accepted as a budget: "I need 5 marla" must not be read as a budget
# of 5 PKR, and "7 marla" must not become a 7-lakh budget.
#
# The table above is the single source of truth for the UNAMBIGUOUS
# units; the ambiguous "m" is resolved by _resolve_unit.
_BUDGET_UNITS: Tuple[Tuple[str, float], ...] = tuple(
    sorted(_MONEY_UNIT_TABLE.items()))

# The smallest budget that can be a real plot budget. The cheapest cell
# in the approved master is a 5-marla plot in Block C at PKR 3,950,000,
# so a figure in the thousands is a misparse, not a budget.
#
# M9 D-53: dropping an implausible figure leaves the budget UNKNOWN,
# which is the safe outcome - the product asks the dealer rather than
# filtering every option on a fiction.
_MIN_PLAUSIBLE_BUDGET_PKR = 100_000.0

# A unit that is explicitly a budget phrase, so a bare number is allowed
# only when one of these words is present.
_BUDGET_CONTEXT_RE = re.compile(
    r"\b(budget|budjet|rate|price|cost|afford|pay|spend|max|maximum|"
    r"upto|up to|within|cheapest|offer)\b",
    re.IGNORECASE,
)

# The words that make a bare "m" a MONEY unit rather than a marla.
#
# M9 D-51: without this, "I need 5 m in Block C" was read as a 5-MILLION
# budget and "5 m plot" as five marla - inconsistently, because the
# size extractor and the budget extractor disagreed about the same
# three characters. A money word next to the "m" settles it.
_MONEY_CONTEXT_RE = re.compile(
    r"\b(budget|budjet|price|cost|rate|afford|pay|spend|payment|"
    r"max|maximum|upto|up to|invest|investment|million|budget's|"
    r"rupees|pkr|rs\.?)\b",
    re.IGNORECASE,
)

# A price RANGE: "between 50 and 60 lakh", "50 to 60 lac",
# "50-60 lakh".
_BUDGET_RANGE_RE = re.compile(
    r"\b(?:between\s+)?([\d,]+(?:\.\d+)?)\s*"
    + _MONEY_UNIT + r"?\s*"
    r"(?:-|to|and|or)\s*"
    r"([\d,]+(?:\.\d+)?)\s*"
    + _MONEY_UNIT + r"\b",
    re.IGNORECASE,
)

# "under 50 lakh", "upto 60 lac", "below 40 lakh", "maximum 70 lakh" -
# a one-sided bound, which is a budget ceiling.
_BUDGET_CEILING_RE = re.compile(
    r"\b(?:under|below|upto|up to|maximum|max|within|less than|"
    r"not more than|ceiling)\s*([\d,]+(?:\.\d+)?)\s*"
    + _MONEY_UNIT + r"\b",
    re.IGNORECASE,
)

_BUDGET_FLOOR_RE = re.compile(
    r"\b(?:above|over|at least|minimum|min|starting from|from)\s*"
    r"([\d,]+(?:\.\d+)?)\s*"
    + _MONEY_UNIT + r"\b",
    re.IGNORECASE,
)

# The size, in marla, when the dealer says a size. The pipeline already
# has a proven extractor for this, so M9 reuses it rather than
# re-implementing it.
#
# M9 D-51: the bare "m" is a marla ONLY when the sentence is not
# money-shaped. "5 m plot" is five marla; "5 m budget" is five million
# and must not become a five-marla size. The unambiguous "marla" is
# always a size.
_SIZE_RE = re.compile(
    r"\b(\d+(?:\.\d+)?)\s*(?:marla|marlas)\b", re.IGNORECASE)
_SIZE_SHORT_RE = re.compile(
    r"\b(\d+(?:\.\d+)?)\s*m\b", re.IGNORECASE)
_KANAL_RE = re.compile(
    r"\b(\d+(?:\.\d+)?)\s*(?:kanal|kanals)\b", re.IGNORECASE)

_KANAL_IN_MARLA = 20.0


def _number(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _to_pkr(value: float, unit: Optional[str]) -> Optional[float]:
    """A number in the dealer's unit, as PKR.

    A bare number is only a budget when a budget word is present, so
    that "5 marla" and "Block C" are never read as a price.
    """
    if unit:
        unit = unit.lower().strip()
        for name, multiplier in _BUDGET_UNITS:
            if unit == name:
                return float(value) * multiplier
    return float(value)


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------


def extract_requirements(message: Optional[str]) -> Dict[str, Any]:
    """Extract the requirements the dealer stated in ONE message.

    Every returned field is either a value the dealer actually stated
    or ``None``. Nothing is defaulted, and nothing is inferred from the
    absence of information.

    Returns:
        A dict with the keys:

        * ``budget_min_pkr`` / ``budget_max_pkr`` - a stated range, or a
          one-sided bound, or ``None``;
        * ``purpose``      - one of :data:`PURPOSES`, or ``None``;
        * ``block``        - a preferred block, or ``None``;
        * ``size_marla``   - a preferred size, or ``None``;
        * ``timeline``     - a canonical horizon, or ``None``;
        * ``source``       - "stated" when at least one requirement was
          found, "none" otherwise.

    The block is canonicalised through the lookup's own alias table, so
    "Block C", "FHC" and "C block" all mean the same cell and a parked
    block is recognised as parked.
    """
    text = str(message or "")
    lowered = text.lower()

    result: Dict[str, Any] = {
        "budget_min_pkr": None,
        "budget_max_pkr": None,
        "purpose": None,
        "block": None,
        "size_marla": None,
        "timeline": None,
        "source": "none",
    }

    if not text.strip():
        return result

    # -- budget ------------------------------------------------------
    budget_min, budget_max = _extract_budget(text, lowered)
    if budget_min is not None or budget_max is not None:
        result["budget_min_pkr"] = budget_min
        result["budget_max_pkr"] = budget_max

    # -- purpose -----------------------------------------------------
    for purpose, patterns in _PURPOSE_PATTERNS:
        for pattern in patterns:
            if re.search(pattern, lowered):
                result["purpose"] = purpose
                break
        if result["purpose"]:
            break

    # -- timeline ----------------------------------------------------
    for horizon, patterns in _TIMELINE_PATTERNS:
        for pattern in patterns:
            if re.search(pattern, lowered):
                result["timeline"] = horizon
                break
        if result["timeline"]:
            break

    # -- size --------------------------------------------------------
    kanals = _KANAL_RE.search(lowered)
    if kanals:
        result["size_marla"] = float(kanals.group(1)) * _KANAL_IN_MARLA
    else:
        size = _SIZE_RE.search(lowered)
        if size:
            result["size_marla"] = float(size.group(1))
        else:
            # M9 D-51: the bare "m" is a size only when the sentence is
            # not money-shaped. "5 m plot" is a size; "5 m budget" is a
            # money figure and is NOT a size.
            short = _SIZE_SHORT_RE.search(lowered)
            if short and not _MONEY_CONTEXT_RE.search(text):
                result["size_marla"] = float(short.group(1))

    # -- block -------------------------------------------------------
    block = _extract_block(text)
    if block:
        result["block"] = block

    if any(
        result[key] is not None
        for key in ("budget_min_pkr", "budget_max_pkr", "purpose", "block",
                    "size_marla", "timeline")
    ):
        result["source"] = "stated"

    return result


def _extract_budget(text: str, lowered: str) -> Tuple[Optional[float], Optional[float]]:
    """A budget range, a ceiling, or a floor, from the message.

    The rules that keep a size from becoming a budget:

    * a number with **no unit** is a budget only when a budget word
      ("budget", "rate", "afford", ...) is next to it;
    * a number with a unit ("60 lakh") is a budget on its own, because
      "lakh" is a money unit and "marla" is not;
    * a range ("between 50 and 60 lakh") yields both bounds.
    """
    # -- an explicit range -------------------------------------------
    range_match = _BUDGET_RANGE_RE.search(text)
    if range_match:
        low = _number(range_match.group(1))
        high = _number(range_match.group(2))
        if low is not None and high is not None:
            # The unit is the one attached to the upper bound.
            unit = _trailing_unit(text, range_match.group(2))
            multiplier = _unit_multiplier(unit)
            if multiplier is None:
                return None, None
            low_pkr = low * multiplier
            high_pkr = high * multiplier
            if low_pkr > high_pkr:
                low_pkr, high_pkr = high_pkr, low_pkr
            if high_pkr < _MIN_PLAUSIBLE_BUDGET_PKR:
                return None, None
            return low_pkr, high_pkr

    # -- a one-sided ceiling -----------------------------------------
    ceiling = _BUDGET_CEILING_RE.search(text)
    if ceiling:
        value = _number(ceiling.group(1))
        multiplier = _unit_multiplier(_trailing_unit(text, ceiling.group(1)))
        if value is not None and multiplier is not None:
            pkr = value * multiplier
            if pkr >= _MIN_PLAUSIBLE_BUDGET_PKR:
                return None, pkr

    # -- a one-sided floor -------------------------------------------
    floor = _BUDGET_FLOOR_RE.search(text)
    if floor:
        value = _number(floor.group(1))
        multiplier = _unit_multiplier(_trailing_unit(text, floor.group(1)))
        if value is not None and multiplier is not None:
            pkr = value * multiplier
            if pkr >= _MIN_PLAUSIBLE_BUDGET_PKR:
                return pkr, None

    # -- a single stated figure -------------------------------------
    for pattern in _BUDGET_PATTERNS:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            value = _number(match.group(1))
            if value is None:
                continue
            unit = _trailing_unit(text, match.group(1))
            multiplier = _unit_multiplier(unit)
            if multiplier is None:
                # A bare number: only a budget when a budget word is
                # around it AND the number is not a size. "cheapest 10
                # marla" must not become a budget of 10 PKR.
                if not _BUDGET_CONTEXT_RE.search(text):
                    continue
                if _number_is_a_size(text, match.group(1)):
                    continue
                multiplier = 1.0
            pkr = value * multiplier
            if pkr <= 0:
                continue
            if pkr < _MIN_PLAUSIBLE_BUDGET_PKR:
                # M9 D-53: a figure below the floor is not a budget for
                # a plot. The smallest cell in the approved master sells
                # in the millions, so "6 PKR" is a misparse - almost
                # always a bare digit that happened to sit next to a
                # budget word. Dropping it leaves the requirement
                # UNKNOWN, which is the safe outcome: the product asks
                # the dealer rather than filtering on a fiction.
                continue
            # A single figure with a ceiling word is a ceiling, not an
            # exact budget.
            #
            # M9 D-54: the ceiling word is looked for in the text
            # IMMEDIATELY BEFORE THE NUMBER, not merely anywhere
            # earlier in the message. "up to 8 million" puts "up to"
            # inside the match, before the number, so the old check -
            # which looked at the whole match start - missed it and
            # read a ceiling as an exact budget. That turned "up to 8
            # million" into a 8,000,000 budget that EXCLUDED a 9,300,000
            # cell the dealer had explicitly said they could afford.
            if _ceiling_word_before(text, match.start(1)):
                return None, pkr
            return pkr, pkr

    return None, None


def _ceiling_word_before(text: str, number_index: int) -> bool:
    """Whether a ceiling word sits immediately before the number.

    M9 D-54. "up to 8 million" is a CEILING of 8,000,000, not an
    exact budget of 8,000,000 - and the difference is material, because
    a ceiling is a filter (drop anything above it) while an exact
    budget is a filter too (drop anything above it) BUT the exact form
    also constrains the lower bound.

    The word must be close to the number: "under 50 lakh" is a ceiling
    for the 50, but "under 50 lakh I also considered the 60" must not
    turn the 60 into a ceiling.
    """
    window = text[max(0, number_index - 32): number_index]
    return bool(re.search(
        r"\b(?:under|below|upto|up to|maximum|max|less than|not more than|"
        r"ceiling|within)\s*$",
        window, re.IGNORECASE
    ))


def _number_is_a_size(text: str, number_text: str) -> bool:
    """Whether a bare number in the text is a SIZE, not a budget.

    "cheapest 10 marla available" - the "10" is a size. Reading it as
    a budget would make every option fall outside the budget and would
    remove the entire option set on a misreading.
    """
    index = text.find(number_text)
    if index < 0:
        return False
    tail = text[index + len(number_text): index + len(number_text) + 20]
    match = re.match(
        r"\s*(marla|marlas|marlay|marley|kanal|kanals|sqft|feet|ft)\b",
        tail, re.IGNORECASE)
    if match:
        return True
    # M9 D-51: the bare "m" is a size only when the sentence is not
    # money-shaped, exactly as in the size extractor.
    short = re.match(r"\s*m\b", tail, re.IGNORECASE)
    if short:
        return not _MONEY_CONTEXT_RE.search(text)
    return False


def _trailing_unit(text: str, number_text: str) -> Optional[str]:
    """The money unit that follows a number, if any.

    ``None`` means the number carried no money unit. A number followed
    by a **size** unit ("10 marla") also returns ``None``, so a size can
    never be read as a budget.

    The ambiguous "m" is resolved by :func:`_resolve_unit`, so this
    function and the size extractor can never disagree about what
    "5 m" means.
    """
    index = text.find(number_text)
    if index < 0:
        return None
    tail = text[index + len(number_text): index + len(number_text) + 20]
    match = re.match(
        r"\s*(crore|cr|lacs?|lakhs?|million|m|thousand|hazar|k)\b",
        tail, re.IGNORECASE)
    if not match:
        return None
    return _resolve_unit(match.group(1), text, index)


def _resolve_unit(unit: str, text: str, number_index: int) -> Optional[str]:
    """Whether a unit is a money unit in this sentence, and which one.

    An unambiguous money unit ("lakh", "crore", "million") is always a
    money unit. The ambiguous "m" is a money unit **only** when the
    sentence is money-shaped - "5 m budget" is five million, "5 m plot"
    is five marla.

    Returns:
        The canonical unit name, or ``None`` when the unit is not a
        money unit in this sentence.
    """
    name = str(unit or "").strip().lower()
    if not name:
        return None
    if name in _NOT_A_MONEY_UNIT:
        return None
    if name == _AMBIGUOUS_MONEY_UNIT:
        if not _MONEY_CONTEXT_RE.search(text):
            # "5 m" with no money word: a marla, not a million.
            return None
        return _AMBIGUOUS_MONEY_UNIT
    if name in _MONEY_UNIT_TABLE:
        return name
    return None


def _unit_multiplier(unit: Optional[str]) -> Optional[float]:
    """The PKR multiplier of a money unit, or ``None`` when there is none."""
    if not unit:
        return None
    name = str(unit).strip().lower()
    if name == _AMBIGUOUS_MONEY_UNIT:
        return _AMBIGUOUS_MONEY_MULTIPLIER
    return _MONEY_UNIT_TABLE.get(name)


def _extract_block(text: str) -> Optional[str]:
    """The block the dealer named, canonicalised through the lookup.

    A block outside the active scope is still returned - the scope check
    belongs to the lookup, and M9 must not create a second scope
    authority. What M9 must not do is *invent* a block.

    M9 D-52: the lookup's alias table knows THREE spellings for the
    same blocks - "C", "FHC" and "BLOCK C" - and also the long forms
    "EXECUTIVE" / "EXEC" for Block E. The extractor used to recognise
    only a single letter next to the word "block", so "I prefer
    Executive block" and "EXEC block" named **no** block at all, and
    the preference was silently dropped. Every spelling the lookup
    knows is now recognised, through the lookup's OWN alias table, so
    the two layers cannot disagree about what a block is.
    """
    from market import price_lookup

    # "block C", "Block-C", "block c"
    match = re.search(r"\bblock[\s\-]*([a-z])\b", text, re.IGNORECASE)
    if match:
        canonical = price_lookup.canonical_block(match.group(1))
        if canonical:
            return canonical

    # "C block"
    match = re.search(r"\b([a-z])\s*block\b", text, re.IGNORECASE)
    if match:
        canonical = price_lookup.canonical_block(match.group(1))
        if canonical:
            return canonical

    # "FHC", "FH C" - the short form the master and the policy use.
    match = re.search(r"\bfh\s*([a-e])\b", text, re.IGNORECASE)
    if match:
        canonical = price_lookup.canonical_block(match.group(1))
        if canonical:
            return canonical

    # "Executive block", "EXEC block", "executive" - the long form.
    # The alias table is the single authority, so a spelling it knows
    # is a block and a spelling it does not know is not.
    for candidate in ("executive", "exec"):
        if re.search(r"\b%s\b" % candidate, text, re.IGNORECASE):
            canonical = price_lookup.canonical_block(candidate)
            if canonical:
                return canonical

    return None


# ---------------------------------------------------------------------------
# Merging across messages
# ---------------------------------------------------------------------------


def merge_requirements(
    previous: Optional[Dict[str, Any]],
    current: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Merge the requirements stated so far with the ones just stated.

    A requirement stated **now** wins over one stated earlier - a dealer
    who says "actually, 8 marla" has changed their mind, and the newer
    statement is the one they mean. A requirement stated earlier and
    **not** restated is kept, so a conversation that spreads its
    requirements over several messages still qualifies.

    A requirement that was never stated stays ``None`` in both inputs
    and remains ``None`` in the result.
    """
    previous = previous or {}
    current = current or {}

    merged: Dict[str, Any] = {
        "budget_min_pkr": None,
        "budget_max_pkr": None,
        "purpose": None,
        "block": None,
        "size_marla": None,
        "timeline": None,
        "source": "none",
    }

    for key in ("budget_min_pkr", "budget_max_pkr", "purpose", "block",
                "size_marla", "timeline"):
        value = current.get(key)
        if value is None:
            value = previous.get(key)
        merged[key] = value

    # A budget stated now replaces a budget stated earlier **as a
    # whole**: a dealer who first said "60 lakh" and then says "up to 80
    # lakh" has one budget, and the newer one is it. Merging the two
    # bounds independently would invent a range they never stated.
    if (current.get("budget_min_pkr") is not None
            or current.get("budget_max_pkr") is not None):
        merged["budget_min_pkr"] = current.get("budget_min_pkr")
        merged["budget_max_pkr"] = current.get("budget_max_pkr")

    if any(
        merged[key] is not None
        for key in ("budget_min_pkr", "budget_max_pkr", "purpose", "block",
                    "size_marla", "timeline")
    ):
        merged["source"] = "stated"

    return merged


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

# The only requirement keys M9 will act on. A key outside this set is
# not a requirement - it is an attempt to add one.
_SUPPORTED_KEYS: Tuple[str, ...] = (
    "budget_min_pkr",
    "budget_max_pkr",
    "purpose",
    "block",
    "size_marla",
    "timeline",
)

# The horizons the product can act on.
_SUPPORTED_TIMELINES: Tuple[str, ...] = (
    "immediate", "one_month", "three_months", "six_months")


def validate_requirement(
    requirement: Optional[Dict[str, Any]],
    message: Optional[str] = None,
) -> Dict[str, Any]:
    """Validate ONE requirement before it is allowed to influence anything.

    This is the gate a model-generated requirement must pass. It is
    deliberately strict, because the cost of a wrong requirement is a
    wrong recommendation:

    * only the supported keys survive - anything else is dropped;
    * a purpose must be one of :data:`PURPOSES`;
    * a timeline must be one of the supported horizons;
    * a budget must be a positive number, and a range must be ordered;
    * a size must be positive;
    * a block must be a known block code.

    When ``message`` is given, a **model-proposed** requirement must
    also be *traceable*: the value must appear in the dealer's own
    message. A model may not introduce a budget the dealer never
    stated, and it may not invent a block, a size or a purpose.

    Returns:
        The validated requirement - a dict with only the supported
        keys, and only the ones that passed. Unsupported or malformed
        entries are **dropped**, never repaired.
    """
    if not isinstance(requirement, dict):
        return {}

    validated: Dict[str, Any] = {}
    text = str(message or "").lower()

    for key in _SUPPORTED_KEYS:
        if key not in requirement:
            continue
        value = requirement.get(key)
        if value is None:
            continue

        if key in ("budget_min_pkr", "budget_max_pkr"):
            number = _number(value)
            if number is None or number <= 0:
                continue
            # M9 D-53: the same plausibility floor the extractor uses.
            # A model that proposes "6 PKR" is proposing a fiction, and
            # a fiction must be dropped, not repaired.
            if number < _MIN_PLAUSIBLE_BUDGET_PKR:
                continue
            validated[key] = number
        elif key == "size_marla":
            number = _number(value)
            if number is None or number <= 0:
                continue
            validated[key] = number
        elif key == "purpose":
            candidate = str(value).strip().lower()
            if candidate not in PURPOSES:
                continue
            validated[key] = candidate
        elif key == "timeline":
            candidate = str(value).strip().lower()
            if candidate not in _SUPPORTED_TIMELINES:
                continue
            validated[key] = candidate
        elif key == "block":
            candidate = str(value).strip().upper()
            if not candidate or not candidate.isalpha():
                continue
            validated[key] = candidate

    # A range must be ordered, or it is dropped rather than "fixed".
    low = validated.get("budget_min_pkr")
    high = validated.get("budget_max_pkr")
    if low is not None and high is not None and low > high:
        validated.pop("budget_min_pkr", None)
        validated.pop("budget_max_pkr", None)

    # -- traceability ------------------------------------------------
    # A model-generated requirement must be traceable to the dealer's
    # own words. The application's own extractor is exempt: it derived
    # the value from the message in the first place.
    if message is not None and requirement.get("source") == "model":
        validated = _require_traceable(validated, text)

    return validated


def _require_traceable(
    validated: Dict[str, Any],
    lowered_message: str,
) -> Dict[str, Any]:
    """Keep only the model-proposed values that appear in the message.

    M9 D-55: this gate had three defects, each of which let a model
    through a hole the gate exists to close.

    1. It **crashed** on a purpose and on a timeline: the generator
       expression bound the name ``pattern`` but the loop variable was
       ``patterns``, so ``re.search(pattern, ...)`` raised
       ``NameError``. A model that proposed a purpose therefore took
       the whole request down instead of being refused.

    2. It compared the model's figure with the message in the wrong
       **unit**. The application works in PKR and in marla; the dealer
       writes "60 lakh" and "1 kanal". A model that correctly read
       "60 lakh" as 6,000,000 was DROPPED because the digits
       "6000000" do not appear in the message - and a model that
       correctly read "1 kanal" as 20 marla was dropped for the same
       reason. The gate was therefore unusable for the two most common
       requirements a dealer states.

    3. It tested a **block** by asking whether the block letter appears
       ANYWHERE in the message. "5 marla in Block A for commercial use"
       contains the letter "c" (in "commercial"), so a model that
       claimed Block C was ACCEPTED for a message that names Block A.
       The model could therefore point the dealer at a different block
       than the one the dealer asked for.

    The gate now works in the dealer's own units and against the
    application's own extractor, so the model can only ever be
    confirmed, never corrected.
    """
    kept: Dict[str, Any] = {}

    for key, value in validated.items():
        if key in ("budget_min_pkr", "budget_max_pkr"):
            if not _budget_traceable(value, lowered_message):
                continue
        elif key == "size_marla":
            if not _size_traceable(value, lowered_message):
                continue
        elif key == "block":
            if not _block_traceable(value, lowered_message):
                continue
        elif key == "purpose":
            # The purpose must be traceable to one of the phrases that
            # produced it. (D-55a: the loop variable was wrong.)
            if not any(
                re.search(pattern, lowered_message)
                for _purpose, patterns in _PURPOSE_PATTERNS
                for pattern in patterns
                if _purpose == value
            ):
                continue
        elif key == "timeline":
            # (D-55a: the loop variable was wrong here too.)
            if not any(
                re.search(pattern, lowered_message)
                for horizon, patterns in _TIMELINE_PATTERNS
                for pattern in patterns
                if horizon == value
            ):
                continue
        kept[key] = value

    return kept


def _budget_traceable(value: Any, lowered_message: str) -> bool:
    """Whether a model-proposed budget is in what the dealer actually wrote.

    The application works in PKR; the dealer writes "60 lakh". The
    figure is therefore converted BACK into the units the dealer could
    have used, and the message is searched for the number in each of
    them. A model that says 6,000,000 about "60 lakh" is confirmed; a
    model that says 9,000,000 about "60 lakh" is dropped.
    """
    number = _number(value)
    if number is None:
        return False
    candidates = set()
    if float(number).is_integer():
        candidates.add(str(int(number)))
    candidates.add("%.1f" % float(number))
    candidates.add("%.2f" % float(number))
    # The figure the dealer would have written, in each money unit.
    for unit, multiplier in _MONEY_UNIT_TABLE.items():
        scaled = number / multiplier
        if scaled > 0 and abs(scaled - round(scaled)) < 0.005:
            candidates.add(str(int(round(scaled))))
            candidates.add("%.1f" % scaled)
    # A plain digit run, with the separators removed.
    stripped = re.sub(r"[,\s]", "", lowered_message)
    for candidate in candidates:
        if candidate in lowered_message:
            return True
        if candidate.replace(",", "") in stripped:
            return True
    return False


def _size_traceable(value: Any, lowered_message: str) -> bool:
    """Whether a model-proposed size is in what the dealer actually wrote.

    The application works in marla; the dealer writes "7 marla" or
    "1 kanal". A model that says 20 marla about "1 kanal" is
    confirmed.
    """
    number = _number(value)
    if number is None:
        return False
    candidates = set()
    if float(number).is_integer():
        candidates.add(str(int(number)))
    candidates.add("%.1f" % float(number))
    # The figure the dealer would have written, in marla and in kanal.
    for scale in (1.0, _KANAL_IN_MARLA):
        scaled = number / scale
        if scaled > 0 and abs(scaled - round(scaled)) < 0.005:
            candidates.add(str(int(round(scaled))))
    stripped = re.sub(r"[,\s]", "", lowered_message)
    for candidate in candidates:
        if candidate in lowered_message:
            return True
        if candidate.replace(",", "") in stripped:
            return True
    return False


def _block_traceable(value: Any, lowered_message: str) -> bool:
    """Whether a model-proposed block is the block the dealer actually named.

    (D-55c) The old test asked whether the block LETTER appeared
    anywhere in the message, so "5 marla in Block A for commercial use"
    confirmed a claim of Block C. The block is now compared against the
    application's OWN extractor, which is the single authority on what
    block a message names.
    """
    canonical = str(value or "").strip().upper()
    if not canonical:
        return False
    stated = extract_requirements(lowered_message).get("block")
    if not stated:
        return False
    return str(stated).strip().upper() == canonical


# ---------------------------------------------------------------------------
# The narrowing
# ---------------------------------------------------------------------------


def _option_price_range(option: Dict[str, Any]) -> Tuple[Optional[float], Optional[float]]:
    """The (min, max) asking-price range of an option, if it has one."""
    summary = option.get("summary") or {}
    low = _number(summary.get("price_min_pkr"))
    high = _number(summary.get("price_max_pkr"))
    if low is None:
        low = _number(summary.get("price_median_pkr"))
    if high is None:
        high = low
    return low, high


def _option_block(option: Dict[str, Any]) -> Optional[str]:
    block = option.get("block")
    return str(block).strip().upper() if block else None


def _option_size(option: Dict[str, Any]) -> Optional[float]:
    return _number(option.get("size_marla"))


def apply_requirements(
    options: Optional[Sequence[Dict[str, Any]]],
    requirements: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Narrow a verified option set by the dealer's requirements.

    The result is a **subset** of the input. An option is removed only
    when it *conflicts* with a stated requirement; an option that
    satisfies the requirements is kept and re-ranked.

    The narrowing rules, in full:

    * **budget** - an option whose asking-price range lies entirely
      above the stated ceiling is removed. An option that *overlaps* the
      stated range is kept, because the master holds an asking price,
      not an agreed one, and a dealer can negotiate inside a band. An
      option that lies entirely below the stated floor is kept - a
      cheaper plot satisfies a minimum.
    * **block** - when the dealer stated a preferred block, an option in
      another block is **not removed** but is ranked **below** an option
      in the stated block. A preference is not an exclusion: the M8
      ladder explicitly offers alternatives in other blocks.
    * **size** - likewise a preference, not an exclusion.
    * **purpose** - the approved master holds **no** category field: all
      374 rows have ``category = null`` (measured 2026-10-21). A purpose
      therefore cannot conflict-detect against the data, and it
      narrows **nothing**. It is recorded, and it makes a clarifying
      question more likely - it never removes an option on a guess. A
      purpose the master cannot describe must not be allowed to remove
      a cell.

    Returns:
        A dict with:

        * ``options``  - the kept options, best first;
        * ``removed``  - the removed options, each with the reason;
        * ``applied``  - the requirements that actually changed
          something;
        * ``unknown``  - the requirements that were stated but could not
          narrow anything, so they are worth a clarifying question.
    """
    options = list(options or [])
    requirements = requirements or {}

    applied: List[str] = []
    unknown: List[str] = []

    budget_low = _number(requirements.get("budget_min_pkr"))
    budget_high = _number(requirements.get("budget_max_pkr"))
    preferred_block = requirements.get("block")
    preferred_size = _number(requirements.get("size_marla"))
    purpose = requirements.get("purpose")

    kept: List[Dict[str, Any]] = []
    removed: List[Dict[str, Any]] = []

    for option in options:
        low, high = _option_price_range(option)

        # -- budget ---------------------------------------------------
        # A CEILING removes the options that are entirely above it. An
        # option that OVERLAPS the stated range is kept, because the
        # master holds an asking price and a dealer negotiates inside a
        # band - "up to 8 million" does not disqualify a cell whose
        # range starts at 6,000,000 and ends at 11,500,000.
        #
        # M9 D-56: a FLOOR is symmetric. A cell that lies entirely
        # BELOW the stated floor does not satisfy "at least 12 million"
        # and is removed, exactly as a cell above a ceiling is removed.
        # The old code only re-ranked on a floor, so a dealer who said
        # "at least 12 million" was still shown a 6,000,000 cell as a
        # verified alternative - the product was offering a plot below
        # the floor the dealer had stated.
        if budget_high is not None and low is not None and low > budget_high:
            removed.append({
                "block": option.get("block"),
                "size_marla": option.get("size_marla"),
                "reason": "the asking price is above the stated budget",
                "requirement": "budget",
            })
            continue

        if budget_low is not None and high is not None and high < budget_low:
            removed.append({
                "block": option.get("block"),
                "size_marla": option.get("size_marla"),
                "reason": "the asking price is below the stated minimum",
                "requirement": "budget",
            })
            continue

        # -- purpose --------------------------------------------------
        conflict = _purpose_conflict(option, purpose)
        if conflict:
            removed.append({
                "block": option.get("block"),
                "size_marla": option.get("size_marla"),
                "reason": conflict,
                "requirement": "purpose",
            })
            continue

        kept.append(option)

    # -- re-rank: a stated preference wins, everything else is kept ---
    order_before = [
        (option.get("block"), option.get("size_marla")) for option in kept
    ]

    def _sort_key(option: Dict[str, Any]):
        block_penalty = 0
        if preferred_block and _option_block(option) != str(
                preferred_block).strip().upper():
            block_penalty = 1
        size_penalty = 0
        if preferred_size is not None and _option_size(option) is not None:
            if abs(_option_size(option) - preferred_size) > 0.001:
                size_penalty = 1
        # M9 D-56: a budget FLOOR now REMOVES the cells below it, so
        # the options that remain all meet the floor and there is
        # nothing left for a floor penalty to rank. The budget's
        # narrowing is entirely in the removal step above.
        return (block_penalty, size_penalty, -float(option.get("score") or 0))

    kept.sort(key=_sort_key)

    order_after = [
        (option.get("block"), option.get("size_marla")) for option in kept
    ]
    # A requirement that only RE-RANKED the options still changed the
    # answer - the dealer is now shown a different option first. That
    # counts as applied.
    reranked = order_before != order_after

    if budget_low is not None or budget_high is not None:
        if any(item.get("requirement") == "budget" for item in removed):
            applied.append("budget")
        else:
            # A stated budget that excluded nothing did not narrow the
            # set. It is still a stated requirement, and it is still
            # worth a clarifying question if the answer is ambiguous.
            unknown.append("budget")
    if preferred_block:
        # A preferred block RE-RANKED the options (it never removes
        # them), so it changed the answer even when it removed nothing.
        applied.append("block")
    if preferred_size is not None:
        applied.append("size")
    if purpose:
        if _purpose_conflict_applied(removed):
            applied.append("purpose")
        else:
            # The approved master carries no category attribute
            # (measured: 374/374 rows null), so a purpose can never
            # narrow the set. It is recorded as unknown - a stated
            # requirement the data cannot act on.
            unknown.append("purpose")
    if requirements.get("timeline"):
        # The approved master carries no timing attribute, so a timeline
        # can never narrow the verified set. It is recorded as unknown -
        # a stated requirement the data cannot act on.
        unknown.append("timeline")

    return {
        "options": kept,
        "removed": removed,
        "applied": sorted(set(applied)),
        "unknown": sorted(set(unknown)),
    }


def _purpose_conflict(
    option: Dict[str, Any],
    purpose: Optional[str],
) -> Optional[str]:
    """Whether an option conflicts with the stated purpose.

    **Measured 2026-10-21: the approved master carries no ``category``
    field.** All 374 rows have ``category = null``, so there is no
    residential/commercial attribute to conflict with.

    A purpose therefore removes **nothing**. That is the honest
    outcome, and it is the safe one: the product must not remove a
    verified cell on a property attribute the approved data does not
    hold. The purpose is still recorded, and it still makes a
    clarifying question more likely, because a purpose the data cannot
    act on is exactly the kind of gap a human should close.

    The check is written against the cell's summary rather than a hard
    "no category" so that a future master that DOES carry the category
    will narrow correctly, without M9 having to be rewritten.
    """
    if not purpose:
        return None

    category = (option.get("summary") or {}).get("category")
    if not category:
        # The approved data does not describe this cell's purpose, so
        # it cannot contradict the dealer's.
        return None

    category = str(category).strip().lower()

    if purpose == "commercial" and category == "residential":
        return "the cell is residential, not commercial"
    if purpose in ("residential", "personal_use") and category == "commercial":
        return "the cell is commercial, not residential"
    if purpose == "investment" and category == "commercial":
        return "the cell is commercial, and the purpose is investment"
    return None


def _purpose_conflict_applied(removed: Sequence[Dict[str, Any]]) -> bool:
    return any(item.get("requirement") == "purpose" for item in removed)


# ---------------------------------------------------------------------------
# The clarifying question
# ---------------------------------------------------------------------------

# Which requirement, when it is missing, is worth asking about - and in
# what order. The order is the order of how much a missing requirement
# would change the answer.
_CLARIFY_PRIORITY: Tuple[Tuple[str, str], ...] = (
    ("budget", "What is your budget for the plot?"),
    ("size_marla", "What size of plot are you looking for?"),
    ("block", "Which block would you prefer?"),
    ("purpose", "Is this for investment or for personal use?"),
    ("timeline", "When are you looking to buy?"),
)


def clarifying_question(
    requirements: Optional[Dict[str, Any]] = None,
    options: Optional[Sequence[Dict[str, Any]]] = None,
) -> Optional[Dict[str, Any]]:
    """The single most useful question to ask, or ``None``.

    A question is worth asking when the answer would **materially
    improve the match**. The rules:

    * a missing requirement is only worth asking about when there ARE
      options to choose between - asking "what is your budget?" when
      there is nothing to recommend wastes the dealer's time;
    * a requirement that was stated but could not narrow anything
      (a timeline, for instance) is worth asking about only if it is
      the one thing standing between the dealer and a decision;
    * when nothing is missing and nothing is ambiguous, there is no
      question - the next action is to offer the options or escalate.

    Returns:
        A dict with the requirement, the question text, and the reason -
        or ``None`` when no question should be asked.
    """
    requirements = requirements or {}
    options = list(options or [])

    missing = [
        (key, text) for key, text in _CLARIFY_PRIORITY
        if requirements.get(key) is None
    ]

    if options:
        if missing:
            key, text = missing[0]
            return {
                "requirement": key,
                "question": text,
                "reason": "the dealer has not stated this, and it would "
                          "change which of the verified options is best",
            }
        return None

    # No option survived. The only useful question is the one that could
    # open the set back up - a budget that excludes everything, or a
    # size the data does not hold.
    budget_low = requirements.get("budget_min_pkr")
    budget_high = requirements.get("budget_max_pkr")
    if budget_high is not None:
        return {
            "requirement": "budget",
            "question": "What is the highest budget you can work with?",
            "reason": "no verified option falls within the stated budget",
        }
    if budget_low is not None:
        return {
            "requirement": "budget",
            "question": "What budget range are you working with?",
            "reason": "no verified option falls within the stated budget",
        }
    if requirements.get("size_marla") is not None:
        return {
            "requirement": "size_marla",
            "question": "Would a different plot size work for you?",
            "reason": "the approved data does not cover the requested "
                      "size with enough listings",
        }
    if missing:
        key, text = missing[0]
        return {
            "requirement": key,
            "question": text,
            "reason": "the dealer has not stated this, and the approved "
                      "data does not cover the request as it stands",
        }
    return None
