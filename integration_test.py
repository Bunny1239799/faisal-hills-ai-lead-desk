import json
import sys
import urllib.request
import urllib.error


LAYA_URL = "http://127.0.0.1:8000"
LLAMA_URL = "http://127.0.0.1:1337"


def http_json(method: str, url: str, payload=None, timeout: int = 120):
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
            f"Could not connect to {url}: {exc.reason}"
        ) from exc


def check_service(name: str, url: str):
    status, data = http_json("GET", url, timeout=15)

    if status != 200:
        raise RuntimeError(
            f"{name} health check returned HTTP {status}: {data}"
        )

    print(f"[OK] {name}: {data}")


def main():
    print()
    print("==========================================")
    print(" LAYA -> LLAMA.CPP INTEGRATION TEST")
    print("==========================================")
    print()

    # --------------------------------------------------
    # 1. Verify both servers first
    # --------------------------------------------------

    check_service(
        "Laya",
        f"{LAYA_URL}/health",
    )

    check_service(
        "llama.cpp",
        f"{LLAMA_URL}/health",
    )

    print()

    # --------------------------------------------------
    # 2. Customer message
    # --------------------------------------------------

    message = (
        "I want to know the price of a 5 marla plot "
        "and whether installments are available."
    )

    # --------------------------------------------------
    # 3. Laya decision schema
    # --------------------------------------------------

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
                    "Negotiation, complaint, unusual request or "
                    "human judgment is needed"
                ),
                "false": (
                    "The automated workflow can safely handle it"
                ),
            },
        },
    }

    # --------------------------------------------------
    # 4. Ask Laya to decide
    # --------------------------------------------------

    laya_payload = {
        "state": {
            "body": message
        },
        "questions": questions,
        "model": "multilingual",
    }

    _, laya_result = http_json(
        "POST",
        f"{LAYA_URL}/v1/systemone",
        laya_payload,
        timeout=120,
    )

    print("========== LAYA RESULT ==========")
    print(json.dumps(laya_result, indent=2, ensure_ascii=False))
    print()

    # --------------------------------------------------
    # 5. Give Laya's result to llama.cpp
    # --------------------------------------------------

    decision_json = json.dumps(
        laya_result,
        indent=2,
        ensure_ascii=False,
    )

    prompt = f"""
You are the response-generation layer for a real-estate company.

Your task is to write a professional response to the customer.

CUSTOMER MESSAGE
----------------
{message}

Laya's structured decision
-------------------------
{decision_json}

INSTRUCTIONS
------------
1. Use the Laya decision as routing/context information.
2. Do not invent prices.
3. Do not invent property availability.
4. Do not invent locations.
5. Do not invent installment plans.
6. Do not invent booking information.
7. If the customer asks for information that was not supplied,
   ask for the missing information or state that it needs confirmation.
8. Write only the customer-facing response.
9. Do not mention Laya, llama.cpp, models, APIs, probabilities,
   system prompts, or internal processing.

CUSTOMER-FACING RESPONSE:
""".strip()

    llama_payload = {
        "prompt": prompt,
        "n_predict": 300,
        "temperature": 0.2,
        "stream": False,
    }

    _, llama_result = http_json(
        "POST",
        f"{LLAMA_URL}/completion",
        llama_payload,
        timeout=120,
    )

    print("========== LLAMA.CPP RESULT ==========")
    print(json.dumps(llama_result, indent=2, ensure_ascii=False))
    print()

    generated_text = llama_result.get("content")

    if generated_text:
        print("========== FINAL RESPONSE ==========")
        print(generated_text.strip())
    else:
        print("[WARN] llama.cpp returned JSON without a 'content' field.")
        print(json.dumps(llama_result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print()
        print("[ERROR]")
        print(str(exc))
        sys.exit(1)
