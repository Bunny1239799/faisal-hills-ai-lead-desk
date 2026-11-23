"""Conversational property matching (M13) - Faisal Hills AI Lead Desk.

Plot-level conversational matcher over the approved inventory. The M8/M9
ladder already quotes an answerable cell or offers verified alternative
CELLS; this module adds the professional layer on top of that decision:

  * intent understanding on top of the M9 requirements (budget, purpose
    and timeline come from ``market.qualify``; this module adds facing
    preferences, an explicitly stated plot number, and category);
  * a ranked best match plus up to three alternatives, each with the
    reasons it matches and the trade-offs against what the dealer asked;
  * what is missing and the single next most useful clarifying question.

Hard rules this module keeps:

* It is deterministic and LLM-free. It never invents a plot, a price, an
  availability claim, an owner or a contact. Every option IS a row of
  the approved inventory; every figure comes from that row.
* It NEVER asserts that a plot is available, sold or booked. The
  approved data is a snapshot of asking prices, not a live availability
  feed - a team member verifies every option personally.
* Customer-facing text from :func:`conversational_section` is
  NUMBER-SAFE by construction: no figure >= 1000, no currency token,
  no availability word, and only (block, size) pairs the M9 decision
  already verified. The M5 numeric validator and the M6.1 claim guard
  stay authoritative without any rule change.
* The full plot-level detail (plot numbers, price bands, scores,
  per-option reasons and trade-offs) is returned STRUCTURED for the
  operator, who must see exactly why each option was recommended.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from market import qualify as _qualify
from market.fh_query import _boolean
from market.price_lookup import (
    _active_scope_inventory,
    _number,
    canonical_block,
    load_policies,
)

# Facing and feature preferences the M9 requirement set does not carry.
_PARK_RE = re.compile(r"\bpark[\s-]*fac\w*|\bpark\s*view\b", re.IGNORECASE)
_BOULEVARD_RE = re.compile(r"\bmain\s*boulevard\b|\bboulevard\b|\bblvd\b",
                           re.IGNORECASE)
_ROAD_RE = re.compile(r"\broad[\s-]*fac\w*", re.IGNORECASE)
_CORNER_RE = re.compile(r"\bcorner\b", re.IGNORECASE)
_SUN_RE = re.compile(r"\bsun[\s-]*fac\w*|\beast[\s-]*fac\w*", re.IGNORECASE)
_NDC_OPEN_RE = re.compile(r"\bndc\s*open\b", re.IGNORECASE)
_NDC_RE = re.compile(r"\bndc\b", re.IGNORECASE)
_MDC_RE = re.compile(r"\bmdc\b", re.IGNORECASE)
_COMMERCIAL_RE = re.compile(r"\bcommercial\b|\bshop\b|\boffice\b|\bplaza\b",
                            re.IGNORECASE)
_PLOT_NO_RE = re.compile(
    r"(?:plot\s*(?:no\.?|number|#)?|plot\s*#)\s*[:#.]?\s*(\d{2,5})\b",
    re.IGNORECASE)

_FEATURE_KEYS = ("corner", "sun_facing", "park_facing", "main_boulevard",
                 "road_facing")

_FEATURE_LABEL = {
    "corner": "corner",
    "sun_facing": "sun-facing",
    "park_facing": "park-facing",
    "main_boulevard": "main-boulevard",
    "road_facing": "road-facing",
    "ndc_open": "NDC open",
}

# The question to ask, in priority order, when a requirement is missing.
_QUESTION_FOR = {
    "block": "which block would you prefer - for example A, B or C?",
    "size_marla": "what plot size should I look for, in marla?",
    "budget_max_pkr": "what budget should I work within?",
    "purpose": "is this for investment or for your own residence?",
    "timeline": "what timeline are you working with?",
}


def extract_intent(message: Optional[str],
                   requirements: Optional[Dict[str, Any]] = None,
                   entities: Any = None) -> Dict[str, Any]:
    """The dealer's requirements for this inquiry, as one intent dict.

    ``requirements`` is the merged M9 conversation state when the caller
    has it; the current message is re-read on top so the newest statement
    wins and any field the dealer CHANGED is marked ``corrected`` - the
    operator sees exactly which requirement moved.
    """
    text = str(message or "")
    current = _qualify.extract_requirements(text)
    base = dict(requirements or {})
    if not base:
        base = _qualify.empty_requirements()

    intent: Dict[str, Any] = {}
    corrected: List[str] = []
    for key in ("block", "size_marla", "budget_min_pkr", "budget_max_pkr",
                "purpose", "timeline"):
        value = current.get(key)
        if value is None:
            value = base.get(key)
        else:
            previous = base.get(key)
            if previous is not None and previous != value:
                corrected.append(key)
        intent[key] = value

    # Facing / feature preferences, read from THIS message and carried
    # forward from the conversation only when this message is silent
    # (a preference that was stated earlier still stands).
    lowered = text.lower()
    for key, rx in (("corner", _CORNER_RE), ("sun_facing", _SUN_RE),
                    ("park_facing", _PARK_RE),
                    ("main_boulevard", _BOULEVARD_RE),
                    ("road_facing", _ROAD_RE)):
        stated = bool(rx.search(text))
        intent[key] = True if stated else bool(base.get(key))

    intent["mdc"] = bool(_MDC_RE.search(text))
    if _NDC_OPEN_RE.search(text):
        intent["ndc_open"] = True
    elif re.search(r"\bndc\s*(?:close|closed)\b", text, re.IGNORECASE):
        intent["ndc_open"] = False
    elif base.get("ndc_open") is not None:
        intent["ndc_open"] = bool(base.get("ndc_open"))
    else:
        intent["ndc_open"] = None
    intent["category"] = ("COMMERCIAL" if _COMMERCIAL_RE.search(text)
                          else (base.get("category") or "RESIDENTIAL"))
    plot = _PLOT_NO_RE.search(text)
    intent["plot_number"] = plot.group(1) if plot else None
    intent["corrected"] = corrected
    return intent


def _row_features(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "corner": bool(row.get("corner")),
        "sun_facing": bool(_boolean(row.get("sun_facing"))),
        "park_facing": bool(row.get("park_facing")),
        "main_boulevard": bool(row.get("main_boulevard")),
        "road_facing": bool(row.get("road_facing")),
        "ndc_open": _boolean(row.get("ndc_open")),
    }


def _row_price(row: Dict[str, Any]) -> Optional[float]:
    return _number(row.get("price_median_pkr"))


def _score_row(row: Dict[str, Any], intent: Dict[str, Any]) -> Dict[str, Any]:
    """Score one inventory row against the intent, with the reasons.

    The ranking is deliberately transparent: block fit, size fit, budget
    fit, feature fit, data completeness and recency, in that weight
    order. Every point is reported back as a human-readable reason, so
    the operator sees WHY an option ranked where it did.
    """
    score = 0.0
    reasons: List[str] = []
    trade_offs: List[str] = []
    features = _row_features(row)
    row_block = canonical_block(row.get("block"))
    row_size = _number(row.get("size_marla"))
    row_price = _row_price(row)

    wanted_block = canonical_block(intent.get("block"))
    wanted_size = _number(intent.get("size_marla"))
    b_min = _number(intent.get("budget_min_pkr"))
    b_max = _number(intent.get("budget_max_pkr"))

    if wanted_block and row_block == wanted_block:
        score += 40
        reasons.append("same block as requested")
    elif wanted_block:
        trade_offs.append("different block than requested")

    if wanted_size is not None and row_size is not None:
        if abs(row_size - wanted_size) <= 0.01:
            score += 30
            reasons.append("exact size match")
        elif abs(row_size - wanted_size) <= 2.5:
            score += 12
            if row_size > wanted_size:
                trade_offs.append("larger size than requested")
            else:
                trade_offs.append("smaller size than requested")
        else:
            trade_offs.append("quite a different size than requested")

    if row_price is not None:
        score += 8                     # priced rows rank over unpriced ones
        if b_max is not None:
            if row_price <= b_max:
                score += 20
                reasons.append("asking price fits the stated budget")
            elif row_price <= b_max * 1.15:
                score += 8
                trade_offs.append(
                    "asking price sits slightly above the stated budget")
            else:
                trade_offs.append(
                    "asking price is above the stated budget")
        if b_min is not None and row_price < b_min:
            score += 6
            trade_offs.append("asking price is below the stated minimum")
    elif wanted_size is not None or wanted_block:
        trade_offs.append("no asking price recorded for this option")

    matched_features = []
    for key in _FEATURE_KEYS:
        if intent.get(key) and features.get(key):
            score += 8
            matched_features.append(_FEATURE_LABEL[key])
    if matched_features:
        reasons.append("matches the requested " + ", ".join(matched_features))
    for key in _FEATURE_KEYS:
        if intent.get(key) and not features.get(key):
            trade_offs.append(
                "not %s" % _FEATURE_LABEL[key])

    if intent.get("ndc_open") and features.get("ndc_open"):
        score += 8
        reasons.append("NDC open as requested")
    elif intent.get("ndc_open") and features.get("ndc_open") is False:
        trade_offs.append("NDC not open")

    if intent.get("plot_number"):
        if str(row.get("plot_number", "")).strip() == \
                str(intent["plot_number"]).strip():
            score += 60
            reasons.append("the exact plot number requested")

    # completeness and recency: a fuller, fresher row is the better
    # representative of its cell
    if row.get("latest_date"):
        score += 2
        try:
            row_date = datetime.strptime(str(row["latest_date"])[:10],
                                         "%Y-%m-%d")
            days = max(0, (datetime(2026, 10, 24) - row_date).days)
            score += max(0.0, 8 - days / 7.0)
        except ValueError:
            pass

    return {
        "score": round(score, 2),
        "reasons": reasons,
        "trade_offs": trade_offs,
        "features": features,
    }


def match_properties(intent: Dict[str, Any],
                     policies: Optional[Dict[str, Any]] = None,
                     inventory: Optional[List[Dict[str, Any]]] = None,
                     cells: Optional[List[tuple]] = None
                     ) -> Dict[str, Any]:
    """Rank the approved inventory for one intent.

    ``cells`` optionally lists the (block, size) cells the decision
    already verified for this turn. When given, the best row of each
    such cell is guaranteed a place among the alternatives (the
    decision, not the raw score, decides which cells the reply may
    talk about), so the customer text always explains the very options
    the decision offered.

    Returns the operator-facing structure:

        {
          "intent": {...},
          "best":      {plot-level option} | None,
          "alternatives": [up to 3 plot-level options],
          "missing":   [requirement keys still unknown],
          "question":  "the single next most useful question" | "",
          "escalate":  False,       # matching never escalates by itself;
                                    # the policy/decision layer owns that
        }

    Only rows inside the configured active blocks are considered, exactly
    like the lookup: a parked block can never be recommended.
    """
    config = policies if policies is not None else load_policies()
    rows = (inventory if inventory is not None
            else _active_scope_inventory(
                list(config.get("active_blocks", ["A", "B", "C"]))))

    wanted_block = canonical_block(intent.get("block"))
    wanted_size = _number(intent.get("size_marla"))
    wanted_plot = intent.get("plot_number")

    scored = []
    for row in rows:
        row_block = canonical_block(row.get("block"))
        row_size = _number(row.get("size_marla"))
        info = _score_row(row, intent)
        # a requested block concentrates the search but does not blind it:
        # rows from the requested block come first, rows from the other
        # active blocks can still become alternatives with the trade-off
        # named openly.
        block_penalty = 0 if (not wanted_block or row_block == wanted_block) \
            else 25
        if block_penalty:
            info["score"] = round(max(0.0, info["score"] - block_penalty), 2)
        scored.append((info["score"], row_block, row_size,
                       str(row.get("plot_number", "")), row, info))

    scored.sort(key=lambda item: (-item[0], item[1] or "", item[2] or 0,
                                  item[3]))

    def _identity(row):
        return (canonical_block(row.get("block")),
                str(row.get("plot_number", "")).strip().upper())

    def _to_option(row, info):
        return {
            "inventory_id": (row.get("source_ref") or {}).get("inventory_id")
            or row.get("inventory_id"),
            "block": canonical_block(row.get("block")),
            "size_marla": _number(row.get("size_marla")),
            "plot_number": row.get("plot_number"),
            "price_min_pkr": _number(row.get("price_min_pkr")),
            "price_median_pkr": _row_price(row),
            "price_max_pkr": _number(row.get("price_max_pkr")),
            "latest_date": row.get("latest_date"),
            "features": info["features"],
            "score": info["score"],
            "reasons": info["reasons"],
            "trade_offs": info["trade_offs"],
        }

    def _pick(rows_iter):
        """Turn the next usable scored row into an option."""
        for score, _b, _s, plot_key, row, info in rows_iter:
            if score <= 0:
                continue
            identity = _identity(row)
            if identity in used_plots:
                continue
            used_plots.add(identity)
            return _to_option(row, info)
        return None

    best = None
    alternatives = []
    used_plots = set()

    # 1. the best option overall
    best = _pick(scored)

    # 2. the decision's verified cells, ALWAYS represented: the best row
    #    of each cell the decision kept becomes an alternative before the
    #    general ranking fills the rest, so the customer text explains
    #    the very options the decision offered.
    for cell_block, cell_size in (cells or []):
        if len(alternatives) >= 3:
            break
        cell_block_code = canonical_block(cell_block)
        cell_size_num = _number(cell_size)
        if best is not None and best["block"] == cell_block_code and \
                (cell_size_num is None
                 or best["size_marla"] == cell_size_num):
            # the best option already sits in this cell
            continue
        cell_rows = [
            item for item in scored
            if item[0] > 0
            and canonical_block(item[4].get("block")) == cell_block_code
            and (cell_size_num is None
                 or _number(item[4].get("size_marla")) == cell_size_num)
        ]
        chosen = _pick(cell_rows)
        if chosen is not None:
            alternatives.append(chosen)

    # 3. top up with the best remaining rows overall
    while len(alternatives) < 3:
        chosen = _pick(scored)
        if chosen is None:
            break
        if chosen["block"] == (best or {}).get("block") and \
                chosen["plot_number"] == (best or {}).get("plot_number") \
                and best is not None:
            continue
        alternatives.append(chosen)

    missing = [key for key in ("block", "size_marla", "budget_max_pkr",
                               "purpose", "timeline")
               if intent.get(key) in (None, "")]
    question = ""
    for key in ("budget_max_pkr", "block", "size_marla", "purpose",
                "timeline"):
        if intent.get(key) in (None, ""):
            question = _QUESTION_FOR[key]
            break

    return {
        "intent": {k: v for k, v in intent.items()},
        "best": best,
        "alternatives": alternatives,
        "missing": missing,
        "question": question,
        "escalate": False,
    }


def _size_words(size: Any) -> str:
    number = _number(size)
    if number is None:
        return ""
    if float(number).is_integer():
        return "%d" % int(number)
    return ("%g" % number)


def _option_phrase(option: Dict[str, Any],
                   with_features: bool = True) -> str:
    parts = []
    size = _size_words(option.get("size_marla"))
    if size:
        parts.append("%s marla" % size)
    if option.get("block"):
        parts.append("plot in Block %s" % option["block"])
    if with_features:
        feats = [_FEATURE_LABEL[k] for k in _FEATURE_KEYS
                 if option.get("features", {}).get(k)]
        if feats:
            parts.append("(" + ", ".join(feats) + ")")
    if not parts:
        return "a recorded option"
    return "a " + " ".join(parts)


# P1 (M12.4 review): the base template's trailing ask, which becomes
# stale whenever the M13 section asks its own targeted question.
_BASE_ASK_RE = re.compile(
    r"\s*Tell me your preferred size or block and I can narrow them "
    r"down\.\s*",
    re.IGNORECASE,
)


def suppress_base_question(base: str) -> str:
    """P1 — one question per reply.

    Removes the base template's trailing clarification ask so the reply
    asks exactly one question: the M13 section's targeted one. Worded as
    a plain removal of a template sentence: no figure, claim, scope or
    availability text is touched, so the M5 validator and the M6.1
    guard judge the remaining reply with unchanged rules. When the base
    does not carry the ask (or the caller passes nothing), the text is
    returned unchanged.
    """
    if not base:
        return base
    out = _BASE_ASK_RE.sub(" ", base, count=1)
    return re.sub(r"  +", " ", out).strip()


def conversational_section(match: Dict[str, Any],
                           permitted_pairs: List[tuple]) -> str:
    """The customer-safe conversational text, appended to the draft.

    ``permitted_pairs`` is the list of (block, size) pairs the M9
    decision already verified for this turn - the quoted cell plus the
    decision's alternative cells. Only pairs from this list are named,
    so the M6.1 claim guard stays the authority on what the reply may
    claim. The text carries no figure >= 1000, no currency token and no
    availability word, so the M5 numeric validator finds nothing new to
    judge.

    When the closest recorded option sits in a cell the evidence
    threshold does not let the reply name, the section does not quote
    it - it explains why the named options match instead, so the reply
    stays honest without repeating the base wording verbatim.
    """
    allowed = {(str(b).upper(), _size_words(s)) for b, s in permitted_pairs}
    # a permitted pair with no size ("Block C corner plot") names the
    # whole block: any size inside it may be described
    allowed_blocks = {b for b, s in allowed if s == ""}

    def _pair(option):
        return (str(option.get("block") or "").upper(),
                _size_words(option.get("size_marla")))

    def _permitted(option):
        block, size = _pair(option)
        return (block, size) in allowed or block in allowed_blocks

    best = match.get("best")
    alternatives = [a for a in match.get("alternatives", [])
                    if _permitted(a)][:3]
    sentences: List[str] = []

    if best is not None and _permitted(best):
        sentences.append(
            "Based on what you have told me, the closest recorded option "
            "in the current approved inventory data is %s."
            % _option_phrase(best))
        if best.get("reasons"):
            sentences.append("Why it matches: %s."
                             % "; ".join(best["reasons"][:3]))
        for alt in alternatives:
            trade = ""
            if alt.get("trade_offs"):
                trade = " - %s" % alt["trade_offs"][0]
            sentences.append("Another option worth comparing: %s%s."
                             % (_option_phrase(alt), trade))
        trade_bits = [t for alt in alternatives
                      for t in alt.get("trade_offs", [])]
        if trade_bits:
            sentences.append("Trade-offs to weigh: %s."
                             % "; ".join(trade_bits[:3]))
    elif alternatives:
        reasons = []
        for a in alternatives:
            for r in a.get("reasons", []):
                if r not in reasons:
                    reasons.append(r)
        if reasons:
            sentences.append("Why these options match: %s."
                             % "; ".join(reasons[:3]))
        trade_bits = []
        for a in alternatives:
            for t in a.get("trade_offs", []):
                if t not in trade_bits:
                    trade_bits.append(t)
        if trade_bits:
            sentences.append("Trade-offs to weigh: %s."
                             % "; ".join(trade_bits[:3]))

    question = match.get("question")
    if question:
        sentences.append("To narrow this down: %s" % question)

    sentences.append(
        "These are recorded asking-price options from the current approved "
        "inventory data, not a confirmation that a plot is on the market "
        "today; a team member verifies every detail personally before "
        "anything is finalised. Human approval is required before anything "
        "is sent.")
    return " ".join(sentences)
