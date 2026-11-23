import re
from typing import Dict, Any


def classify_rules(message: str) -> Dict[str, Any]:
    """
    Classifies a customer message for:
    - lead_type: 'buyer', 'investor', 'renter', 'broker', 'existing_customer', 'other'
    - high_intent: bool
    - needs_human: bool
    
    Supports English, Urdu script, and Roman Urdu.
    """
    text = message.strip()
    text_lower = text.lower()

    # ----------------------------------------------------
    # 1. Needs Human Detection (Risk / Legal / Booking / Discount / Escalation)
    # ----------------------------------------------------
    # Legal / NOC / Approval
    legal_patterns = [
        r"\bnoc\b", r"\brda\b", r"\blegal\b", r"\bapproval\b", r"\bdisputed\b",
        r"\bdispute\b", r"\bintiqal\b", r"\bfard\b", r"\bkhasra\b", r"\bregistry\b",
        r"\btown planning\b", r"\blop\b", r"قانونی", r"منظوری", r"این او سی", r"رجسٹری", r"انتقال", r"خسرہ", r"ایل او پی"
    ]
    is_legal = any(re.search(p, text_lower) for p in legal_patterns)

    # Discount / Negotiation
    discount_patterns = [
        r"\bdiscount\b", r"\bkam karein\b", r"\bkam ho\b", r"\bkam kar\b",
        r"\blump-sum discount\b", r"\bdiscount rate\b", r"\bdiscount milega\b",
        r"رعایت", r"ڈسکاؤنٹ", r"کم ہو", r"کم کریں"
    ]
    is_discount = any(re.search(p, text_lower) for p in discount_patterns)

    # Booking execution / Token payment
    booking_patterns = [
        r"\bbook\b", r"\bbooking\b", r"\bbook karwana\b", r"\bbook karwana chahta\b",
        r"\btoken money\b", r"\btoken amount\b", r"\btoken payment\b", r"\btoken diya\b",
        r"\bpay order\b", r"\block karna\b", r"\bfinal karna\b", r"\bfinalize today\b",
        r"\bdeal done\b", r"بک کروانا", r"بکنگ", r"ٹوکن", r"فائنل کرنا", r"بک کروانا چاہتا ہوں"
    ]
    is_booking = any(re.search(p, text_lower) for p in booking_patterns)

    # Investment returns / Guaranteed profit
    return_patterns = [
        r"\bguaranteed\b", r"\bguarantee\b", r"\breturn\b", r"\breturns\b",
        r"\bprofit\b", r"\bcapital gain\b", r"\byield\b", r"\bbuyback\b",
        r"منافع", r"ضمانت", r"گارنٹی", r"پرافٹ"
    ]
    is_return = any(re.search(p, text_lower) for p in return_patterns)

    # Complaint / Refund / Abusive / Existing customer issue
    complaint_patterns = [
        r"\bfraud\b", r"\bcomplaint\b", r"\brefund\b", r"\bdelay\b", r"\bdelayed\b",
        r"\bbakwas\b", r"\bmisinformed\b", r"\bnot satisfied\b", r"\bsupervisor\b",
        r"\bcase karoonga\b", r"شکایت", r"بکواس", r"فراڈ", r"واپسی", r"ریفنڈ"
    ]
    is_complaint = any(re.search(p, text_lower) for p in complaint_patterns)

    # Broker / Commission inquiries
    broker_patterns = [
        r"\bdealer\b", r"\bproperty dealer\b", r"\bcommission\b", r"\breferral\b",
        r"\bdealer inventory\b", r"\bcommission split\b", r"ڈیلر", r"کمیشن"
    ]
    is_broker = any(re.search(p, text_lower) for p in broker_patterns)

    needs_human = bool(is_legal or is_discount or is_booking or is_return or is_complaint or is_broker)

    # ----------------------------------------------------
    # 2. Lead Type Classification
    # ----------------------------------------------------
    # Renter / Rental
    rental_patterns = [
        r"\brent\b", r"\brental\b", r"\bkiraya\b", r"\bkiraye\b", r"کرایہ"
    ]
    is_rental = any(re.search(p, text_lower) for p in rental_patterns)

    # Smalltalk / Greeting only
    smalltalk_patterns = [
        r"^(hello|hi|hey|good morning|good afternoon|assalam\s*o\s*alaikum|salam|kaisay hain|kaise hain|kia haal|kya haal|sub theek|خیریت|السلام علیکم|کیا حال).{0,30}$"
    ]
    is_pure_smalltalk = any(re.search(p, text_lower) for p in smalltalk_patterns) and not any(
        re.search(w, text_lower) for w in [r"\bplot\b", r"\bmarla\b", r"\brate\b", r"\bprice\b", r"\bcost\b", r"قیمت", r"پلاٹ", r"مرلہ"]
    )

    if is_complaint:
        lead_type = "existing_customer"
    elif is_broker:
        lead_type = "broker"
    elif is_return or (re.search(r"\binvest\b|\binvestment\b|\binvestor\b|سرمایہ کاری", text_lower) and not is_booking):
        lead_type = "investor"
    elif is_rental:
        lead_type = "renter"
    elif is_pure_smalltalk:
        lead_type = "other"
    else:
        lead_type = "buyer"

    # ----------------------------------------------------
    # 3. High Intent Detection
    # ----------------------------------------------------
    # Explicit visit, budget with buying timeframe, or immediate booking/finalizing
    site_visit_patterns = [
        r"\bvisit\b", r"\bsite visit\b", r"\bkal subah\b", r"\btomorrow\b", r"\bvisit karni hai\b",
        r"\bvisit schedule\b", r"\bvisit timing\b", r"\bready with\b", r"\bbudget of\b",
        r"\bmera budget\b", r"\bnext month\b", r"\b15 دنوں\b", r"\baglay hafte\b",
        r"\bconstruct\b", r"\bghar banane\b", r"سائٹ وزٹ", r"وزٹ کرنا", r"خریدنا چاہتا ہوں", r"بجٹ"
    ]
    has_site_visit = any(re.search(p, text_lower) for p in site_visit_patterns)

    # Exclude pure ambiguous questions like 'Site visit timing?' or 'Visit schedule?'
    short_inquiry = bool(re.search(r"^(site visit timing\??|visit schedule\??)$", text_lower))

    high_intent = False
    if is_booking:
        high_intent = True
    elif has_site_visit and not short_inquiry:
        high_intent = True

    return {
        "lead_type": lead_type,
        "high_intent": high_intent,
        "needs_human": needs_human,
    }
