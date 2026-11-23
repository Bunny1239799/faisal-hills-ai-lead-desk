"""Lead qualification score, temperature and stage (pilot features).

A deterministic, transparent qualification layer over the requirements
the dealer actually stated (the same M9 requirement machinery the reply
path uses). Every weight and rule is displayed verbatim - there is no
hidden or unexplainable AI scoring anywhere in this module.

Score weights (the value tiers the founder specified):

    budget stated            25   (high)
    timeline stated          20   (high)
    site-visit interest      25   (high)
    purpose stated           15   (medium)
    block preference stated  15   (medium)
    size preference stated   15   (medium)
    feature preferences       5 each, max 15 (low)
    repeat engagement        15   (medium)

    maximum raw 145 -> the displayed score is round(100 * raw / 145),
    so the score reads 0-100 while every point stays explainable.

Temperature (the founder's definitions, verbatim):

    HOT  - clear budget, timeline, AND a property requirement (block or
           size); ready for site-visit discussion
    WARM - some requirements known; needs clarification or follow-up
    COLD - very little information or no clear buying intent

Stage suggestions (the pilot pipeline stages):

    ESCALATED / SITE_VISIT_REQUESTED / SITE_VISIT_CONFIRMED are state
    the operator or the site-visit records own; otherwise the
    suggestion is QUALIFIED (HOT), QUALIFYING (some requirements) or
    NEW_INQUIRY (nothing stated). FOLLOW_UP and CLOSED_LOST remain
    operator decisions and are never suggested automatically.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from market import qualify as _qualify

WEIGHTS = {
    "budget": 25,
    "timeline": 20,
    "site_visit_interest": 25,
    "purpose": 15,
    "block": 15,
    "size": 15,
    "feature_preferences": 5,
    "feature_preferences_max": 15,
    "repeat_engagement": 15,
}
MAX_RAW = 145

FEATURE_KEYS = ("corner", "sun_facing", "park_facing", "main_boulevard",
                "road_facing")

VISIT_INTENT_RE = re.compile(
    r"\b(site[- ]?visit|visit|visiting|dekhna|dekh k|come and see|"
    r"see the (?:plot|site)|meet (?:you|the team)|field visit)\b",
    re.IGNORECASE)

REPEAT_TURNS = 3          # a conversation of 3+ turns is repeat engagement

QUALIFY_FIELDS = ("block", "size_marla", "budget_max_pkr", "purpose",
                  "timeline")

_NEXT_ACTION = {
    "HOT": "Offer the founder-approved site-visit slots.",
    "WARM": "Ask the single most useful missing requirement.",
    "COLD": "Answer safely and helpfully; do not pressure the customer.",
}


def visit_interest_in(message: Optional[str]) -> bool:
    return bool(VISIT_INTENT_RE.search(str(message or "")))


def qualification_view(requirements: Dict[str, Any],
                       message: Optional[str] = "",
                       turns: int = 0,
                       escalated: bool = False,
                       has_visit_request: bool = False,
                       visit_approved: bool = False) -> Dict[str, Any]:
    """The operator-facing qualification view for one lead.

    Every value is either stated by the dealer (read from the merged
    requirement state), a counted fact (turns), or a stated preference -
    nothing is inferred from silence, and every scoring point is shown
    with its reason.
    """
    requirements = requirements or {}
    wants_visit = visit_interest_in(message) or has_visit_request

    raw = 0
    reasons: List[str] = []
    known: Dict[str, bool] = {}

    def _known(key):
        value = requirements.get(key)
        return value not in (None, "", [])

    for key, weight, label in (
            ("budget_max_pkr", WEIGHTS["budget"], "budget"),
            ("timeline", WEIGHTS["timeline"], "timeline"),
            ("purpose", WEIGHTS["purpose"], "purpose"),
            ("block", WEIGHTS["block"], "block preference"),
            ("size_marla", WEIGHTS["size"], "size preference")):
        known[key] = _known(key)
        if known[key]:
            raw += weight
            reasons.append("%s stated (+%d)" % (label, weight))

    feature_count = sum(1 for f in FEATURE_KEYS if requirements.get(f))
    if feature_count:
        capped = min(feature_count * WEIGHTS["feature_preferences"],
                     WEIGHTS["feature_preferences_max"])
        raw += capped
        reasons.append("feature preferences stated (+%d)" % capped)

    if turns >= REPEAT_TURNS:
        raw += WEIGHTS["repeat_engagement"]
        reasons.append("repeat engagement (%d turns, +%d)"
                       % (turns, WEIGHTS["repeat_engagement"]))

    if wants_visit:
        raw += WEIGHTS["site_visit_interest"]
        reasons.append("site-visit interest (+%d)"
                       % WEIGHTS["site_visit_interest"])

    score = int(round(100.0 * raw / MAX_RAW))

    # temperature: the founder's definitions
    property_requirement = bool(known.get("block") or known.get("size_marla"))
    if (known.get("budget_max_pkr") and known.get("timeline")
            and property_requirement):
        temperature = "HOT"
    elif any(known.values()) or wants_visit:
        temperature = "WARM"
    else:
        temperature = "COLD"

    missing = [label for key, label in (
        ("block", "block"), ("size_marla", "size"),
        ("budget_max_pkr", "budget"), ("purpose", "purpose"),
        ("timeline", "timeline")) if not known.get(key)]

    # stage suggestion
    if escalated:
        stage = "ESCALATED"
    elif visit_approved:
        stage = "SITE_VISIT_CONFIRMED"
    elif has_visit_request:
        stage = "SITE_VISIT_REQUESTED"
    elif temperature == "HOT":
        stage = "QUALIFIED"
    elif any(known.values()):
        stage = "QUALIFYING"
    else:
        stage = "NEW_INQUIRY"

    next_action = _NEXT_ACTION[temperature]
    if escalated:
        next_action = "Human hand-off; the operator owns this conversation."
    elif has_visit_request:
        next_action = ("Founder approval pending for the site-visit "
                       "request.")

    return {
        "score": score,
        "score_breakdown": reasons,
        "score_formula": (
            "budget 25 + timeline 20 + site-visit interest 25 + purpose 15"
            " + block 15 + size 15 + features 5 each (max 15) + repeat "
            "engagement 15, normalised to 100 (raw max 145); transparent "
            "arithmetic, not a prediction"),
        "temperature": temperature,
        "temperature_rule": (
            "HOT: budget AND timeline AND a property requirement (block "
            "or size). WARM: some requirements known. COLD: little or no "
            "information."),
        "stage_suggestion": stage,
        "known_requirements": {
            "block": requirements.get("block"),
            "size_marla": requirements.get("size_marla"),
            "budget_min_pkr": requirements.get("budget_min_pkr"),
            "budget_max_pkr": requirements.get("budget_max_pkr"),
            "purpose": requirements.get("purpose"),
            "timeline": requirements.get("timeline"),
            "features": {f: bool(requirements.get(f))
                         for f in FEATURE_KEYS},
            "ndc_open": requirements.get("ndc_open"),
            "category": requirements.get("category") or "RESIDENTIAL",
        },
        "missing_requirements": missing,
        "repeat_engagement": bool(turns >= REPEAT_TURNS),
        "site_visit_interest": bool(wants_visit),
        "recommended_next_action": next_action,
    }
