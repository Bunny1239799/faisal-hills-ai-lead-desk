import json
import urllib.request
import urllib.error
from typing import Dict, Any, Optional

LAYA_DEFAULT_URL = "http://127.0.0.1:8000"


def call_laya_systemone(
    message: str,
    base_url: str = LAYA_DEFAULT_URL,
    timeout: int = 120,
) -> Dict[str, Any]:
    """
    Calls Laya POST /v1/systemone matching the exact schema from shadow_mode.py and integration_test.py.
    """
    questions = {
        "lead_type": {
            "type": "choice",
            "instructions": (
                "What is the main role or category of this person contacting a real estate company?"
            ),
            "criteria": {
                "buyer": "Wants to buy or asks plot price, payment plans, site visit",
                "investor": "Asks about profit, return, capital gain, guaranteed yield",
                "renter": "Asks about renting properties or rental shops",
                "broker": "Real estate agent asking about commission or dealer inventory",
                "existing_customer": "Existing customer with complaint, delayed possession or refund",
                "other": "Greeting, casual smalltalk or unrelated",
            },
        },
        "high_intent": {
            "type": "noul",
            "instructions": (
                "Does the person show serious intent to purchase property?"
            ),
            "criteria": {
                "true": (
                    "Clear buying, booking, visiting or proceeding intent"
                ),
                "false": (
                    "General information, curiosity, greeting or unclear intent"
                ),
            },
        },
        "needs_human": {
            "type": "noul",
            "instructions": (
                "Does this message require human sales judgment?"
            ),
            "criteria": {
                "true": (
                    "Negotiation, complaint, unusual request, legal/NOC, discount, booking or human judgment is needed"
                ),
                "false": (
                    "The automated workflow can safely handle it"
                ),
            },
        },
    }

    payload = {
        "state": {
            "body": message
        },
        "questions": questions,
        "model": "multilingual",
    }

    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url=f"{base_url}/v1/systemone",
        data=data,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw)
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Laya HTTP {exc.code}: {raw}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Could not connect to Laya at {base_url}: {exc.reason}") from exc


def classify_laya(
    message: str,
    base_url: str = LAYA_DEFAULT_URL,
    high_intent_threshold: float = 0.5,
    needs_human_threshold: float = 0.5,
) -> Dict[str, Any]:
    """
    Invokes Laya and formats outputs for lead_type, high_intent, and needs_human using provided thresholds.
    """
    response = call_laya_systemone(message, base_url=base_url)
    decisions = response.get("decisions", {})

    # 1. lead_type choice decision
    lead_type_decision = decisions.get("lead_type", {})
    lead_type = lead_type_decision.get("decision", "buyer")
    if lead_type not in {"buyer", "investor", "renter", "broker", "existing_customer", "other"}:
        lead_type = "buyer"

    # 2. high_intent noul decision
    high_intent_decision = decisions.get("high_intent", {})
    p_high_intent = high_intent_decision.get("probabilities", {}).get("true", 0.0)
    high_intent = bool(p_high_intent >= high_intent_threshold)

    # 3. needs_human noul decision
    needs_human_decision = decisions.get("needs_human", {})
    p_needs_human = needs_human_decision.get("probabilities", {}).get("true", 0.0)
    needs_human = bool(p_needs_human >= needs_human_threshold)

    return {
        "lead_type": lead_type,
        "high_intent": high_intent,
        "needs_human": needs_human,
        "raw_response": response,
    }
