"""Extra stricter-only guard patterns for the policy gate (English, Roman Urdu, Urdu)."""
import re

_F = re.IGNORECASE | re.DOTALL

_PATTERNS = [
    # English: asking the assistant to invent facts
    (r"\b(invent|make[\s-]?up|made[\s-]?up|fabricat\w*|fake)\b.{0,60}\b(price|prices|rate|rates|cost|value|figure|number|availability|plan|plans|plot|plots|discount|details?)\b", "invent_fact"),
    (r"\b(price|prices|rate|rates|cost|figure|number|availability|plan)\b.{0,40}\b(invent|make[\s-]?up|made[\s-]?up|fabricat\w*|fake)\b", "invent_fact"),
    (r"\bjust\s+(invent|estimate|guess|assume|make\s+up|make\s+it\s+up)\b", "invent_fact"),
    (r"\b(any|some|a)\s+(random|made[\s-]?up|fake|imaginary)\s+(price|rate|number|figure)\b", "invent_fact"),
    # English: pressure to skip data or checks
    (r"\b(skip|ignore|bypass|forget|without)\b.{0,25}\b(database|data\s?base|facts|records|verification|verifying|checking|checks|rules|sources)\b", "skip_checks"),
    (r"\b(do\s+not|don'?t|dont|no\s+need\s+(to|for)|need\s+not)\b.{0,40}\b(database|data\s?base|facts|records|verification|verify|checks|rules|sources)\b", "skip_checks"),
    # Roman Urdu
    (r"\b(farzi|jhoot\w*|jhoota)\b", "invent_fact_ru"),
    (r"\bapni\s+(taraf|marzi)\s+se\b", "invent_fact_ru"),
    (r"\b(price|rate|qeemat|keemat|qimat)\b.{0,30}\bbana\w*\b", "invent_fact_ru"),
    (r"\bbana\w*\b.{0,30}\b(price|rate|qeemat|keemat|qimat)\b", "invent_fact_ru"),
    (r"\b(database|data|facts?)\s+(ki|ka)\s+zar\w*rat\s+nahi", "skip_checks_ru"),
    (r"\bzar\w*rat\s+nahi\w*\b.{0,30}\b(database|facts?|data)\b", "skip_checks_ru"),
    (r"\bbina\s+(check|verify|confirm|database|tasdeeq|tasdiq)\b", "skip_checks_ru"),
    (r"\b(check|verify|confirm)\s+(na|mat)\s+(karo|karen|kro|kijiye)\b", "skip_checks_ru"),
    # Urdu script
    (r"(\u0641\u0631\u0636\u06CC|\u062C\u06BE\u0648\u0679)", "invent_fact_ur"),
    (r"\u0627\u067E\u0646\u06CC\s+(\u0637\u0631\u0641|\u0645\u0631\u0636\u06CC)\s+\u0633\u06D2", "invent_fact_ur"),
    (r"(\u0642\u06CC\u0645\u062A|\u0631\u06CC\u0679).{0,25}\u0628\u0646\u0627", "invent_fact_ur"),
    (r"\u0628\u0646\u0627\s+(\u062F\u0648|\u062F\u06CC\u06BA|\u06A9\u0631).{0,25}(\u0642\u06CC\u0645\u062A|\u0631\u06CC\u0679)", "invent_fact_ur"),
    (r"\u0688\u06CC\u0679\u0627\s*\u0628\u06CC\u0633.{0,20}\u0636\u0631\u0648\u0631\u062A\s+\u0646\u06C1\u06CC\u06BA", "skip_checks_ur"),
    (r"\u0636\u0631\u0648\u0631\u062A\s+\u0646\u06C1\u06CC\u06BA.{0,20}\u0688\u06CC\u0679\u0627\s*\u0628\u06CC\u0633", "skip_checks_ur"),
    (r"\u0628\u063A\u06CC\u0631\s+(\u0686\u06CC\u06A9|\u062A\u0635\u062F\u06CC\u0642)", "skip_checks_ur"),
    # --- new patterns (TASK_12: Step 12 Matrix) ---
    # Availability
    (r"\b(do\s+you\s+have|is\s+it\s+available|any\s+plot\s+available|available\s+hai|mojood|koi\s+plot\s+available|do\s+you\s+have\b.*\bavailable|available\s+plot)\b", "availability"),
    # Abusive language
    (r"\b(useless|stupid|idiot|bakwas|bewakoof)\b", "abuse"),
    # Quote confirmation / Pressure ("you said", "you told me")
    (r"\b(you\s+(said|told\s+me|quoted)|aap\s+ne\s+kaha\s+tha|yesterday|last\s+week)\b.*\b(price|confirm|confirming)\b", "stale_quote"),
    # Payment / Installments
    (r"\b(installments?|payment\s+plans?|down\s+payments?|advances?|tokens?|bookings?|emi|kists?)\b", "payment_protected"),
    # Privacy / Contact details
    (r"\b(number\s+of\s+another\s+customer|send\s+me\s+his\s+phone\s+number|who\s+else\s+asked)\b", "privacy"),
    # Injection/System prompt
    (r"\b(ignore\s+previous\s+instructions|reveal\s+your\s+system\s+prompt|you\s+are\s+now|developer\s+mode)\b", "injection"),
    # Urdu/Roman Urdu Abusive
    (r"\b(bakwas|bewakoof)\b", "abuse_ru"),
]

_RULES = [(re.compile(p, _F), tag) for p, tag in _PATTERNS]


