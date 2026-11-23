"""Number / traceability validator for the Faisal Hills AI Lead Desk (M5).

The product rule (RULES_SHORT #2, handoff v2 §7.3) is:

    The LLM never writes numbers. Templates + placeholders only. Code fills
    numbers. A validator blocks any number not traceable to a stored fact.

Today (M4) the customer-facing reply is built by a template, so a number
*cannot* reach a customer unless something changes the draft. M5 makes that
property **enforced** rather than **assumed**: every number in a customer-facing
reply is extracted and matched against the fact set the lookup produced. A
number that does not trace to an approved fact is a defect, and the reply is
**blocked and routed to a human** instead of being sent.

Design notes (the M5 risks in FH-02 §6):

* **Whitelist-based, not blacklist-based.** A "does this look like a price?"
  heuristic would fire on legitimate non-price numbers - sizes ("7 marla"),
  dates ("2026-10-07"), sample sizes ("21 matching listings"). The validator
  therefore builds the set of *permitted* numbers from the fact set plus the
  already-parsed context, and reports any number outside that set. This is the
  opposite of a blacklist and is what keeps the false-positive rate at zero on
  the legitimate replies.
* **Unknown means unknown.** A fact that is ``None`` contributes nothing to the
  whitelist, so a number that could only have come from that missing fact is
  reported as untraceable. Nothing is inferred.
* **No LLM, no network, no side effects.** The module is stdlib-only
  (RULES_SHORT #5), reads nothing, writes nothing, and never calls a model.

The validator is deliberately *fail-closed*: when it cannot decide, it says so
and lets the caller escalate, rather than passing a reply through unchecked.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

__all__ = [
    "TraceabilityResult",
    "extract_numbers",
    "build_allowed_numbers",
    "validate_reply",
]


# ---------------------------------------------------------------------------
# Number extraction
# ---------------------------------------------------------------------------

# A number in customer-facing prose. Matches:
#   21            -> plain integer
#   7,900,000     -> thousands-separated integer
#   2026          -> year
#   10-07         -> the date part of 2026-10-07
#   11.5          -> decimal
#   5.5           -> decimal
# The trailing punctuation is deliberately excluded so "11,500,000." yields
# "11,500,000" and not "11,500,000.".
_NUMBER_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")

# Money with an explicit currency marker, e.g. "PKR 7,900,000".
_CURRENCY_RE = re.compile(r"\b(?:PKR|Rs\.?|Rs|INR|AED|USD)\s*([\d][\d,]*(?:\.\d+)?)",
                          re.IGNORECASE)


def _to_number(text: str) -> Optional[float]:
    """Parse ``"7,900,000"`` / ``"21"`` / ``"11.5"`` into a float.

    Returns ``None`` when the text is not a number. Thousands separators are
    removed; a trailing separator (``"21,"``) is tolerated because the reply
    template can end a clause on a number.
    """
    if text is None:
        return None
    cleaned = str(text).strip().rstrip(",").replace(",", "")
    if not cleaned:
        return None
    try:
        return float(cleaned)
    except (TypeError, ValueError):
        return None


def extract_numbers(text: Optional[str]) -> List[Tuple[str, float]]:
    """Extract every number from ``text``.

    Returns a list of ``(raw_text, numeric_value)`` pairs in the order they
    appear. ``raw_text`` keeps the original formatting so a failure report can
    quote exactly what was seen.
    """
    if not text:
        return []
    found: List[Tuple[str, float]] = []
    for match in _NUMBER_RE.finditer(text):
        raw = match.group(0)
        value = _to_number(raw)
        if value is not None:
            found.append((raw, value))
    return found


def _date_parts(value: Any) -> Set[float]:
    """Return the numeric parts of a date, so "2026-10-07" is traceable.

    The date in the reply (``2026-10-07``) is rendered as three separate
    numbers by the plain number scanner (2026, 10, 07). Each of those must be
    traceable to the fact's ``latest_date``.
    """
    parts: Set[float] = set()
    if value is None:
        return parts
    text = str(value).strip()
    if not text:
        return parts
    parsed: Optional[date] = None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%d-%m-%Y", "%d/%m/%Y"):
        try:
            parsed = datetime.strptime(text, fmt).date()
            break
        except ValueError:
            continue
    if parsed is None:
        # Fall back to the numeric components of the raw string.
        for chunk in re.split(r"[^0-9]+", text):
            number = _to_number(chunk)
            if number is not None:
                parts.add(number)
        return parts
    parts.add(float(parsed.year))
    parts.add(float(parsed.month))
    parts.add(float(parsed.day))
    return parts


# ---------------------------------------------------------------------------
# The allowed-number set
# ---------------------------------------------------------------------------

# Fact keys whose value is a count (a sample size) rather than a price.
_COUNT_KEYS = (
    "matched_plots",
    "observation_count",
    "distinct_source_chats",
    # M5 (D-32): the number of rows in a cell that actually carry a price.
    # It is an approved-master fact (a count, not a figure), and the
    # closest-match block reports it next to the cell's sample size.
    "priced_plots",
)

# Fact keys whose value is a price.
_PRICE_KEYS = (
    "price_min_pkr",
    "price_median_pkr",
    "price_max_pkr",
    "price_min",
    "price_median",
    "price_max",
)


def build_allowed_numbers(
    facts: Optional[Dict[str, Any]],
    context: Optional[Dict[str, Any]] = None,
) -> Set[float]:
    """Build the set of numbers a reply is permitted to contain.

    ``facts`` is the fact set produced by ``market.price_lookup.lookup_price``
    (or by ``app.market_adapter``). ``context`` may carry extra permitted
    numbers that were already parsed out of the customer's own question -
    the requested size in marla, the block number - so that an echo of the
    customer's own figure is not mistaken for an invented one.

    A fact that is ``None`` contributes **nothing**: an unknown fact cannot
    whitelist anything (unknown means unknown).
    """
    allowed: Set[float] = set()

    if facts:
        for key in _PRICE_KEYS:
            value = _to_number(facts.get(key)) if facts.get(key) is not None else None
            if value is not None:
                allowed.add(value)

        for key in _COUNT_KEYS:
            value = _to_number(facts.get(key)) if facts.get(key) is not None else None
            if value is not None:
                allowed.add(value)

        allowed |= _date_parts(facts.get("latest_date"))

        # The "closest match" (handoff v2 section 7.4 / FH-02 R17) is a real
        # cell of the approved master, so its size and its listing count are
        # approved facts too. Without this, the not-enough-data reply - which
        # names the closest alternative's size - would be blocked for
        # containing a number that is a fact rather than an invention.
        closest = facts.get("closest_match")
        if isinstance(closest, dict):
            size = _to_number(closest.get("size_marla"))
            if size is not None:
                allowed.add(size)
            count = _to_number(closest.get("matched_plots"))
            if count is not None:
                allowed.add(count)
            priced = _to_number(closest.get("priced_plots"))
            if priced is not None:
                allowed.add(priced)

        # A per-marla figure would be a derived number; it is not produced by
        # the current template, so it is deliberately NOT whitelisted.

        # M8: the application's VERIFIED alternatives. They are real cells of
        # the approved master, ranked by the application itself, so naming
        # their size is an approved fact rather than an invention - exactly
        # the grounds on which the closest match is permitted above.
        #
        # Only an entry the application marked ``verified`` is trusted, and
        # only its SIZE is permitted. A price is deliberately not: the
        # alternatives are offered without a figure, and permitting one
        # would let a reply quote a cell the customer path never priced.
        alternatives = facts.get("verified_alternatives")
        if isinstance(alternatives, (list, tuple)):
            for item in alternatives:
                if not isinstance(item, dict):
                    continue
                if item.get("verified") is not True:
                    continue
                size = _to_number(item.get("size_marla"))
                if size is not None:
                    allowed.add(size)

    if context:
        for key in ("size_marla", "size", "block_number", "entity_size_marla"):
            value = context.get(key)
            if value is None:
                continue
            number = _to_number(value)
            if number is not None:
                allowed.add(number)
                # 1 kanal == 20 marla, 2 kanal == 40 marla (DEC-10). A reply
                # that echoes the size in marla is still the customer's own
                # figure, not an invented one.
                if number == 1.0:
                    allowed.add(20.0)
                if number == 2.0:
                    allowed.add(40.0)

        # M5 (D-32): the budget the CUSTOMER stated in their own message.
        # It is not a market fact - it is the dealer's own figure, echoed
        # into the lead brief - so it is permitted on the same grounds as
        # the size, and only on those grounds.
        budget = _to_number(context.get("budget"))
        if budget is not None:
            allowed.add(budget)

        # M5 (D-32): the system timestamp of the reply. It is a system
        # fact (when the reply was produced), not a market fact, so its
        # components are permitted for the same reason.
        timestamp = context.get("timestamp")
        if timestamp is not None:
            allowed |= _timestamp_parts(timestamp)

    return allowed


def _timestamp_parts(value: Any) -> Set[float]:
    """The numeric parts of an ISO timestamp, e.g. "2026-10-21T12:22:32".

    A timestamp is a system fact - it records when the reply was
    produced - so the numbers in it are permitted, exactly as the
    observation date's numbers are.

    The parts are extracted with the SAME scanner the payload uses, so
    a fractional second ("14.066004") is one number here and one number
    there. Splitting on non-digits instead would produce "14" and
    "66004" and then fail to match.
    """
    parts: Set[float] = set()
    if value is None:
        return parts
    for _raw, number in extract_numbers(str(value)):
        parts.add(number)
    return parts


# ---------------------------------------------------------------------------
# The validator
# ---------------------------------------------------------------------------


class TraceabilityResult:
    """The outcome of validating one draft reply.

    Attributes:
        ok: ``True`` when every number in the reply traces to an approved fact.
        untraceable: the ``(raw_text, value)`` pairs that do not trace.
        numbers: every ``(raw_text, value)`` pair found in the reply.
        allowed_count: how many distinct numbers were permitted.
        reason: a human-readable explanation when ``ok`` is ``False``.
    """

    __slots__ = ("ok", "untraceable", "numbers", "allowed_count", "reason")

    def __init__(
        self,
        ok: bool,
        untraceable: Optional[Sequence[Tuple[str, float]]] = None,
        numbers: Optional[Sequence[Tuple[str, float]]] = None,
        allowed_count: int = 0,
        reason: str = "",
    ) -> None:
        self.ok = bool(ok)
        self.untraceable = list(untraceable or [])
        self.numbers = list(numbers or [])
        self.allowed_count = int(allowed_count)
        self.reason = reason

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "untraceable": [
                {"text": raw, "value": value} for raw, value in self.untraceable
            ],
            "numbers": [
                {"text": raw, "value": value} for raw, value in self.numbers
            ],
            "allowed_count": self.allowed_count,
            "reason": self.reason,
        }

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "TraceabilityResult(ok=%r, untraceable=%r, allowed_count=%r)" % (
            self.ok,
            self.untraceable,
            self.allowed_count,
        )

    def __bool__(self) -> bool:
        return self.ok


def validate_reply(
    reply: Optional[str],
    facts: Optional[Dict[str, Any]] = None,
    context: Optional[Dict[str, Any]] = None,
) -> TraceabilityResult:
    """Validate that every number in ``reply`` traces to an approved fact.

    Args:
        reply: the customer-facing draft reply.
        facts: the fact set the reply was built from. ``None`` means no fact
            set is available, so **no** number is permitted.
        context: optional extra permitted numbers parsed from the customer's
            own question (requested size, block number).

    Returns:
        A :class:`TraceabilityResult`. ``ok`` is ``True`` only when every
        number in the reply is in the permitted set.
    """
    numbers = extract_numbers(reply)

    if not numbers:
        # A reply with no numbers cannot carry an unsupported claim. This is
        # the "not enough data" case and it is correct.
        return TraceabilityResult(
            ok=True,
            untraceable=[],
            numbers=[],
            allowed_count=0,
            reason="",
        )

    allowed = build_allowed_numbers(facts, context)

    untraceable: List[Tuple[str, float]] = []
    seen: Set[float] = set()
    for raw, value in numbers:
        if value in allowed or value in seen:
            continue
        seen.add(value)
        untraceable.append((raw, value))

    if untraceable:
        quoted = ", ".join(repr(raw) for raw, _ in untraceable)
        return TraceabilityResult(
            ok=False,
            untraceable=untraceable,
            numbers=numbers,
            allowed_count=len(allowed),
            reason=(
                "Number(s) in the reply do not trace to an approved fact: %s."
                % quoted
            ),
        )

    return TraceabilityResult(
        ok=True,
        untraceable=[],
        numbers=numbers,
        allowed_count=len(allowed),
        reason="",
    )
