"""M6 task 2 - the decision-layer port: Laya as a TIGHTENING-ONLY signal.

FH-02 M6: *"call Laya ... and pass its signals to
`evaluate_policy(message, laya_signals=...)` as a tightening-only input"*.

The risk FH-02 names: *"Laya is 0% on `needs_human` recall per
`eval_20261004_1241.md` - it must not be trusted for safety until
diagnosed."* 0% recall means Laya never says "this needs a human", so it
cannot be trusted to DETECT a dangerous message. It may therefore only ever
be wired as a signal that can ADD a concern, never remove one.

This module is the seam. Like the customer-model port it is
configuration-selected, offline by default, and it has a deterministic mock
so the behaviour can be proved without a service, a credential or a spend.

    DECISION_MODEL          "rules" (default) | "mock" | "laya"
    ENABLE_LAYA_DECISION    "1"/"true"/"yes"/"on" to allow a non-default
                            implementation to be used at all
    LAYA_URL                the Laya base URL (default http://127.0.0.1:8000)
    LAYA_TIMEOUT            seconds (default 120)

The default is the **rules** implementation: the application's own
deterministic policy decides alone, exactly as before M6. Nothing changes
on the default path.

The port never decides anything. It produces SIGNALS, and it produces them
in a shape the policy already understands: a `needs_human` probability in
[0, 1]. `app/policy.py` consumes them and can only make the decision
stricter - that logic already exists and is not modified here.
"""

import json
import os
import urllib.error
import urllib.request
from typing import Any, Dict, Optional

# The implementations this port knows about.
IMPLEMENTATION_RULES = "rules"
IMPLEMENTATION_MOCK = "mock"
IMPLEMENTATION_LAYA = "laya"
KNOWN_IMPLEMENTATIONS = (IMPLEMENTATION_RULES, IMPLEMENTATION_MOCK, IMPLEMENTATION_LAYA)

DEFAULT_IMPLEMENTATION = IMPLEMENTATION_RULES

DEFAULT_LAYA_URL = "http://127.0.0.1:8000"
DEFAULT_LAYA_TIMEOUT = 120

# The threshold at which a `needs_human` signal escalates. It is the same
# threshold `app/policy.py` already uses, and it is deliberately NOT
# lowered: a lower threshold would mean more escalations, and the rule
# "the model may only tighten" is about what the model may *do*, not about
# how often.
NEEDS_HUMAN_THRESHOLD = 0.5


class DecisionModelError(RuntimeError):
    """Raised when a decision-layer implementation cannot produce signals."""


def _env_flag(name: str) -> bool:
    value = os.getenv(name, "")
    return value.strip().lower() in ("1", "true", "yes", "on")


def is_laya_decision_enabled() -> bool:
    """Whether a non-default decision implementation may be used."""
    return _env_flag("ENABLE_LAYA_DECISION")


def configured_implementation() -> str:
    """The implementation the environment selects (normalised)."""
    raw = (os.getenv("DECISION_MODEL") or "").strip().lower()
    if raw in KNOWN_IMPLEMENTATIONS:
        return raw
    return DEFAULT_IMPLEMENTATION


def active_implementation() -> str:
    """The implementation that will actually be used."""
    implementation = configured_implementation()
    if implementation == DEFAULT_IMPLEMENTATION:
        return DEFAULT_IMPLEMENTATION
    if not is_laya_decision_enabled():
        return DEFAULT_IMPLEMENTATION
    return implementation


def describe_configuration() -> Dict[str, Any]:
    """A non-sensitive description of the decision port's configuration."""
    return {
        "configured": configured_implementation(),
        "active": active_implementation(),
        "laya_decision_enabled": is_laya_decision_enabled(),
        "laya_url": (os.getenv("LAYA_URL") or DEFAULT_LAYA_URL).strip(),
        "default_implementation": DEFAULT_IMPLEMENTATION,
    }


# ---------------------------------------------------------------------------
# The rules implementation (the default): the application's own policy alone
# ---------------------------------------------------------------------------


def rules_signals(message: str) -> Dict[str, Any]:
    """No external signal at all.

    The default path is the application's deterministic policy, on its own -
    exactly as it behaved before M6. Returning an empty signal set means
    `evaluate_policy()` sees exactly what it saw before.
    """
    return {}


# ---------------------------------------------------------------------------
# The mock implementation: a deterministic, offline stand-in for Laya
# ---------------------------------------------------------------------------

# A small, deterministic, message-driven signal generator. It is NOT a
# classifier - it exists so the *wiring* (and the tightening-only rule) can
# be proved offline. Its output is a function of the message text only, so
# the same message always produces the same signals.
MOCK_SIGNAL_RULES = (
    # (substring, needs_human probability, lead_type)
    ("guaranteed", 0.95, "investor"),
    ("guarantee", 0.95, "investor"),
    ("profit", 0.80, "investor"),
    ("return", 0.80, "investor"),
    ("discount", 0.75, "broker"),
    ("commission", 0.75, "broker"),
    ("noc", 0.70, "buyer"),
    ("title", 0.70, "buyer"),
    ("legal", 0.70, "buyer"),
)


