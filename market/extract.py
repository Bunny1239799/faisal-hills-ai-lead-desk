import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

BLOCKS_FILE = Path(__file__).resolve().parent / "blocks.json"


def _load_block_definitions() -> List[Dict[str, Any]]:
    if not BLOCKS_FILE.exists():
        return []
    with open(BLOCKS_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("blocks", [])


BLOCK_DEFINITIONS = _load_block_definitions()


@dataclass
class ExtractedEntity:
    size_marla: Optional[float] = None
    block_code: Optional[str] = None
    block_name: Optional[str] = None
    side: Optional[str] = None  # "BUY" | "SELL" | "INQUIRY"
    price_pkr: Optional[int] = None
    price_raw: Optional[str] = None
    category: Optional[str] = None  # "residential" | "commercial"
    is_corner: bool = False
    is_boulevard: bool = False
    is_park_facing: bool = False
    attributes: List[str] = field(default_factory=list)


# Urdu digit mapping
URDU_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")


def normalize_urdu_digits(text: str) -> str:
    return text.translate(URDU_DIGITS)


def extract_size_marla(text: str) -> Optional[float]:
    """
    Extracts plot size normalized to Marla (1 Kanal = 20 Marla).
    Handles English, Roman Urdu, and Urdu script.
    """
    clean_text = normalize_urdu_digits(text.lower())

    # Kanal matching: e.g., "1 kanal", "2 kanals", "1 کنال", "ایک کنال"
    kanal_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:kanal|kanals|کنال)", clean_text)
    if kanal_match:
        return float(kanal_match.group(1)) * 20.0

    if re.search(r"\b(one|aik|ek)\s+kanal\b", clean_text) or "ایک کنال" in clean_text:
        return 20.0

    # Marla matching: e.g., "5 marla", "10m", "5 مرلہ", "7 marlay", "8 marle"
    marla_match = re.search(
        r"(\d+(?:\.\d+)?)\s*(?:marla|marlas|marle|marlay|marley|m\b|مرلہ|مرلے)", clean_text
    )
    if marla_match:
        return float(marla_match.group(1))

    # Common word numerals in Urdu / Roman Urdu for size
    word_sizes = [
        (r"\b(paanch|panch|five)\s*(?:marla|m)\b|پانچ مرلہ", 5.0),
        (r"\b(das|dus|ten)\s*(?:marla|m)\b|دس مرلہ", 10.0),
        (r"\b(saat|seven)\s*(?:marla|m)\b|سات مرلہ", 7.0),
        (r"\b(aath|eight)\s*(?:marla|m)\b|آٹھ مرلہ", 8.0),
    ]
    for pattern, val in word_sizes:
        if re.search(pattern, clean_text):
            return val

    return None


