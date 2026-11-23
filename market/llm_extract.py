import json
import os
import urllib.error
import urllib.request
from typing import Any, Dict, Optional

from market.anonymize import scrub_pii
from market.extract import ExtractedEntity, extract_market_entities

# LLM Extraction is OFF by default for privacy and cost control
DEFAULT_ENABLE_LLM = False
OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL = "google/gemini-2.5-flash-lite"


def is_llm_extract_enabled() -> bool:
    """Checks whether LLM extraction fallback is explicitly enabled via environment variable."""
    val = os.getenv("ENABLE_LLM_MARKET_EXTRACT", "").strip().lower()
    return val in ("1", "true", "yes", "on")


EXTRACTION_PROMPT = """You are a real estate entity extractor for Faisal Hills Islamabad/Taxila.
Extract structured details from the customer or dealer message below.
Return ONLY valid JSON matching this schema:
{
  "size_marla": number or null (e.g., 5, 10, 20 for 1 kanal),
  "block_code": "A" | "B" | "C" | "EXEC" | null,
  "side": "BUY" | "SELL" | "INQUIRY",
  "price_pkr": integer or null (e.g. 4500000),
  "category": "residential" | "commercial" | null,
  "plot_no": string or null,
  "is_corner": boolean,
  "is_boulevard": boolean,
  "is_park_facing": boolean
}

Rules:
1. Only return the JSON object, nothing else.
2. If uncertain about a field, set it to null or false.
3. 1 Kanal = 20 Marla. 1 Lac = 100000 PKR. 1 Crore = 10000000 PKR.

Message:
"{message}"
"""


def extract_with_llm(scrubbed_text: str, api_key: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """
    Sends strictly scrubbed text to the LLM for entity extraction.
    Returns dictionary with extracted fields or None on error.
    """
    if not api_key:
        api_key = os.getenv("OPENROUTER_API_KEY")

    if not api_key:
        return None

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/faisal-hills-ai",
        "X-Title": "Faisal Hills Market Desk",
    }

    payload = {
        "model": os.getenv("MARKET_LLM_MODEL", DEFAULT_MODEL),
        "messages": [
            {
                "role": "user",
                "content": EXTRACTION_PROMPT.format(message=scrubbed_text),
            }
        ],
        "temperature": 0.0,
    }

    try:
        req = urllib.request.Request(
            OPENROUTER_API_URL,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            content = data["choices"][0]["message"]["content"].strip()

            # Clean JSON markdown fences if present
            if content.startswith("```"):
                lines = content.splitlines()
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].startswith("```"):
                    lines = lines[:-1]
                content = "\n".join(lines).strip()

            return json.loads(content)
    except Exception:
        return None


def extract_entities_with_fallback(text: str, api_key: Optional[str] = None) -> ExtractedEntity:
    """
    First runs fast deterministic rule extraction.
    If LLM extract is enabled and critical entities (size or block) are missing,
    scrubs PII and calls LLM fallback to refine the extraction.
    """
    entity = extract_market_entities(text)

    # If already fully parsed or LLM extraction is turned off, return rule result
    if not is_llm_extract_enabled():
        return entity

    # If critical fields like block or size are missing, attempt fallback on scrubbed text only
    if entity.block_code is None or entity.size_marla is None:
        safe_text = scrub_pii(text)
        llm_data = extract_with_llm(safe_text, api_key=api_key)

        if llm_data:
            if entity.size_marla is None and llm_data.get("size_marla"):
                try:
                    entity.size_marla = float(llm_data["size_marla"])
                except (ValueError, TypeError):
                    pass

            if entity.block_code is None and llm_data.get("block_code"):
                code = str(llm_data["block_code"]).upper().strip()
                if code in ("A", "B", "C", "EXEC"):
                    entity.block_code = code
                    name_map = {"A": "Block A", "B": "Block B", "C": "Block C", "EXEC": "Executive Block"}
                    entity.block_name = name_map.get(code)

            if entity.price_pkr is None and llm_data.get("price_pkr"):
                try:
                    entity.price_pkr = int(llm_data["price_pkr"])
                except (ValueError, TypeError):
                    pass

            if entity.side in (None, "INQUIRY") and llm_data.get("side"):
                side = str(llm_data["side"]).upper().strip()
                if side in ("BUY", "SELL", "INQUIRY"):
                    entity.side = side

    return entity