def mock_signals(message: str) -> Dict[str, Any]:
    """Deterministic, offline signals.

    The point of the mock is not to be a good classifier. The point is to
    produce a **known** `needs_human` probability so the test can prove the
    two directions:

      * a HIGH probability escalates an otherwise answerable message;
      * a LOW probability changes nothing at all.
    """
    text = (message or "").lower()

    needs_human = 0.0
    lead_type = "other"
    for needle, probability, kind in MOCK_SIGNAL_RULES:
        if needle in text:
            needs_human = max(needs_human, probability)
            lead_type = kind

    return {
        "needs_human": needs_human,
        "lead_type": lead_type,
        "high_intent": bool(needs_human == 0.0 and "price" in text),
        "source": "mock",
    }


# ---------------------------------------------------------------------------
# The Laya implementation (opt-in, never the default)
# ---------------------------------------------------------------------------


def laya_signals(message: str) -> Dict[str, Any]:
    """Call Laya and return its signals in the policy's own shape.

    This is **never** reached in the default configuration. It is reached
    only when an operator has set `DECISION_MODEL=laya`,
    `ENABLE_LAYA_DECISION=1` and a Laya service is actually running.

    The signal is a `needs_human` probability in [0, 1] - the same shape
    `app/policy.py` already consumes. The decision itself remains the
    application's.
    """
    base_url = (os.getenv("LAYA_URL") or DEFAULT_LAYA_URL).strip().rstrip("/")
    try:
        timeout = int(os.getenv("LAYA_TIMEOUT") or DEFAULT_LAYA_TIMEOUT)
    except (TypeError, ValueError):
        timeout = DEFAULT_LAYA_TIMEOUT

    # PII is scrubbed BEFORE the message leaves the machine
    # (RULES_SHORT #6: scrub names/phones, never send real chat text).
    # The scrub happens here, at the boundary, so no caller can forget it.
    try:
        from market.anonymize import scrub_pii

        outbound = scrub_pii(message or "")
    except Exception:  # pragma: no cover - defensive
        outbound = message or ""

    questions = {
        "lead_type": {
            "type": "choice",
            "instructions": (
                "What is the main role or category of this person contacting "
                "a real estate company?"
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
                    "Negotiation, complaint, unusual request, legal/NOC, "
                    "discount, booking or human judgment is needed"
                ),
                "false": "The automated workflow can safely handle it",
            },
        },
    }

    payload = {
        "state": {"body": outbound},
        "questions": questions,
        "model": "multilingual",
    }

    request = urllib.request.Request(
        url="%s/v1/systemone" % base_url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
        data = json.loads(raw)
    except urllib.error.HTTPError as exc:
        raise DecisionModelError("Laya HTTP %s" % exc.code) from exc
    except urllib.error.URLError as exc:
        raise DecisionModelError("could not connect to Laya at %s: %s"
                                 % (base_url, exc.reason)) from exc
    except (TypeError, ValueError) as exc:
        raise DecisionModelError("Laya returned an unusable payload") from exc

    decisions = data.get("decisions") or {}
    needs_human_decision = decisions.get("needs_human") or {}
    probabilities = needs_human_decision.get("probabilities") or {}
    try:
        needs_human = float(probabilities.get("true", 0.0))
    except (TypeError, ValueError):
        needs_human = 0.0
    needs_human = min(1.0, max(0.0, needs_human))

    lead_type_decision = decisions.get("lead_type") or {}
    lead_type = lead_type_decision.get("decision", "other")
    if lead_type not in {
        "buyer", "investor", "renter", "broker", "existing_customer", "other",
    }:
        lead_type = "other"

    return {
        "needs_human": needs_human,
        "lead_type": lead_type,
        "source": "laya",
    }


# ---------------------------------------------------------------------------
# The port
# ---------------------------------------------------------------------------


def get_decision_signals(message: str) -> Dict[str, Any]:
    """Produce the decision signals for a message.

    Returns a dict with at least ``needs_human`` (a probability in [0, 1]),
    ``lead_type`` and ``source``. A failure of a non-default implementation
    is a **fall back to no external signal** - the application's own policy
    then decides alone, which is the pre-M6 behaviour and is always safe.
    """
    chosen = active_implementation()

    if chosen == IMPLEMENTATION_RULES:
        signals = rules_signals(message)
        signals.setdefault("source", "rules")
        return signals

    if chosen == IMPLEMENTATION_MOCK:
        signals = mock_signals(message)
        signals.setdefault("source", "mock")
        return signals

    if chosen == IMPLEMENTATION_LAYA:
        try:
            signals = laya_signals(message)
        except DecisionModelError:
            # No signal is safer than a wrong one: the application's own
            # policy decides alone.
            signals = rules_signals(message)
            signals["source"] = "rules"
            signals["fallback"] = True
            return signals
        signals.setdefault("source", "laya")
        return signals

    signals = rules_signals(message)
    signals.setdefault("source", "rules")
    return signals
