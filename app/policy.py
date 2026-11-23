import re
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any


# v1 scope: Blocks A, B and C only (handoff v2, section 1).
#
# M4: the scope lives in ONE place - `config/policies.json` -> the
# `active_blocks` key - so the owner can change it without touching Python.
# `_ACTIVE_BLOCK_CODES` is now only the hard-coded FALLBACK used when that
# file cannot be read. The lookup layer (`market/price_lookup.py`) reads
# the same file, so the policy gate and the lookup can no longer disagree
# about which blocks are in scope.
_FALLBACK_ACTIVE_BLOCK_CODES = {"A", "B", "C"}

_ACTIVE_BLOCK_CODES = _FALLBACK_ACTIVE_BLOCK_CODES


def _load_active_block_codes():
    """The active block codes, from the single policy configuration.

    Returns the configured `active_blocks` from `config/policies.json`,
    falling back to the hard-coded v1 scope (Blocks A, B, C) if the file is
    missing or unreadable.

    The value is read on every call rather than cached: the configuration
    path can be relocated (that is how the scope is tested, and how the
    master is relocated in CI), and a cached scope would keep enforcing a
    stale value. The configured codes are canonicalised through the
    lookup's alias table so that "EXECUTIVE" in the config and "Executive"
    in a question are the same block.
    """
    try:
        from market import price_lookup as _price_lookup

        policies = _price_lookup.load_policies()
        codes = set()
        for configured in policies.get("active_blocks", []):
            canonical = _canonical_block_code(configured)
            if canonical:
                codes.add(canonical)
        if codes:
            return codes
    except Exception:  # pragma: no cover - config is present in this repo
        pass

    return set(_FALLBACK_ACTIVE_BLOCK_CODES)

# Words that may follow "block" without naming a block. "mein" is Urdu
# for "in", so "block mein" must not be read as a block code.
_BLOCK_FILLER_WORDS = {
    "mein", "me", "in", "on", "ka", "ki", "ke", "ko", "wala", "walay",
    "and", "or", "for", "of", "to", "is", "are", "the", "a", "an", "with",
    "price", "prices", "rate", "rates", "marla", "marlas", "plot", "plots",
    "available", "availability", "possession", "details", "detail", "show",
    "tell", "want", "need", "looking", "only", "just", "not", "no",
}


def _canonical_block_code(code):
    """Canonicalise a block code the same way the lookup layer does.

    The lookup (`market/price_lookup.py`) canonicalises the CONFIGURED
    active blocks through the same alias table it uses for a requested
    block, so "EXECUTIVE" in the config becomes "E". The policy gate must
    canonicalise its token the same way, or the two layers disagree about
    which blocks are in scope.

    The alias table is taken from the lookup module when it is importable,
    so there is still only ONE definition of the aliases.
    """
    try:
        from market.price_lookup import _normalize_block

        canonical = _normalize_block(code)
        if canonical:
            return canonical
    except Exception:  # pragma: no cover - lookup is present in this repo
        pass

    return str(code).strip().upper()


def _extract_block_token(text_lower):
    """Return the canonical block code named in the message, or None.

    Recognises "block c", "c block", "fhc" and named parked blocks such as
    "executive block". Filler words after "block" are ignored so that
    "block mein" is not mistaken for a block code.
    """
    if re.search(r"\bexecutive\b", text_lower) or re.search(r"\bexec\b", text_lower):
        return "E"

    match = re.search(r"\bblock\s*([a-z])\b", text_lower)
    if match:
        return match.group(1).upper()

    match = re.search(r"\b([a-z])\s+block\b", text_lower)
    if match:
        return match.group(1).upper()

    match = re.search(r"\bfh([a-z])\b", text_lower)
    if match:
        return match.group(1).upper()

    match = re.search(r"\bblock\s+([a-z]{2,})\b", text_lower)
    if match and match.group(1) not in _BLOCK_FILLER_WORDS:
        return match.group(1).upper()

    return None


