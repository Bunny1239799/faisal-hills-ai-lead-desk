"""M6.1 - the reply claim / shape / provenance guard.

Why this module exists
-----------------------
M5's validator (``market/fact_validator.py``) checks **numbers**. M6 added
a replaceable phrasing port (``app/customer_model.py``) that lets an
implementation - possibly an external model - choose the **wording** of a
reply. The port may therefore introduce a claim that carries no new
number at all, and a numeric validator cannot see it.

Three real holes were measured against the approved master before this
module was written. All three pass the M5 numeric validator today:

1. **An availability claim on a thin cell.** "Yes, we have 5 marla plots
   in Block C." carries only the requested size (5), which is in the
   validator's whitelist - it is the customer's own figure, echoed back.
   The numeric validator passes it. The application had already decided
   that the cell is below the evidence threshold, so the claim is
   unsupported.

2. **A size claim that rides in on the date.** The approved master
   carries an observation date of 2026-10-07, and the validator
   whitelists the date's numeric parts (2026, 10, 07). A reply that
   says "we also have 10 marla plots" therefore passes the numeric
   validator - 10 is a permitted number - while asserting a size no
   evidence supports.

3. **A scope claim.** "Block D" and "Executive Block" carry no number at
   all, so neither the numeric validator nor the request-side scope
   check can see them. A reply that names a parked block is a scope
   violation the request path never made.

What this module does
---------------------
It checks the **shape of the claim**, not the value of the number. Every
rule is a membership test against a set the application built from the
approved master - the same whitelist philosophy the numeric validator
uses, applied to claims rather than to numerals.

**Always refused, in every state:**

* a **scope** violation - a block outside the configured active scope;
* an **unsupported size** - a size the evidence does not cover;
* an **unsupported pair** - a (block, size) combination the evidence
  does not cover, even when both of its parts are individually known;
* a **certainty** claim ("guaranteed", "100%", "we can confirm",
  "definitely") - asking-price observations never attest to a promise;
* a **sold-price** claim - the dataset holds asking prices, so a
  confirmed transaction price is never supported;
* a **stock claim about the requested cell** - the master is a *partial
  snapshot of asking prices*, not a live availability feed, so it can
  never attest that a plot is on the market today. A stock claim about
  the **closest-match cell** is allowed in the insufficient state,
  because pointing a dealer at a cell the master does support is the
  product's explicit purpose (handoff v2 section 7.4 / FH-02 R17);
* a **discount or negotiation claim** (D-65) - the application never
  offers, promises or hints at a discount. The guard reads the SAME
  shared discount-term list the policy gate reads
  (`market/discount_terms.py`), so the request path and the reply path
  cannot disagree about what a discount is. A reply that *refuses* a
  discount is a correct reply and is not a claim.

**Required:**

* an **answerable** reply must keep all three provenance markers - that
  the prices are *asking* prices, that they are *not* confirmed sold
  prices, and that *human approval* is required. Dropping one is a
  provenance loss;
* an **insufficient** or **hold** reply must keep the human hand-off.
  A reply that answers a cell below the evidence threshold, or that
  drops the hand-off, is refused.

The state is derived from the **fact set, the reply mode and the
decision** - never from the reply. A reply cannot declare itself
answerable.

The module is stdlib-only (RULES_SHORT #5), reads nothing, writes
nothing, and never calls a model.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from market import discount_terms

__all__ = [
    "APPROVED_SOURCE",
    "STATE_ANSWERABLE",
    "STATE_INSUFFICIENT",
    "STATE_HOLD",
    "STATE_UNSCOPED",
    "ClaimReport",
    "build_claim_manifest",
    "guard_reply",
    "normalize_text",
]

# The one provenance string an approved fact set may carry. It is the same
# constant the surface guard uses; the test suite asserts the two agree,
# so the two layers cannot drift.
APPROVED_SOURCE = "FaisalHills verified partial master"

# The states a reply can be in.
STATE_ANSWERABLE = "answerable"     # a verified cell answered the question
STATE_INSUFFICIENT = "insufficient"  # the cell is below the evidence threshold
STATE_HOLD = "hold"                  # the application escalated, refused or declined
STATE_UNSCOPED = "unscoped"          # not a market reply - nothing to check

# The reply modes the lookup produces (see market/price_lookup.py).
_REPLY_MODE_ANSWERABLE = "verified_market_facts"
_REPLY_MODE_INSUFFICIENT = "insufficient_data"
_REPLY_MODE_HOLD = ("out_of_scope", "no_lookup")


# ---------------------------------------------------------------------------
# Text normalisation
# ---------------------------------------------------------------------------


def normalize_text(text: Optional[str]) -> str:
    """Lower-case a reply and reduce it to words, for marker matching.

    Punctuation becomes a space, so "asking-price" and "asking price"
    are the same marker, and "Human approval is required." matches
    "approval is required" whatever the case.
    """
    lowered = (text or "").lower()
    lowered = re.sub(r"[^a-z0-9%]+", " ", lowered)
    return re.sub(r"\s+", " ", lowered).strip()


# ---------------------------------------------------------------------------
# Claim extraction
# ---------------------------------------------------------------------------

# A block reference. The forms are the ones the approved master and the
# lookup itself use: "Block C", "FHC", "C block", "Executive Block".
#
# The "X block" form is matched case-SENSITIVELY on purpose: a lower-case
# "a block" is the English article, not Block A.
_BLOCK_PATTERNS: Tuple[Tuple["re.Pattern", Any], ...] = (
    (re.compile(r"\bblock\s+([a-e])\b", re.IGNORECASE), 1),
    (re.compile(r"\bfh\s*([a-e])\b", re.IGNORECASE), 1),
    (re.compile(r"\b([A-E])\s+block\b"), 1),
    (re.compile(r"\bblock\s+(?:exec|executive)\b", re.IGNORECASE), "E"),
    (re.compile(r"\bexecutive\b", re.IGNORECASE), "E"),
)

# A size reference, in marla or in kanal. 1 kanal == 20 marla, 2 kanal ==
# 40 marla (DEC-10).
_SIZE_MARLA_RE = re.compile(r"(\d+(?:\.\d+)?)[\s-]*marla", re.IGNORECASE)
_SIZE_KANAL_RE = re.compile(r"(\d+(?:\.\d+)?)[\s-]*kanal", re.IGNORECASE)

_KANAL_IN_MARLA = 20.0


def _extract_blocks(text: Optional[str]) -> List[str]:
    """Every block the text names, canonicalised to a single letter."""
    found: List[str] = []
    seen: Set[str] = set()
    for pattern, group in _BLOCK_PATTERNS:
        for match in pattern.finditer(text or ""):
            code = match.group(group) if isinstance(group, int) else group
            code = str(code).strip().upper()
            if code and code not in seen:
                seen.add(code)
                found.append(code)
    return found


def _extract_sizes(text: Optional[str]) -> List[float]:
    """Every size the text states, normalised to marla."""
    found: List[float] = []
    seen: Set[float] = set()
    for match in _SIZE_MARLA_RE.finditer(text or ""):
        try:
            value = float(match.group(1))
        except (TypeError, ValueError):
            continue
        if value not in seen:
            seen.add(value)
            found.append(value)
    for match in _SIZE_KANAL_RE.finditer(text or ""):
        try:
            value = float(match.group(1)) * _KANAL_IN_MARLA
        except (TypeError, ValueError):
            continue
        if value not in seen:
            seen.add(value)
            found.append(value)
    return found


def _sentences(text: Optional[str]) -> List[str]:
    """The reply split into sentences, so a claim is judged in context."""
    parts = re.split(r"[.!?\n]+", text or "")
    return [part.strip() for part in parts if part and part.strip()]


# The separators that separate one named option from the next. A reply
# that offers several alternatives names them in a list: "a 10 marla
# plot in Block B, a 7 marla plot in Block A and a 5 marla plot in
# Block A".
_CLAUSE_SPLIT_RE = re.compile(
    r",|\s+and\s+|\s*&\s*|\s+or\s+|\s+plus\s+|;", re.IGNORECASE
)


def _clauses(sentence: Optional[str]) -> List[str]:
    """A sentence split into the options it names.

    A single sentence may name several alternatives. Judging the whole
    sentence as one unit would cross every block it names with every
    size it names, and invent a (block, size) combination the reply
    never claimed. Each clause is therefore judged on its own.
    """
    parts = _CLAUSE_SPLIT_RE.split(sentence or "")
    return [part.strip() for part in parts if part and part.strip()]


def _clause_pairs(sentence: Optional[str]) -> List[Tuple[str, float]]:
    """The (block, size) pairs a sentence actually asserts.

    Each clause is judged on its own, so a list of alternatives yields
    one pair per alternative rather than the cross product of all of
    them.

    When **no** clause carries both a block and a size, the whole
    sentence is judged instead. That keeps a claim like "Block C 7 marla
    plots are listed" checked as a pair, exactly as before - the clause
    split must not weaken the check.
    """
    pairs: List[Tuple[str, float]] = []
    clause_with_both = False

    for clause in _clauses(sentence):
        blocks = _extract_blocks(clause)
        sizes = _extract_sizes(clause)
        if blocks and sizes:
            clause_with_both = True
            for block in blocks:
                for size in sizes:
                    pairs.append((block, size))

    if not clause_with_both:
        blocks = _extract_blocks(sentence)
        sizes = _extract_sizes(sentence)
        for block in blocks:
            for size in sizes:
                pairs.append((block, size))

    return pairs


# ---------------------------------------------------------------------------
# Forbidden claim classes
# ---------------------------------------------------------------------------

# A certainty claim. Asking-price observations never attest to a
# promise, a guarantee or a confirmed figure, so these are refused in
# every state.
_FORBIDDEN_CLAIM_PATTERNS: Tuple[Tuple[str, "re.Pattern"], ...] = (
    ("certainty", re.compile(r"\bguarantee\w*\b", re.IGNORECASE)),
    ("certainty", re.compile(
        r"\b(?:definitely|certainly|absolutely|undoubtedly)\b", re.IGNORECASE)),
    ("certainty", re.compile(r"\bno doubt\b", re.IGNORECASE)),
    ("certainty", re.compile(r"\b100\s*%", re.IGNORECASE)),
    ("certainty", re.compile(r"\bwe can confirm\b", re.IGNORECASE)),
    ("certainty", re.compile(r"\bcan confirm\b", re.IGNORECASE)),
    ("certainty", re.compile(r"\bprice is confirmed\b", re.IGNORECASE)),
    ("certainty", re.compile(r"\bconfirmed price\b", re.IGNORECASE)),
    ("certainty", re.compile(r"\bprice confirmed\b", re.IGNORECASE)),
    ("certainty", re.compile(r"\bassured\b", re.IGNORECASE)),
    ("certainty", re.compile(r"\bwill be available\b", re.IGNORECASE)),
    ("certainty", re.compile(r"\bprice is final\b", re.IGNORECASE)),
    ("certainty", re.compile(r"\bfinal price\b", re.IGNORECASE)),
)
# A claim that a **sold** price is being reported. The dataset holds
# asking prices, so a sold price is always unsupported. The negative
# look-behind keeps the product's own disclaimer - "not confirmed sold
# prices" - from being read as a sold-price claim.
_SOLD_CLAIM_PATTERNS: Tuple["re.Pattern", ...] = (
    re.compile(r"(?<!not )confirmed (?:sale|sold) price"),
    re.compile(r"(?<!not )confirmed (?:transaction|deal) price"),
    re.compile(r"\btransaction price\b"),
    re.compile(r"\bdeal price\b"),
    re.compile(r"\bprice (?:was|has been) (?:confirmed|finali[sz]ed)\b"),
    re.compile(r"\bbook(?:ed|ing) price\b"),
    re.compile(r"\balready sold\b"),
)

# A stock / availability claim. The master is a partial snapshot of
# asking prices, not a live availability feed, so a claim that stock
# exists is refused for the REQUESTED cell in every state. It is allowed
# for the closest-match cell in the insufficient state, because that cell
# is the verified alternative the product is meant to point at.
_STOCK_CLAIM_PATTERNS: Tuple["re.Pattern", ...] = (
    re.compile(r"\bavailable\b", re.IGNORECASE),
    re.compile(r"\bavailability\b", re.IGNORECASE),
    re.compile(r"\bin stock\b", re.IGNORECASE),
    re.compile(r"\bfor sale\b", re.IGNORECASE),
    re.compile(r"\bwe (?:can |do |also )?(?:have|has|offer|sell)\b", re.IGNORECASE),
    re.compile(r"\bthere (?:is|are)\b", re.IGNORECASE),
    re.compile(r"\bthere'?s\b", re.IGNORECASE),
    re.compile(r"\bi (?:have|offer)\b", re.IGNORECASE),
    re.compile(r"\bready to (?:sell|buy|book|reserve)\b", re.IGNORECASE),
    re.compile(r"\bwe (?:can )?(?:arrange|reserve|book)\b", re.IGNORECASE),
)

# A property noun, so a stock claim needs a subject that is actually a
# property. "there is not enough data" has no property noun and is not
# a stock claim.
_PROPERTY_NOUN_RE = re.compile(
    r"\b(?:plots?|units?|propert(?:y|ies)|houses?|flats?|inventory|listings?)\b",
    re.IGNORECASE,
)

# A price token, so a stock claim needs a figure or a size to be about.
_PRICE_TOKEN_RE = re.compile(
    r"(?:\bPKR\b|\bRs\.?\b|\bINR\b|\bAED\b|\bUSD\b)\s*[\d,]+|\b[\d,]{4,}\b",
    re.IGNORECASE,
)

# A reply that opens with "Yes".
_YES_RE = re.compile(r"^\s*yes\b", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Required markers
# ---------------------------------------------------------------------------

# The provenance markers an answerable market reply must keep. A reply
# that drops one has lost the provenance the product depends on, so the
# guard refuses it rather than passing it on.
_ASKING_PRICE_RE = re.compile(
    r"\basking price\b|\basking prices\b|\bdealer asking\b|\basked price\b",
    re.IGNORECASE,
)

# The marker that the prices are NOT confirmed sold prices. The
# alternative forms are the phrasings a model may legitimately choose.
_NOT_SOLD_RE = re.compile(
    r"\bnot\s+(?:a\s+|the\s+)?(?:confirmed\s+|completed\s+|final\s+)?(?:sold|sale)\b"
    r"|\basking prices\b[^.]{0,60}\bnot\b"
    r"|\bnot\b[^.]{0,40}\basking prices\b",
    re.IGNORECASE,
)

# The marker that a human approves the reply.
_APPROVAL_RE = re.compile(
    r"\bapproval is required\b|\bhuman approval\b|\bmember of our team\b"
    r"|\bour team approves\b|\bapproves every reply\b|\bteam member\b"
    r"|\bbefore sending\b|\bbefore it is sent\b|\bour team will\b"
    r"|\ba colleague\b",
    re.IGNORECASE,
)

# A deferral marker: the reply must keep the conversation with a human.
_DEFERRAL_RE = re.compile(
    r"\bconfirm\b|\bverify\b|\bour team\b|\bnot enough data\b|\binsufficient\b"
    r"|\bcannot\b|\bcan not\b|\bunable to\b|\bnot able to\b"
    r"|\bget back to you\b|\bpersonally\b|\bcheck with\b|\bteam member\b"
    r"|\bhuman\b|\bour people\b|\breview\b",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# The report
# ---------------------------------------------------------------------------


class ClaimReport:
    """The outcome of checking one reply's claim shape.

    Attributes:
        ok: ``True`` when every claim in the reply is supported.
        state: the state the reply was checked in.
        violations: the ``{"code": ..., "detail": ...}`` records of what
            was not supported. Empty when ``ok`` is ``True``.
        action: ``"accepted"`` when the reply may be used, or
            ``"rejected"`` when it may not.
    """

    __slots__ = ("ok", "state", "violations", "action")

    def __init__(
        self,
        ok: bool,
        state: str = STATE_UNSCOPED,
        violations: Optional[Sequence[Dict[str, str]]] = None,
        action: Optional[str] = None,
    ) -> None:
        self.ok = bool(ok)
        self.state = state
        self.violations = [dict(item) for item in (violations or [])]
        self.action = action or ("accepted" if self.ok else "rejected")

    def to_dict(self) -> Dict[str, Any]:
        # The report is NUMBER-FREE by design. A violation's value is a
        # size or a block the permitted set does not contain, so quoting
        # it would put an untraceable number on a serving surface - the
        # D-32 hole. The count is therefore not a field either: the
        # consumer reads ``len(violations)``. This is the same
        # redaction discipline `market/fact_guard.py` uses for the
        # numbers it refuses to serve.
        return {
            "ok": self.ok,
            "state": self.state,
            "action": self.action,
            "violations": list(self.violations),
        }

    def __bool__(self) -> bool:
        return self.ok

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "ClaimReport(ok=%r, state=%r, violations=%r)" % (
            self.ok,
            self.state,
            self.violations,
        )


# ---------------------------------------------------------------------------
# The scope
# ---------------------------------------------------------------------------


def _scope_blocks() -> Set[str]:
    """The configured active scope, read from the single policy file.

    The lookup, the policy gate and the surface guard all read
    ``config/policies.json`` (D-26). The guard reads it too, so a scope
    change cannot leave one layer behind. A read failure falls back to
    the v1 scope, which is the same fallback the lookup uses.
    """
    try:
        from market import price_lookup

        codes: Set[str] = set()
        for configured in price_lookup.load_policies().get("active_blocks", []):
            canonical = price_lookup.canonical_block(configured)
            if canonical:
                codes.add(canonical)
        if codes:
            return codes
    except Exception:  # pragma: no cover - the config is present in this repo
        pass
    return {"A", "B", "C"}


# ---------------------------------------------------------------------------
# The manifest
# ---------------------------------------------------------------------------


def _number(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _derive_state(
    facts: Optional[Dict[str, Any]],
    action: Optional[str],
    reply_mode: Optional[str],
) -> str:
    """Which of the four states a reply is in.

    The state is derived from the **fact set, the reply mode and the
    decision** - never from the reply itself, so a reply cannot declare
    itself answerable.
    """
    if action in ("escalate", "refuse"):
        return STATE_HOLD
    if reply_mode in _REPLY_MODE_HOLD:
        return STATE_HOLD
    if reply_mode == _REPLY_MODE_INSUFFICIENT:
        return STATE_INSUFFICIENT
    if reply_mode == _REPLY_MODE_ANSWERABLE:
        return STATE_ANSWERABLE
    if isinstance(facts, dict) and facts:
        if facts.get("answerable_for_demo"):
            return STATE_ANSWERABLE
        return STATE_INSUFFICIENT
    return STATE_UNSCOPED


def build_claim_manifest(
    facts: Optional[Dict[str, Any]] = None,
    filters: Optional[Dict[str, Any]] = None,
    context: Optional[Dict[str, Any]] = None,
    action: Optional[str] = None,
    reply_mode: Optional[str] = None,
) -> Dict[str, Any]:
    """Build the set of claims the evidence supports.

    The manifest is derived from the approved fact set, the request's
    own filters and the decision - never from the reply. It says:

    * ``state``          - answerable / insufficient / hold / unscoped;
    * ``scope_blocks``   - the blocks a reply may name at all;
    * ``known_sizes``    - the sizes the evidence covers;
    * ``known_pairs``    - the (block, size) combinations the evidence
      covers - a claim about a *different* cell is not supported even
      when both of its parts are individually supported;
    * ``closest_pairs``  - the (block, size) combinations the closest
      match covers, which a verified alternative may refer to;
    * ``alternative_pairs`` - the (block, size) combinations the
      application's **verified alternatives** cover (M8). A reply may
      name one of these, because the application itself ranked it from
      the approved master. The list is built from the fact set, never
      from the reply.
    """
    filters = filters or {}
    context = context or {}
    state = _derive_state(facts, action, reply_mode)

    requested_block = filters.get("block")
    requested_size = _number(filters.get("size_marla"))
    if requested_size is None:
        requested_size = _number(context.get("size_marla"))

    closest = facts.get("closest_match") if isinstance(facts, dict) else None
    closest_block = None
    closest_size = None
    if isinstance(closest, dict):
        closest_block = closest.get("block")
        closest_size = _number(closest.get("size_marla"))

    known_sizes: Set[float] = set()
    if requested_size is not None:
        known_sizes.add(requested_size)
    if closest_size is not None:
        known_sizes.add(closest_size)

    known_pairs: Set[Tuple[str, float]] = set()
    if requested_block and requested_size is not None:
        known_pairs.add((str(requested_block).strip().upper(), requested_size))
    if closest_block and closest_size is not None:
        known_pairs.add((str(closest_block).strip().upper(), closest_size))

    closest_pairs: Set[Tuple[str, float]] = set()
    if closest_block and closest_size is not None:
        closest_pairs.add((str(closest_block).strip().upper(), closest_size))

    # M8: the application's verified alternatives. They come from the
    # fact set the application built - the reply never contributes to
    # this list, so a reply cannot widen its own permitted claims.
    #
    # An alternative is a permitted claim only when the application
    # marked it ``verified``. An unverified or malformed entry is
    # ignored rather than trusted, so a reply that tried to smuggle an
    # option into the fact set would not be believed.
    alternative_pairs: Set[Tuple[str, float]] = set()
    alternatives = (
        facts.get("verified_alternatives") if isinstance(facts, dict) else None
    )
    if isinstance(alternatives, (list, tuple)):
        for item in alternatives:
            if not isinstance(item, dict):
                continue
            if item.get("verified") is not True:
                continue
            alt_block = item.get("block")
            alt_size = _number(item.get("size_marla"))
            if alt_block and alt_size is not None:
                pair = (str(alt_block).strip().upper(), alt_size)
                alternative_pairs.add(pair)
                known_pairs.add(pair)
                known_sizes.add(alt_size)

    return {
        "state": state,
        "scope_blocks": _scope_blocks(),
        "requested_block": (
            str(requested_block).strip().upper() if requested_block else None
        ),
        "requested_size_marla": requested_size,
        "closest_block": (
            str(closest_block).strip().upper() if closest_block else None
        ),
        "closest_size_marla": closest_size,
        "known_sizes": known_sizes,
        "known_pairs": known_pairs,
        "closest_pairs": closest_pairs,
        "alternative_pairs": alternative_pairs,
        "answerable": bool(
            isinstance(facts, dict) and facts.get("answerable_for_demo")
        ),
        "facts_source": (
            facts.get("facts_source") if isinstance(facts, dict) else None
        ),
    }


# ---------------------------------------------------------------------------
# The guard
# ---------------------------------------------------------------------------


def guard_reply(
    reply: Optional[str],
    facts: Optional[Dict[str, Any]] = None,
    filters: Optional[Dict[str, Any]] = None,
    context: Optional[Dict[str, Any]] = None,
    action: Optional[str] = None,
    reply_mode: Optional[str] = None,
) -> ClaimReport:
    """Check the claim shape of a reply against the approved fact set.

    Args:
        reply: the customer-facing draft reply.
        facts: the fact set the reply was built from. ``None`` means no
            market fact set is available.
        filters: the request's own filters (the requested block and
            size).
        context: the numbers parsed from the customer's own message.
        action: the policy action (``answer`` / ``escalate`` /
            ``refuse``).
        reply_mode: the lookup's reply mode, when a lookup ran.

    Returns:
        A :class:`ClaimReport`. ``ok`` is ``True`` only when every claim
        in the reply is supported by the evidence.
    """
    manifest = build_claim_manifest(facts, filters, context, action, reply_mode)
    state = manifest["state"]

    violations: List[Dict[str, str]] = []
    text = reply or ""
    normalized = normalize_text(text)

    def _add(code: str, detail: str, field: str = "") -> None:
        # The detail NEVER quotes the offending value. The numeric
        # validator may echo an untraceable number (the operator needs to
        # see it to fix it), but a claim violation's value is a size or a
        # block - and a size the evidence does not cover is, by
        # definition, a number the permitted set does not contain.
        # Echoing it would put an untraceable number on a serving
        # surface, which is exactly what D-32 closed.
        record = {"code": code, "detail": detail}
        if field:
            record["field"] = field
        violations.append(record)

    # --- a discount or negotiation claim ---------------------------------
    #
    # D-65: the reply path reads the SAME shared discount-term list as
    # the policy gate (`market/discount_terms.py`). The application never
    # offers, promises or hints at a discount, so a reply that CLAIMS one
    # is refused. A reply that REFUSES one ("we cannot offer a discount",
    # "no discount is available", "our team must approve any discount")
    # is a correct, safe reply and is not a claim.
    #
    # The check runs in EVERY state, including `unscoped`, because a
    # discount claim is a claim about the terms of a deal, not a market
    # claim: it is wrong whatever the evidence covers.
    for sentence in _sentences(text):
        _discount_hit = discount_terms.detect_discount_claim(sentence)
        if _discount_hit:
            _add(
                "discount_claim",
                "the reply makes a discount or negotiation claim",
            )
            break

    if state == STATE_UNSCOPED:
        # Not a market reply: there is no market claim to check. The
        # numeric validator still covers the reply.
        return ClaimReport(ok=not violations, state=state, violations=violations)

    # --- provenance -----------------------------------------------------
    if state in (STATE_ANSWERABLE, STATE_INSUFFICIENT):
        source = manifest.get("facts_source")
        if source != APPROVED_SOURCE:
            _add(
                "provenance_lost",
                "the fact set carries no approved provenance",
            )

    # --- claim classes the evidence can never support --------------------
    for code, pattern in _FORBIDDEN_CLAIM_PATTERNS:
        match = pattern.search(text)
        if match:
            _add(code, "unsupported claim %r" % (match.group(0),))

    for pattern in _SOLD_CLAIM_PATTERNS:
        match = pattern.search(text)
        if match:
            _add("sold_price_claim", "unsupported claim %r" % (match.group(0),))
            break

    # --- scope and the (block, size) pairs the evidence covers -----------
    scope_blocks = manifest["scope_blocks"]
    known_sizes = manifest["known_sizes"]
    known_pairs = manifest["known_pairs"]
    closest_pairs = manifest["closest_pairs"]
    alternative_pairs = manifest["alternative_pairs"]
    requested_block = manifest["requested_block"]
    requested_size = manifest["requested_size_marla"]

    for sentence in _sentences(text):
        blocks = _extract_blocks(sentence)
        sizes = _extract_sizes(sentence)

        for block in blocks:
            if block not in scope_blocks:
                _add(
                    "out_of_scope_block",
                    "the reply names a block outside the active scope",
                    field="block",
                )

        for size in sizes:
            if size not in known_sizes:
                _add(
                    "unsupported_size",
                    "the reply states a size the evidence does not cover",
                    field="size_marla",
                )

        # The (block, size) pairs are read at CLAUSE level, so a reply
        # that offers several alternatives is not judged as the cross
        # product of every block and every size it names. A reply that
        # says "a 10 marla plot in Block B, a 7 marla plot in Block A"
        # claims (B, 10) and (A, 7) - it does not claim (B, 7).
        for block, size in _clause_pairs(sentence):
            if (block, size) not in known_pairs:
                _add(
                    "unsupported_pair",
                    "the reply names a block-and-size combination "
                    "the evidence does not cover",
                    field="block_size",
                )
                break

        # --- stock claims ------------------------------------------------
        # A stock claim about the REQUESTED cell is refused in every
        # state: the master is a partial snapshot of asking prices, not
        # a live availability feed. A stock claim about the
        # closest-match cell is allowed in the insufficient state,
        # because that cell is the verified alternative the product is
        # meant to point at.
        #
        # M8: a stock claim about one of the application's **verified
        # alternatives** is allowed in the insufficient state too, for
        # the same reason. The alternative list comes from the fact set
        # the application built from the approved master, so the reply
        # can only name a cell the application already verified.
        #
        # The stock claim is judged per CLAUSE for the same reason the
        # pair check is: a sentence that offers several alternatives
        # makes one claim per alternative, not one claim about the
        # cross product of everything it names.
        if state == STATE_INSUFFICIENT:
            permitted_pairs = closest_pairs | alternative_pairs
            for clause in _clauses(sentence) or [sentence]:
                if not _is_stock_claim(clause):
                    continue
                clause_blocks = _extract_blocks(clause)
                clause_sizes = _extract_sizes(clause)
                clause_pairs = _clause_pairs(clause)

                mentions_permitted = any(
                    pair in permitted_pairs for pair in clause_pairs)
                mentions_requested = (
                    (requested_size is not None
                     and requested_size in clause_sizes)
                    or (not clause_sizes and requested_block is not None
                        and requested_block in clause_blocks)
                )
                if mentions_permitted and not mentions_requested:
                    # A verified alternative: the cell is covered by the
                    # master and the product points at it on purpose.
                    # Allowed.
                    continue

                _add(
                    "unsupported_availability",
                    "the reply claims inventory exists; the approved data "
                    "is a partial snapshot of asking prices, not an "
                    "availability feed",
                )
                break
            continue

        if not _is_stock_claim(sentence):
            continue

        _add(
            "unsupported_availability",
            "the reply claims inventory exists; the approved data is a "
            "partial snapshot of asking prices, not an availability feed",
        )

    # --- the state-specific requirements --------------------------------
    if state == STATE_ANSWERABLE:
        if not _ASKING_PRICE_RE.search(normalized):
            _add(
                "provenance_lost",
                "the reply does not say the prices are asking prices",
            )
        if not _NOT_SOLD_RE.search(normalized):
            _add(
                "provenance_lost",
                "the reply does not say the prices are not confirmed sold prices",
            )
        if not _APPROVAL_RE.search(normalized):
            _add(
                "provenance_lost",
                "the reply does not keep the human-approval requirement",
            )

    if state == STATE_INSUFFICIENT:
        if not _DEFERRAL_RE.search(normalized):
            _add(
                "deferral_lost",
                "the reply does not keep the human hand-off",
            )
        for sentence in _sentences(text):
            if _YES_RE.match(sentence):
                _add(
                    "insufficient_data_answered",
                    "the reply answers a cell that is below the evidence threshold",
                )
                break

    if state == STATE_HOLD:
        if not _DEFERRAL_RE.search(normalized):
            _add(
                "deferral_lost",
                "the reply does not keep the human hand-off",
            )

    return ClaimReport(
        ok=not violations,
        state=state,
        violations=violations,
    )


def _is_stock_claim(sentence: str) -> bool:
    """Whether a sentence claims that stock exists.

    It needs a stock phrase, a property noun and a figure or a size, so
    "there is not enough data" (no property noun, no figure) is not
    mistaken for a claim that inventory exists.
    """
    for pattern in _STOCK_CLAIM_PATTERNS:
        if not pattern.search(sentence):
            continue
        if not _PROPERTY_NOUN_RE.search(sentence):
            continue
        if _extract_sizes(sentence) or _PRICE_TOKEN_RE.search(sentence):
            return True
    return False