def extract_block(text: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Identifies block using canonical definitions and aliases in blocks.json.
    """
    clean_text = text.lower()

    for b in BLOCK_DEFINITIONS:
        for alias in b.get("aliases", []):
            pattern = r"(?<!\w)" + re.escape(alias.lower()) + r"(?!\w)"
            if re.search(pattern, clean_text):
                return b["code"], b["canonical_name"]

    return None, None


def extract_price_pkr(text: str) -> Tuple[Optional[int], Optional[str]]:
    """
    Parses prices in Lac / Lakh, Crore, Thousand / Hazar, or plain numbers with K / M.
    Returns (price_in_pkr, raw_matched_string).
    """
    clean_text = normalize_urdu_digits(text.lower())

    # 1. Crore matching (e.g., "1.25 crore", "2 cr", "1 کروڑ")
    cr_match = re.search(
        r"(\d+(?:\.\d+)?)\s*(?:crore|crores|cr|کروڑ)", clean_text
    )
    if cr_match:
        val = float(cr_match.group(1))
        return int(round(val * 10_000_000)), cr_match.group(0).strip()

    # 2. Lac / Lakh matching (e.g., "45 lac", "50.5 lacs", "60 lakh", "45 لاکھ", "45 lac tak")
    lac_match = re.search(
        r"(\d+(?:\.\d+)?)\s*(?:lacs|lac|lakh|lakhs|لاکھ|لاک)", clean_text
    )
    if lac_match:
        val = float(lac_match.group(1))
        return int(round(val * 100_000)), lac_match.group(0).strip()

    # 3. K format (e.g. 500k, 800 k)
    k_match = re.search(r"(\d+(?:\.\d+)?)\s*k\b", clean_text)
    if k_match:
        val = float(k_match.group(1))
        return int(round(val * 1_000)), k_match.group(0).strip()

    # 4. Raw digits over 100,000 (e.g. 4500000)
    raw_num_match = re.search(r"\b(\d{6,9})\b", clean_text)
    if raw_num_match:
        val = int(raw_num_match.group(1))
        return val, raw_num_match.group(0).strip()

    return None, None


def extract_side(text: str) -> str:
    """
    Determines market side:
    - BUY: buyer looking for inventory (demand)
    - SELL: seller / agent offering inventory (supply)
    - INQUIRY: general question or inquiry
    """
    clean_text = text.lower()

    # SELL / OFFER keywords
    sell_patterns = [
        r"\bavailable\b", r"\bfor sale\b", r"\bfor sell\b", r"\bdirect owner\b",
        r"\bready for transfer\b", r"\bhot deal\b", r"\bprime location available\b",
        r"\bdemand\b", r"\boffer\b", r"\bplot for sale\b", r"\bselling\b",
        r"\bfor sale\b", r"\bavailable hai\b", r"\bmauke par dastiyab\b",
        r"برائے فروخت", r"دستیاب", r"سیل کے لیے", r"ڈیمانڈ"
    ]

    # BUY / REQUIREMENT keywords
    buy_patterns = [
        r"\brequired\b", r"\blooking for\b", r"\bneed\b", r"\bwant\b",
        r"\bbuy\b", r"\bbuying\b", r"\binterested to buy\b", r"\bchahiye\b",
        r"\bchahye\b", r"\bkharidna\b", r"\bkharidni\b", r"\blena chahta\b",
        r"\bleni hai\b", r"\blena hai\b", r"\bbudget\b",
        r"درکار", r"چاہیے", r"خریدنا", r"لینا ہے", r"بجٹ"
    ]

    is_sell = any(re.search(p, clean_text) for p in sell_patterns)
    is_buy = any(re.search(p, clean_text) for p in buy_patterns)

    if is_sell and not is_buy:
        return "SELL"
    if is_buy and not is_sell:
        return "BUY"

    # Nuanced priority when both or neither occur
    if "demand" in clean_text or "final" in clean_text or "available" in clean_text:
        return "SELL"
    if "chahiye" in clean_text or "required" in clean_text or "need" in clean_text or "lena hai" in clean_text:
        return "BUY"

    return "INQUIRY"


def extract_attributes_and_category(text: str) -> Tuple[Optional[str], bool, bool, bool, List[str]]:
    """
    Extracts plot category (residential vs commercial) and attributes (corner, boulevard, park facing).
    """
    clean_text = text.lower()
    attrs: List[str] = []

    # Category
    category = None
    if re.search(r"\bcommercial\b|\bcomm\b|کمرشل", clean_text):
        category = "commercial"
        attrs.append("commercial")
    elif re.search(r"\bresidential\b|\bres\b|رہائشی", clean_text):
        category = "residential"
        attrs.append("residential")

    # Corner
    is_corner = bool(re.search(r"\bcorner\b|کارنر|کونا", clean_text))
    if is_corner:
        attrs.append("corner")

    # Boulevard / Main Road
    is_boulevard = bool(
        re.search(r"\bboulevard\b|\bmain road\b|\bmb\b|\bmain blvd\b|مین روڈ|بلیوارڈ", clean_text)
    )
    if is_boulevard:
        attrs.append("boulevard")

    # Park Facing
    is_park_facing = bool(re.search(r"\bpark facing\b|\bpark face\b|پارک فیسنگ|پارک فیس", clean_text))
    if is_park_facing:
        attrs.append("park_facing")

    return category, is_corner, is_boulevard, is_park_facing, attrs


def extract_market_entities(text: str) -> ExtractedEntity:
    """
    Main extraction function for customer messages and market chat posts.
    """
    size_marla = extract_size_marla(text)
    block_code, block_name = extract_block(text)
    price_pkr, price_raw = extract_price_pkr(text)
    side = extract_side(text)
    category, is_corner, is_boulevard, is_park_facing, attrs = extract_attributes_and_category(text)

    return ExtractedEntity(
        size_marla=size_marla,
        block_code=block_code,
        block_name=block_name,
        side=side,
        price_pkr=price_pkr,
        price_raw=price_raw,
        category=category,
        is_corner=is_corner,
        is_boulevard=is_boulevard,
        is_park_facing=is_park_facing,
        attributes=attrs,
    )
