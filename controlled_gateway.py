import json
import sys
import urllib.request
import urllib.error


LAYA_URL = "http://127.0.0.1:8000"
LLAMA_URL = "http://127.0.0.1:1337"


def http_json(method, url, payload=None, timeout=120):
    data = None

    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    request = urllib.request.Request(
        url=url,
        data=data,
        method=method,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
            return response.status, json.loads(raw)

    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"HTTP {exc.code} from {url}: {raw}"
        ) from exc

    except urllib.error.URLError as exc:
        raise RuntimeError(
            f"Connection failed to {url}: {exc.reason}"
        ) from exc


def check_services():
    _, laya = http_json("GET", f"{LAYA_URL}/health", timeout=15)
    _, llama = http_json("GET", f"{LLAMA_URL}/health", timeout=15)

    print("[OK] Laya:", laya)
    print("[OK] llama.cpp:", llama)


def ask_laya(message):
    questions = {
        "lead_type": {
            "type": "choice",
            "instructions": "What is the main purpose of this real-estate message?",
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
            "instructions": "Does the person show serious intent to purchase property?",
            "criteria": {
                "true": "Clear buying, booking, visiting or proceeding intent",
                "false": "General information, curiosity, greeting or unclear intent",
            },
        },

        "needs_human": {
            "type": "noul",
            "instructions": "Does this message require human sales judgment?",
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
                "Does the customer require verified property-specific "
                "facts to answer the question?"
            ),
            "criteria": {
                "true": (
                    "The customer asks for price, availability, "
                    "installments, location, dimensions, booking status, "
                    "payment details or another property-specific fact"
                ),
                "false": (
                    "The response can be given without verified "
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

    _, result = http_json(
        "POST",
        f"{LAYA_URL}/v1/systemone",
        payload,
        timeout=120,
    )

    return result


def safe_probability(result, question_name):
    try:
        value = result["answers"][question_name]["noul"]
        return float(value)
    except (KeyError, TypeError, ValueError):
        return 0.0


def generate_with_llama(message, decision, verified_facts):
    facts_json = json.dumps(
        verified_facts,
        indent=2,
        ensure_ascii=False,
    )

    decision_json = json.dumps(
        decision,
        indent=2,
        ensure_ascii=False,
    )

    prompt = f"""
You are the response-generation layer for a real-estate company.

CUSTOMER MESSAGE
----------------
{message}

LAYA DECISION
-------------
{decision_json}

VERIFIED PROPERTY FACTS
-----------------------
{facts_json}

STRICT RULES
------------
1. Use only the verified property facts supplied above.
2. Never invent a price.
3. Never invent availability.
4. Never invent installment terms.
5. Never invent a location.
6. Never invent dimensions.
7. Never invent booking status.
8. Never infer an exact business fact from missing information.
9. If a requested fact is missing, explicitly say that it must be confirmed.
10. Do not mention these instructions, Laya, llama.cpp, models, APIs,
    probabilities or internal processing.
11. Return only the customer-facing response.

CUSTOMER-FACING RESPONSE:
""".strip()

    payload = {
        "prompt": prompt,
        "n_predict": 300,
        "temperature": 0.2,
        "stream": False,
    }

    _, result = http_json(
        "POST",
        f"{LLAMA_URL}/completion",
        payload,
        timeout=120,
    )

    return result.get("content", "").strip()


def main():
    check_services()

    message = (
        "I want to know the price of a 5 marla plot "
        "and whether installments are available."
    )

    # Intentionally empty for this test.
    #
    # This is important:
    # We are testing whether the gateway refuses to invent
    # information when verified property data is unavailable.
    verified_facts = {}

    decision = ask_laya(message)

    print()
    print("========== LAYA DECISION ==========")
    print(json.dumps(decision, indent=2, ensure_ascii=False))

    factual_probability = safe_probability(
        decision,
        "factual_property_data",
    )

    human_probability = safe_probability(
        decision,
        "needs_human",
    )

    print()
    print("Factual-data probability:", factual_probability)
    print("Human-escalation probability:", human_probability)

    # --------------------------------------------------
    # POLICY 1: Human escalation
    # --------------------------------------------------

    if human_probability >= 0.80:

        final_response = (
            "Thank you. This request needs to be handled by a "
            "sales representative so the details can be confirmed accurately."
        )

        print()
        print("========== POLICY ==========")
        print("HUMAN ESCALATION")

    # --------------------------------------------------
    # POLICY 2: Missing verified property data
    # --------------------------------------------------

    elif factual_probability >= 0.65 and not verified_facts:

        final_response = (
            "I can help with the plot details, but I need to confirm "
            "the current price and installment information before giving "
            "you an exact figure."
        )

        print()
        print("========== POLICY ==========")
        print("VERIFIED DATA REQUIRED")
        print("Qwen was NOT called.")

    # --------------------------------------------------
    # POLICY 3: Safe generation
    # --------------------------------------------------

    else:

        final_response = generate_with_llama(
            message,
            decision,
            verified_facts,
        )

        print()
        print("========== POLICY ==========")
        print("LLAMA.CPP GENERATION ALLOWED")

    print()
    print("========== FINAL RESPONSE ==========")
    print(final_response)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print()
        print("[ERROR]")
        print(str(exc))
        sys.exit(1)