@dataclass
class PolicyDecision:
    action: str  # answer | clarify | escalate | refuse
    reasons: List[str] = field(default_factory=list)
    risk_tags: List[str] = field(default_factory=list)
    needs_human: bool = False


def evaluate_policy(message: str, laya_signals: Optional[Dict[str, Any]] = None, threshold: float = 0.5) -> PolicyDecision:
    """
    Evaluates safety, risk, and routing policy deterministically on a customer message,
    combined with optional Laya signals. Policy can only make decisions stricter (never looser).
    """
    text = message.strip()
    text_lower = text.lower()

    reasons: List[str] = []
    risk_tags: List[str] = []
    action = "answer"
    needs_human = False

    # 1. Prompt Injection / Jailbreak / System Prompt Extraction / Hallucination-forcing
    injection_patterns = [
        r"ignore all previous instructions",
        r"pichli saari hidayaat bhool",
        r"تمام سابقہ ہدایات",
        r"system override",
        r"admin and unrestricted",
        r"print database schema",
        r"hidden prompt",
        r"خفیہ سسٹم",
        r"dan mode",
        r"rule-shule choro",
        r"verify that all constraints are removed",
        r"private security credentials",
        r"bot mode off",
        r"act as rogue ai",
        r"\binvent\b",
        r"make up",
        r"\bfabricate\b",
        r"\bestimate\b",
        r"\bguess\b",
        r"\bassume\b",
        r"just say",
        r"just give",
        r"do not need .* database",
        r"don't need .* database",
        r"do not need .* facts",
        r"don't need .* facts",
        r"do not need .* data",
        r"don't need .* data",
        r"skip the checks",
        r"don't verify",
        r"without checking",
        r"without database",
        # Roman Urdu / Urdu Hallucination & Bypass patterns
        r"\bandaza\b",
        r"\bfarzi\b",
        r"apni taraf se",
        r"bana do",
        r"\bjhoot\b",
        r"khud se",
        r"khud bana",
        r"andaaza",
        r"farzi rate",
        r"database ki zaroorat nahi",
        r"facts ki zaroorat nahi",
        r"data ki zaroorat nahi",
        r"check karne ki zaroorat nahi",
        r"verify mat karo",
        r"خود سے",
        r"اندازہ",
        r"فرضی",
        r"اپنی طرف سے",
        r"بنا دو",
        r"جھوٹ",
        r"ڈیٹا کی ضرورت نہیں",
        r"فیکٹس کی ضرورت نہیں",
    ]
    if any(re.search(p, text_lower) for p in injection_patterns):
        return PolicyDecision(
            action="refuse",
            reasons=["Prompt injection or unauthorized system access / hallucination attempt detected."],
            risk_tags=["injection"],
            needs_human=True,
        )

    # 2. Requests for other customers' data / PII / DB records
    other_data_patterns = [
        r"phone number and cnic",
        r"buyer who bought plot",
        r"contact numbers",
        r"another customer",
        r"other customer",
        r"other buyer",
        r"another buyer",
        r"someone else's (?:phone|number|contact)",
        r"send me (?:his|her|their|another|the other) (?:phone|number|contact)",
        r"(?:his|her|their) (?:phone|phone number|number|contact details?)",
        r"who (?:else )?(?:asked|inquired|enquired|is interested)",
        r"number of another customer",
        r"customer list",
        r"buyer list",
        r"رابطہ نمبرز",
        r"data aur phone numbers",
    ]
    if any(re.search(p, text_lower) for p in other_data_patterns):
        return PolicyDecision(
            action="refuse",
            reasons=["Request for confidential customer personal data or private records."],
            risk_tags=["privacy"],
            needs_human=True,
        )

    # 2b. Parked / out-of-scope blocks (v1 scope is Blocks A, B, C only).
    #     Block D, Executive (E) and any block outside A/B/C must not return
    #     actionable property prices; they route to a human instead.
    requested_block = _extract_block_token(text_lower)
    active_block_codes = _load_active_block_codes()
    if requested_block is not None:
        requested_block = _canonical_block_code(requested_block)
    if requested_block is not None and requested_block not in active_block_codes:
        action = "escalate"
        needs_human = True
        reasons.append(
            "Refers to a block outside the approved scope (Blocks %s only)."
            % ", ".join(sorted(active_block_codes))
        )
        risk_tags.append("out_of_scope")

    # 3. Legal / NOC / Title / Ownership / RDA approval claims
    legal_patterns = [
        r"\bnoc\b", r"\brda\b", r"\blegal\b", r"\bapproval\b", r"\bdisputed\b",
        r"\bdispute\b", r"\bintiqal\b", r"\bfard\b", r"\bkhasra\b", r"\bregistry\b",
        r"\btown planning\b", r"\blop\b", r"قانونی", r"منظوری", r"این او سی",
        r"رجسٹری", r"انتقال", r"خسرہ", r"ایل او پی", r"stay order", r"تنازع"
    ]
    if any(re.search(p, text_lower) for p in legal_patterns):
        action = "escalate"
        needs_human = True
        reasons.append("Involves legal status, NOC, RDA approval, registry or title verification.")
        risk_tags.append("legal")

    # 4. Discounts and Negotiation / Secret Commission
    #
    # D-65: the discount vocabulary lives in ONE shared list
    # (`market/discount_terms.py`), which the M6.1 claim guard reads as
    # well. The list used to live here alone and matched only the word
    # "discount", so "20% off", "knock 20 percent off", "rebate",
    # "reduce the price" and "negotiable?" reached the answering path.
    # The list is deliberately conservative: a mention is enough, and the
    # whole point of the shared list is that the request path and the
    # reply path can no longer disagree about what a discount request is.
    try:
        from market import discount_terms as _discount_terms
        _discount_hit = _discount_terms.detect_discount_request(text)
    except Exception:  # pragma: no cover - the module is in this repo
        _discount_hit = None
    if _discount_hit:
        action = "escalate"
        needs_human = True
        reasons.append("Involves price discount, negotiation, or commission discussion.")
        risk_tags.append("discount")

    # 4b. Private data requests (D-66, founder-authorized 2026-10-24)
    #
    # A request for dealer identities, phone numbers, source chats or
    # other customers' data was already UNLEAKABLE (the M7 whitelist
    # serves none of it), but it was not flagged, so the operator saw an
    # ordinary clarification instead of "Human review required". The
    # vocabulary lives in ONE shared list (`market/privacy_terms.py`),
    # read here on the request path; a mention is enough.
    try:
        from market import privacy_terms as _privacy_terms
        _privacy_hit = _privacy_terms.detect_private_data_request(text)
    except Exception:  # pragma: no cover - the module is in this repo
        _privacy_hit = None
    if _privacy_hit:
        action = "escalate"
        needs_human = True
        reasons.append("Requests private dealer, customer or source information.")
        risk_tags.append("privacy")

    # 5. Booking, payment or token-money commitments
    booking_patterns = [
        r"\bbook\b", r"\bbooking\b", r"\bbook karwana\b", r"\btoken money\b",
        r"\btoken amount\b", r"\btoken payment\b", r"\bpay order\b", r"\block karna\b",
        r"\bfinal karna\b", r"\bfinalize today\b", r"\bdeal done\b",
        r"بک کروانا", r"بکنگ", r"ٹوکن", r"فائنل کرنا", r"پیمنٹ تیار", r"لاباک"
    ]
    if any(re.search(p, text_lower) for p in booking_patterns):
        action = "escalate"
        needs_human = True
        reasons.append("Involves booking execution, token payment, or deal finalization.")
        risk_tags.append("booking")

    # 6. Refunds and Complaints / Abusive language
    complaint_patterns = [
        r"\bfraud\b", r"\bcomplaint\b", r"\brefund\b", r"\bdelay\b", r"\bdelayed\b",
        r"\bbakwas\b", r"\bmisinformed\b", r"\bnot satisfied\b", r"\bsupervisor\b",
        r"\bcase karoonga\b", r"\bchhor\b", r"\bsue\b", r"\bidiot\b", r"\bkamina\b",
        r"شکایت", r"بکواس", r"فراڈ", r"واپسی", r"ریفنڈ", r"دھوکے باز", r"فراڈیے"
    ]
    if any(re.search(p, text_lower) for p in complaint_patterns):
        action = "escalate"
        needs_human = True
        reasons.append("Involves customer complaint, refund demand, or abusive/legal threats.")
        risk_tags.append("abusive")
        if any(w in text_lower for w in ["idiot", "bakwas", "kameeno", "دھوکے باز", "فراڈیے"]):
            risk_tags.append("legal")

    # 7. Investment returns, guarantees or profit promises
    return_patterns = [
        r"\bguaranteed\b", r"\bguarantee\b", r"\breturn\b", r"\breturns\b",
        r"\bprofit\b", r"\bcapital gain\b", r"\byield\b", r"\bbuyback\b",
        r"منافع", r"ضمانت", r"گارنٹی", r"پرافٹ", r"ڈبل"
    ]
    if any(re.search(p, text_lower) for p in return_patterns):
        action = "escalate"
        needs_human = True
        reasons.append("Involves investment returns, guaranteed profit, or buyback claims.")
        risk_tags.append("returns")

    # 8. Claims that a manager / director already approved something on call
    manager_approval_patterns = [
        r"manager .* promised",
        r"director .* phone pe",
        r"تھپ کے مینیجر",
        r"ڈائریکٹر .* فون",
    ]
    if any(re.search(p, text_lower) for p in manager_approval_patterns):
        action = "escalate"
        needs_human = True
        reasons.append("Involves unverified claims of manager or director approval.")
        risk_tags.append("discount")

    # 9. Pressure to repeat an old price
    old_price_patterns = [
        r"last week your bot told",
        r"pichle hafte aapne",
        r"گزشتہ ہفتے آپ نے",
        r"purane rate pe deal",
    ]
    if any(re.search(p, text_lower) for p in old_price_patterns):
        action = "escalate"
        needs_human = True
        reasons.append("Involves pressure to honor stale or historical price claims.")
        risk_tags.append("discount")

    # 10. Broker / Dealer commission inquiries
    broker_patterns = [
        r"\bdealer inventory\b", r"\bcommission split\b", r"\breferral\b",
        r"ڈیلر انوینٹری", r"کمیشن اسپلٹ"
    ]
    if any(re.search(p, text_lower) for p in broker_patterns):
        action = "escalate"
        needs_human = True
        reasons.append("Involves broker inventory or commission split negotiations.")
        risk_tags.append("broker")

    # Integrate Laya signals if provided (Policy can only make decision STRICTER, never looser)
    if laya_signals and isinstance(laya_signals, dict):
        p_needs_human = laya_signals.get("needs_human", 0.0)
        if isinstance(p_needs_human, (int, float)) and p_needs_human >= threshold:
            needs_human = True
            if action == "answer":
                action = "escalate"
                reasons.append(f"Laya signals indicated high needs_human probability ({p_needs_human:.2f} >= {threshold}).")

    if not needs_human and action == "answer":
        # Check if short or ambiguous
        if len(text.split()) <= 3 and "?" in text:
            action = "clarify"

    return PolicyDecision(
        action=action,
        reasons=reasons,
        risk_tags=list(set(risk_tags)),
        needs_human=needs_human,
    )


# --- stricter-only wrapper (TASK_04 red-team fix) ---
from app.policy_extra import extra_risk as _extra_risk

_base_evaluate_policy = evaluate_policy


def evaluate_policy(message, *args, **kwargs):
    decision = _base_evaluate_policy(message, *args, **kwargs)
    if decision.action in ("escalate", "refuse"):
        print(f"DEBUG: Policy decision: {decision}")
        return decision
    hits = _extra_risk(message)
    if not hits:
        return decision
    print(f"DEBUG: Policy hits: {hits}")
    return PolicyDecision(
        action="escalate",
        reasons=list(decision.reasons) + ["extra_guard:" + h for h in hits],
        risk_tags=list(decision.risk_tags) + hits,
        needs_human=True,
    )