def _norm(text):
    t = str(text)
    t = t.replace("\u064A", "\u06CC").replace("\u0643", "\u06A9").replace("\u0649", "\u06CC")
    t = t.replace("\u2019", "'")
    t = re.sub(r"[\u200b\u200c\u200d\u200e\u200f\ufeff]", "", t)
    return re.sub(r"\s+", " ", t).strip()


def extra_risk(message):
    """Return a sorted list of risk tags found in the message (empty if none)."""
    text = _norm(message)
    return sorted({tag for rx, tag in _RULES if rx.search(text)})

# --- additional stricter-only patterns: guess/estimate wording ---
_PATTERNS.extend([
    # Roman Urdu: guess/estimate-based prices
    (r"\bandaz\w*\b.{0,60}\b(price|rate|rates|qeemat|keemat|qimat|bhao|bhaao|cost)\b", "invent_fact_ru"),
    (r"\b(price|rate|rates|qeemat|keemat|qimat|bhao|bhaao|cost)\b.{0,60}\bandaz\w*\b", "invent_fact_ru"),
    (r"\bkoi\s+bhi\b.{0,30}\b(price|rate|qeemat|keemat|qimat|bhao|bhaao)\b", "invent_fact_ru"),
    (r"\b(tukka|tukke|tukay)\b", "invent_fact_ru"),
    (r"\b(db|database|data\s?base|data|record)\b.{0,30}\bnahi\b.{0,60}\b(bata|batao|batana|de\s?do|dedo)\b", "invent_fact_ru"),
    # English: "if it is not in the database, guess/tell me anyway"
    (r"\b(if|when)\b.{0,40}\b(not\s+in|isn'?t\s+in|missing\s+from|no)\b.{0,20}\b(database|db|data|records?)\b.{0,60}\b(guess|estimate|any|make\s+up|invent|tell)\b", "invent_fact"),
    # Urdu script
    (r"\u0627\u0646\u062F\u0627\u0632\w*.{0,60}(\u0642\u06CC\u0645\u062A|\u0631\u06CC\u0679|\u0628\u06BE\u0627\u0624|\u0631\u0642\u0645)", "invent_fact_ur"),
    (r"(\u0642\u06CC\u0645\u062A|\u0631\u06CC\u0679|\u0628\u06BE\u0627\u0624|\u0631\u0642\u0645).{0,60}\u0627\u0646\u062F\u0627\u0632\w*", "invent_fact_ur"),
    (r"\u062A\u062E\u0645\u06CC\u0646\w*.{0,60}(\u0642\u06CC\u0645\u062A|\u0631\u06CC\u0679|\u0628\u06BE\u0627\u0624|\u0631\u0642\u0645)", "invent_fact_ur"),
    (r"\u06A9\u0648\u0626\u06CC\s+\u0628\u06BE\u06CC.{0,30}(\u0642\u06CC\u0645\u062A|\u0631\u06CC\u0679|\u0628\u06BE\u0627\u0624)", "invent_fact_ur"),
    (r"(\u0688\u06CC\u0679\u0627\s*\u0628\u06CC\u0633|\u0688\u06CC\s*\u0628\u06CC).{0,30}\u0646\u06C1\u06CC\u06BA.{0,60}\u0628\u062A\u0627", "invent_fact_ur"),
])
_RULES[:] = [(re.compile(p, _F), t) for p, t in _PATTERNS]

# --- evade-fees patterns: secret transfers, tax and fee avoidance ---
_PATTERNS.extend([
    # English
    (r"\b(without|avoid|evade|dodge|skip|bypass|no)\b.{0,30}\b(tax|taxes|fee|fees|stamp\s*duty|duty|cvt|withholding|registration|transfer\s+charges)\b", "evade_fees"),
    (r"\b(secretly|quietly|under\s+the\s+table|off\s+the\s+record|off[\s-]?book\w*|benami|black\s+money|undeclared|unofficial(ly)?)\b", "evade_fees"),
    (r"\btransfer\b.{0,50}\b(secret\w*|quiet\w*|without\s+(any\s+)?(record|paperwork|documents|papers))\b", "evade_fees"),
    # Roman Urdu
    (r"\b(khufia|khufiya|chupke|chup\s*chap|chupkay|gupt)\b", "evade_fees_ru"),
    (r"\bbina\b.{0,30}\b(fee|fees|tax|taxes|duty|sarkari)\b", "evade_fees_ru"),
    (r"\b(tax|fee|fees|duty)\b.{0,25}\b(bacha\w*|se\s+bach\w*|chor\w*|na\s+(do|dena|dein))\b", "evade_fees_ru"),
    (r"\b(benami|kala\s+(dhan|paisa|paise))\b", "evade_fees_ru"),
    # Urdu script
    (r"\u062e\u0641\u06cc[\u06c1\u0647]", "evade_fees_ur"),
    (r"(\u0686\u067e\u06a9\u06d2|\u0686\u067e\s*\u0686\u0627\u067e)", "evade_fees_ur"),
    (r"\u0628\u063a\u06cc\u0631.{0,40}(\u0641\u06cc\u0633|\u0679\u06cc\u06a9\u0633|\u0688\u0648\u0679\u06cc|\u0633\u0631\u06a9\u0627\u0631\u06cc)", "evade_fees_ur"),
    (r"(\u0679\u06cc\u06a9\u0633|\u0641\u06cc\u0633).{0,25}(\u0686\u0648\u0631\u06cc|\u0628\u0686\u0627)", "evade_fees_ur"),
    (r"\u0628\u06d2\s*\u0646\u0627\u0645\u06cc", "evade_fees_ur"),
])
_RULES[:] = [(re.compile(p, _F), t) for p, t in _PATTERNS]