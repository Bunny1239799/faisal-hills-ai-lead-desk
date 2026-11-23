import json
import os
import re
import time
import urllib.request
import urllib.error
from pathlib import Path
from typing import List, Dict, Any, Optional

CACHE_PATH = Path("evaluation/cache/llm_cache.json")
GEMINI_MODEL = "gemini-3.5-flash-lite"
MAX_RETRIES = 5
BASE_BACKOFF_SECONDS = 2
BATCH_SIZE = 10


def scrub_pii(text: str) -> str:
    """Scrubs phone numbers and email addresses from text."""
    # Email regex
    text = re.sub(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", "[EMAIL]", text)
    # Phone regex (supports international, local 03xx, hyphenated)
    text = re.sub(r"(\+?92\s*|0)?3[0-9]{2}[\s-]?[0-9]{7}", "[PHONE]", text)
    text = re.sub(r"\b\d{3}[-.\s]?\d{3}[-.\s]?\d{4}\b", "[PHONE]", text)
    return text


def load_cache() -> Dict[str, Dict[str, Any]]:
    if CACHE_PATH.exists():
        try:
            with open(CACHE_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_cache(cache: Dict[str, Dict[str, Any]]) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=2, ensure_ascii=False)


def call_gemini_api(prompt: str, api_key: str) -> str:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={api_key}"
    payload = {
        "contents": [
            {
                "parts": [
                    {"text": prompt}
                ]
            }
        ],
        "generationConfig": {
            "responseMimeType": "application/json",
            "temperature": 0.0
        }
    }
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    for attempt in range(MAX_RETRIES):
        request = urllib.request.Request(
            url=url,
            data=data,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                raw = response.read().decode("utf-8")
                res_json = json.loads(raw)
                text = res_json["candidates"][0]["content"]["parts"][0]["text"]
                return text
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                sleep_time = BASE_BACKOFF_SECONDS * (2 ** attempt)
                print(f"[LLM] Rate limit hit (429). Retrying in {sleep_time}s... (attempt {attempt + 1}/{MAX_RETRIES})")
                time.sleep(sleep_time)
            else:
                raw_err = exc.read().decode("utf-8", errors="replace")
                raise RuntimeError(f"Gemini API HTTP {exc.code}: {raw_err}") from exc
        except urllib.error.URLError as exc:
            sleep_time = BASE_BACKOFF_SECONDS * (2 ** attempt)
            print(f"[LLM] Connection error: {exc.reason}. Retrying in {sleep_time}s...")
            time.sleep(sleep_time)

    raise RuntimeError(f"Gemini API request failed after {MAX_RETRIES} attempts.")


def build_batch_prompt(batch: List[Dict[str, Any]]) -> str:
    items = []
    for item in batch:
        items.append({
            "id": item["id"],
            "message": scrub_pii(item["message"])
        })
    items_json = json.dumps(items, ensure_ascii=False, indent=2)

    prompt = f"""You are a real-estate message classifier for Faisal Hills.
Classify each message in the provided JSON array into three fields:
1. `lead_type`: Must be one of ["buyer", "investor", "renter", "broker", "existing_customer", "other"].
   - "buyer": Asks to purchase a plot, prices, payment plans, site visit, or general society details.
   - "investor": Asks about capital gain, profit, guaranteed return, ROI, rental yield, or bulk investing.
   - "renter": Inquires about renting properties, shops, or offices.
   - "broker": Property dealers asking for commission split, referral agreements, or dealer inventory.
   - "existing_customer": Has already purchased/booked, complaining about delays, refund, possession, or registry.
   - "other": General greeting, smalltalk, or unrelated.
2. `high_intent`: Boolean (true/false).
   - true: Explicit booking, token payment, scheduled site visit date/time, ready funds/budget with buying timeline.
   - false: General information, curiosity, greetings, or unclear timeline.
3. `needs_human`: Boolean (true/false).
   - true: Requires human judgment: legal/NOC/dispute/RDA inquiries, price discount/bargaining, direct booking/token transfer, complaints, refund requests, guaranteed return questions, or broker commission deals.
   - false: Automated factual queries (pricing, location, map, amenities, installment schedule) or smalltalk.

Input Messages:
{items_json}

Return ONLY a valid JSON array of objects with keys: "id", "lead_type", "high_intent", "needs_human".
"""
    return prompt


def classify_batch_llm(records: List[Dict[str, Any]], api_key: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Classifies a list of dataset records using Gemini API in batches of 10.
    Utilizes local cache to avoid duplicate API requests.
    """
    if not api_key:
        api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise ValueError("GEMINI_API_KEY environment variable is not set.")

    cache = load_cache()
    results: List[Dict[str, Any]] = [None] * len(records)
    pending_indices: List[int] = []

    for idx, rec in enumerate(records):
        rec_id = str(rec["id"])
        if rec_id in cache:
            cached_item = cache[rec_id]
            results[idx] = {
                "id": rec_id,
                "lead_type": cached_item.get("lead_type", "buyer"),
                "high_intent": bool(cached_item.get("high_intent", False)),
                "needs_human": bool(cached_item.get("needs_human", False)),
            }
        else:
            pending_indices.append(idx)

    # Process pending in batches of BATCH_SIZE
    for i in range(0, len(pending_indices), BATCH_SIZE):
        batch_idxs = pending_indices[i : i + BATCH_SIZE]
        batch_records = [records[b_idx] for b_idx in batch_idxs]

        prompt = build_batch_prompt(batch_records)
        raw_response = call_gemini_api(prompt, api_key)

        try:
            parsed_list = json.loads(raw_response)
            parsed_dict = {str(item["id"]): item for item in parsed_list if "id" in item}
        except Exception as e:
            # Fallback if json parsing fails
            parsed_dict = {}
            print(f"[LLM] Error parsing batch JSON response: {e}")

        for b_idx in batch_idxs:
            rec = records[b_idx]
            rec_id = str(rec["id"])
            item_res = parsed_dict.get(rec_id, {})
            classification = {
                "id": rec_id,
                "lead_type": item_res.get("lead_type", "buyer"),
                "high_intent": bool(item_res.get("high_intent", False)),
                "needs_human": bool(item_res.get("needs_human", False)),
            }
            results[b_idx] = classification
            cache[rec_id] = classification

        save_cache(cache)
        # Gentle pacing between batch requests
        time.sleep(1.0)

    return results
