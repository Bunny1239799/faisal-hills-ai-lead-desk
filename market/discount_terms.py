"""D-65 - ONE shared discount-term list for the policy gate and the claim guard.

Why this module exists
-----------------------
D-65 measured a real hole: the policy gate escalated a message that
contained the word "discount", but **answered** the same request written
the way a customer actually writes it - "20% off", "knock 20 percent off",
"rebate", "reduce the price", "negotiable?". RULES_SHORT #3 requires a
discount, a negotiation or a commission discussion to **always** escalate,
so the gap was an escalation-recall hole in the safety-critical surface.

The fix must not be a second copy of a list. Two copies of a discount
list are two chances to drift, and the drift is exactly what the defect
was. So the list lives HERE, once, and both layers read it:

* `app/policy.py` - the **request** path. Any discount term escalates.
  The policy is deliberately conservative: a mention is enough.
* `market/reply_guard.py` - the **reply** path. A reply that *claims* a
  discount is refused. A reply that *refuses* one ("we cannot offer a
  discount") is a safe, correct reply and is not a claim - so the guard
  reads the same terms through a negation-aware test.

`market/reply_guard.py` is stdlib-only (RULES_SHORT #5) and must not
import `app/*`, so the shared list has to live in `market/`. It is
stdlib-only too, reads nothing, writes nothing and never calls a model.

The terms themselves are the ordinary words a dealer uses for a discount
or a negotiation, in English and in Roman Urdu, plus the Urdu script
forms the policy already used. No dealer term was invented: every term
below either already appeared in `app/policy.py` / `app/policy_extra.py`,
or is the ordinary English or Roman-Urdu way of saying the same thing
("off", "rebate", "knock ... off", "reduce the price", "negotiable",
"kam"). Nothing here is a business definition.
"""

from __future__ import annotations

import re
from typing import List, Optional, Sequence, Tuple

__all__ = [
    "DISCOUNT_TERMS",
    "REFUSAL_MARKERS",
    "detect_discount_request",
    "detect_discount_claim",
    "discount_terms_in",
]

# The price words a discount or a negotiation is asked about. A dealer
# says "price", "rate" or the Roman Urdu "qeemat" / "qimat".
_PRICE_WORD = r"(?:price|rate|rates|qeemat|qimat|keemat)"

# ---------------------------------------------------------------------------
# THE shared list
# ---------------------------------------------------------------------------
#
# Every entry is a regular expression matched against the lower-cased
# message (request path) or the raw reply (reply path). The order is
# presentation order only - every entry is OR-ed, so no entry can hide
# another.
DISCOUNT_TERMS: Tuple[str, ...] = (
    # --- the words the policy already escalated (kept verbatim) ---------
    r"\bdiscount\w*\b",
    r"\blump[\s-]?sum\b",
    r"\bconcession\w*\b",
    r"\bsecret commission\b",
    r"\bcommission\w*\b",
    r"\bkam karein\b",
    r"\bkam ho\b",
    r"\bkam kar\b",
    # --- the same request written the way a dealer writes it -----------
    r"\brebate\b",
    r"\bnegotia\w*\b",                 # negotiate / negotiation / negotiable
    r"\bbargain\w*\b",
    r"\bshav(?:e|es|ing)\b",
    r"\bsast[ae]\b",                   # Roman Urdu: cheap
    # --- a percentage, a fraction, a "percent off" ----------------------
    r"\b\d+\s*%\s*off\b",
    r"\b\d+\s*(?:percent|per\s?cent|%)\s*off\b",
    r"\b\d+\s*(?:percent|per\s?cent|%)\s*(?:discount|less|reduction)\w*\b",
    r"\bknock\w*\b[^.?]{0,40}\boff\b",
    # --- "reduce the price", "price reduce", "reduce the rate" --------
    r"\breduc\w+\s+(?:the\s+|its\s+|your\s+|our\s+)?%s\b" % _PRICE_WORD,
    r"\b%s\s+(?:reduc\w*|cut|cuts|cutting|lower\w*|drop\w*|down)\b" % _PRICE_WORD,
    r"\b%s\s+(?:kam|kam\s+kar\w*)\b" % _PRICE_WORD,
    # --- "can you do better on price", "a better rate" -----------------
    r"\bbetter\s+(?:on\s+)?(?:price|rate|rates|deal|offer)\b",
    r"\bdo\s+better\s+on\b",
    r"\bmake\s+(?:it|the\s+price|the\s+rate)\s+cheaper\b",
    # --- "a special rate", "the final rate", "the last price" ---------
    r"\bspecial\s+(?:price|rate|rates|deal|discount\w*)\b",
    r"\b(?:final|last|best|lowest|minimum)\s+(?:price|rate|rates)\b",
    # --- Roman Urdu: "kam" (less), "rate kam", "kam qeemat" -------------
    r"\bkam\b",
    r"\bkam\s+(?:qeemat|qimat|rate|price|amount|paisa)\b",
    r"\b(?:qeemat|qimat|rate|price)\s+kam\b",
    # --- Urdu script (kept from the policy gate) ------------------------
    "رعایت",
    "ڈسکاؤنٹ",
    "کم ہو",
    "کم کریں",
    "کمیشن",
    "تین لاکھ کم",
)

