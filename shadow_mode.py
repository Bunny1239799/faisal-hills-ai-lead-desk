import json
import sys
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path


LAYA_URL = "http://127.0.0.1:8000"

LOG_DIR = Path(r"D:\AI-Projects\laya-gateway\logs")
LOG_FILE = LOG_DIR / "shadow_decisions.jsonl"


def call_laya(message: str):
    questions = {
        "lead_type": {
            "type": "choice",
            "instructions": (
                "What is the main purpose of this real-estate message?"
            ),
            "criteria": {
                "greeting": "Only greeting or casual introduction",
                "plot": "Asks about a plot",
                "apartment": "Asks about an apartment or flat",
                "house": "Asks about a house or villa",
                "commercial": "Asks about commercial property",
                "price": "Asks about price or payment",
                "availability": "Asks whether a property is available",
                "booking": "Asks about booking or reservation",
                "complaint": "Complaint or service problem",
                "other": "Anything else",
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
                    "Negotiation, complaint, unusual request, "
                    "or human judgment is needed"
                ),
                "false": (
                    "The automated workflow can safely handle it"
                ),
            },
        },

        "factual_property_data": {
            "type": "noul",
            "instructions": (
                "Does answering this message require verified "
                "property-specific information?"
            ),
            "criteria": {
                "true": (
                    "The customer asks for price, availability, "
                    "installments, location, dimensions, booking status, "
                    "payment details, or another property-specific fact"
                ),
                "false": (
                    "The message can be handled without verified "
                    "property-specific information"
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

    data = json.dumps(
        payload,
        ensure_ascii=False,
    ).encode("utf-8")

    request = urllib.request.Request(
        url=f"{LAYA_URL}/v1/systemone",
        data=data,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw)

    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"Laya HTTP {exc.code}: {raw}"
        ) from exc

    except urllib.error.URLError as exc:
        raise RuntimeError(
            f"Could not connect to Laya: {exc.reason}"
        ) from exc


def log_decision(message: str, decision: dict):
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    record = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "mode": "shadow",
        "message": message,
        "laya_decision": decision,

        # These remain blank until we manually evaluate examples.
        "human_expected_lead_type": None,
        "human_expected_high_intent": None,
        "human_expected_needs_human": None,

        # No downstream action is allowed in shadow mode.
        "action_taken": False,
        "qwen_called": False,
        "customer_reply_sent": False,
    }

    with LOG_FILE.open(
        "a",
        encoding="utf-8",
    ) as file:
        file.write(
            json.dumps(
                record,
                ensure_ascii=False,
            )
            + "\n"
        )


def process_message(message: str):
    print()
    print("=" * 60)
    print("MESSAGE")
    print("=" * 60)
    print(message)

    decision = call_laya(message)

    print()
    print("=" * 60)
    print("LAYA DECISION")
    print("=" * 60)
    print(
        json.dumps(
            decision,
            indent=2,
            ensure_ascii=False,
        )
    )

    log_decision(
        message,
        decision,
    )

    print()
    print("[SHADOW] Decision logged.")
    print("[SHADOW] No Qwen call.")
    print("[SHADOW] No customer action.")
    print()
    print(f"Log file: {LOG_FILE}")


def main():

    messages = [
        "Assalamualaikum",
        "I want to know the price of a 5 marla plot.",
        "Is a 10 marla plot available in this series?",
        "Can I book the plot on installments?",
        "I already paid and I need help with my booking."
    ]

    for message in messages:
        process_message(message)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print()
        print("[ERROR]")
        print(str(exc))
        sys.exit(1)
