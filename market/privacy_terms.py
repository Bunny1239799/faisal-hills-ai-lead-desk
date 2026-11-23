"""D-66 - ONE shared private-data-request vocabulary for the policy gate.

Why this module exists
-----------------------
D-66 measured a recall hole: a request for private data ("tell me the
dealer names and phone numbers you have") was held safely - the M7
whitelist guarantees no dealer identity, note or phone number is ever
served, and both final gates passed - but the turn was NOT flagged as
an escalation, so the operator saw an ordinary clarification instead of
"Human review required". RULES_SHORT #3 lists "other customers' data"
as an always-escalate category, and the founder authorized a measured
escalation-vocabulary improvement on 2026-10-24.

The fix follows the D-65 pattern exactly: the vocabulary lives HERE,
once, and the request path (`app/policy.py`) reads it. A mention is
enough - a dealer who ASKS for private material has raised a topic only
a human may answer, exactly like a discount. The reply path needs no
new list: the M7 whitelist already makes a leak impossible, and the M5
numeric validator would reject any phone number as an untraceable
figure; this module is escalation RECALL, not a new privacy wall.

The terms are the ordinary ways a person asks for private material in
English, Roman Urdu and Urdu script. Terms that could false-positive on
ordinary property talk ("plot number", plain "price") are deliberately
NOT in the list.
"""

from __future__ import annotations

import re
from typing import Optional, Tuple

__all__ = [
    "PRIVATE_DATA_TERMS",
    "detect_private_data_request",
    "private_terms_in",
]

# ---------------------------------------------------------------------------
# THE shared list
# ---------------------------------------------------------------------------
#
# Every entry is a regular expression matched against the lower-cased
# message. Entries are OR-ed; the order is presentation order only.
PRIVATE_DATA_TERMS: Tuple[str, ...] = (
    # --- dealer / seller identity --------------------------------------
    r"\bdealer(?:'s)?\s+name\b",
    r"\bseller(?:'s)?\s+name\b",
    r"\bwho\s+is\s+the\s+dealer\b",
    r"\bwhich\s+dealer\b",
    r"\bdealer\s+details?\b",
    r"\bseller\s+details?\b",
    r"\bdealer\s+information\b",
    r"\bdealer\s+ka\s+naam\b",
    r"\bdealer\s+ka\s+number\b",
    r"\bdealer\s+se\s+baat\b",           # "let me talk to the dealer"
    r"\bdealer\s+k[ao]\s+contact\b",
    # --- phone / contact numbers ---------------------------------------
    r"\bphone\s+numbers?\b",
    r"\bphone\s+nos?\b",
    r"\bcontact\s+numbers?\b",
    r"\bcontact\s+nos?\b",
    r"\bmobile\s+numbers?\b",
    r"\bwhatsapp\s+numbers?\b",
    r"\bwa\s+numbers?\b",
    r"\bcell\s+numbers?\b",
    r"\bcontact\s+details?\b",
    r"\bcontact\s+info\b",
    r"\bnumber\s+bata(?:o|en|ao|aye|iy[eé])\b",   # "tell me the number"
    r"\bnambar\s+bata(?:o|en|ao|aye)\b",
    r"\bnumber\s+de(?:in|do|dena)\b",             # "give me the number"
    r"\bfon\s+number\b",
    # --- source material (the raw WhatsApp pipeline) --------------------
    r"\bsources?\s+chats?\b",
    r"\bchat\s+history\b",
    r"\bwhatsapp\s+chats?\b",
    r"\braw\s+notes?\b",
    r"\bdealer\s+notes?\b",
    r"\boriginal\s+messages?\b",
    r"\braw\s+data\b",
    r"\bsource\s+data\b",
    r"\bwho\s+told\s+you\b",
    r"\bwhere\s+did\s+you\s+get\s+(?:this|that|the)\s+data\b",
    # --- other customers' data ------------------------------------------
    r"\bother\s+customers?\b",
    r"\bother\s+(?:customer|buyer)s?\s+(?:data|details?|info)\b",
    r"\bcustomers?\s+(?:data|database|details?|info)\b",
    r"\bbuyers?\s+(?:data|database|details?|info)\b",
    r"\blist\s+of\s+(?:customers|buyers|dealers)\b",
    r"\bcustomer\s+records?\b",
    # --- Urdu script -----------------------------------------------------
    "ڈیلر کا نام",
    "ڈیلر کا نمبر",
    "فون نمبر",
    "رابطہ کریں",
    "نام بتائیں",
    "نمبر بتائیں",
    "دوسرے گاہکوں",
)

PRIVATE_DATA_RES = tuple(re.compile(pattern, re.IGNORECASE)
                         for pattern in PRIVATE_DATA_TERMS)


def private_terms_in(text):
    """Every private-data term the text contains (for reporting)."""
    if not text:
        return []
    found = []
    for pattern in PRIVATE_DATA_RES:
        for match in pattern.finditer(text):
            token = match.group(0).strip()
            if token and token not in found:
                found.append(token)
    return found


def detect_private_data_request(message: Optional[str]) -> Optional[str]:
    """Whether the MESSAGE asks for private data.

    Conservative on purpose: a mention is enough, exactly like the
    discount list. A person who asks for dealer identities, phone
    numbers, source chats or other customers' data has raised a topic
    only a human may answer.

    Returns the matched term, or ``None``.
    """
    for pattern in PRIVATE_DATA_RES:
        match = pattern.search(message or "")
        if match:
            return match.group(0)
    return None