# The compiled form. Compiled once, at import time, from the list above -
# so the list itself remains the single readable source of truth.
DISCOUNT_TERM_RES = tuple(re.compile(pattern, re.IGNORECASE)
                           for pattern in DISCOUNT_TERMS)

# A sentence that REFUSES a discount is a correct, safe reply, not a
# discount claim. These markers are what separates them. They are used
# ONLY by the reply path; the request path never applies them, because a
# dealer who *mentions* a discount has still raised the topic and must
# reach a human.
REFUSAL_MARKERS: Tuple[str, ...] = (
    r"\bno\b",
    r"\bnot\b",
    r"\bcannot\b",
    r"\bcan\s*not\b",
    r"\bcan't\b",
    r"\bwon't\b",
    r"\bwill\s+not\b",
    r"\bunable\b",
    r"\bnot\s+able\b",
    r"\bnever\b",
    r"\bwithout\b",
    r"\brequires?\b",
    r"\brequired\b",
    r"\bapproval\b",
    r"\bour\s+team\b",
    r"\bmember\s+of\s+our\s+team\b",
)

_REFUSAL_RES = tuple(re.compile(pattern, re.IGNORECASE)
                      for pattern in REFUSAL_MARKERS)


def discount_terms_in(text: Optional[str]) -> List[str]:
    """Every discount term the text contains (the matched text itself).

    Used for reporting and for the request path's reason string.
    """
    if not text:
        return []
    found: List[str] = []
    for pattern in DISCOUNT_TERM_RES:
        for match in pattern.finditer(text):
            token = match.group(0).strip()
            if token and token not in found:
                found.append(token)
    return found


def detect_discount_request(message: Optional[str]) -> Optional[str]:
    """Whether the MESSAGE raises a discount / negotiation topic.

    Conservative on purpose: a mention is enough, and no refusal marker
    is applied here. A dealer who asks for a discount, or who says "no
    discount?" or "is there a discount?" has raised the topic and must
    reach a human (RULES_SHORT #3).

    Returns the matched term, or ``None``.
    """
    for pattern in DISCOUNT_TERM_RES:
        match = pattern.search(message or "")
        if match:
            return match.group(0)
    return None


def detect_discount_claim(sentence: Optional[str]) -> Optional[str]:
    """Whether the SENTENCE claims a discount, rather than refusing one.

    The same shared list is used, plus one extra test: a sentence that
    refuses or defers ("we cannot offer a discount", "no discount is
    available", "our team must approve any discount") is a **safe** reply
    and is not a claim.

    Returns the matched term, or ``None``.
    """
    if not sentence:
        return None

    hit = None
    for pattern in DISCOUNT_TERM_RES:
        match = pattern.search(sentence)
        if match:
            hit = match.group(0)
            break
    if hit is None:
        return None

    for pattern in _REFUSAL_RES:
        if pattern.search(sentence):
            return None

    return hit
