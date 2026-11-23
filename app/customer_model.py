"""M6 - the replaceable customer-facing model / phrasing port.

Architecture (handoff V2 section 7.3, FH-02 section 6 M6):

    dealer question
      -> application decision engine      (app/policy.py - deterministic)
      -> controlled policy
      -> approved inventory lookup         (market/price_lookup.py - one impl)
      -> application-calculated facts      (the fact set)
      -> LLM phrasing                      (THIS PORT)
      -> response traceability validation  (market/fact_validator.py - M5)
      -> reply or human escalation

The port is a **phrasing** port, not a fact port. It receives a fact set that
the application has already computed and approved, and it may only choose
**how** those facts are worded. It may not:

  * supply, alter or invent a number (RULES_SHORT #1, #2);
  * decide whether the question is answerable (the policy does that);
  * widen the scope (the lookup does that);
  * bypass validation (the M5 validator is still the final gate, and a
    model reply that fails it is blocked exactly like any other reply).

Implementations are selected **by configuration alone** (environment
variables), never by a code change in the lookup, the policy or the
validator:

    CUSTOMER_MODEL          "template" (default) | "mock" | "http"
    ENABLE_LLM_REPLY        "1"/"true"/"yes"/"on" to allow a non-default
                             implementation to be used at all
    CUSTOMER_MODEL_URL      the endpoint for the "http" implementation
    CUSTOMER_MODEL_NAME     the model name for the "http" implementation
    OPENROUTER_API_KEY      the credential for the "http" implementation

The **default is the deterministic template**, which is offline, needs no key
and makes no network call. The "mock" implementation is a deterministic
in-process stand-in used to exercise the swap **without** a provider, a key
or any spend - it is what the offline provider-swap test drives.

This module is stdlib-only (RULES_SHORT #5). It imports no HTTP client
library; the "http" implementation uses ``urllib.request`` from the standard
library, and it is only reachable when an operator has explicitly enabled a
non-default implementation AND supplied a credential.
"""

import json
import os
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

# The implementations this port knows about.
IMPLEMENTATION_TEMPLATE = "template"
IMPLEMENTATION_MOCK = "mock"
IMPLEMENTATION_HTTP = "http"
KNOWN_IMPLEMENTATIONS = (IMPLEMENTATION_TEMPLATE, IMPLEMENTATION_MOCK, IMPLEMENTATION_HTTP)

# The default is the deterministic, offline, no-key template.
DEFAULT_IMPLEMENTATION = IMPLEMENTATION_TEMPLATE

# How a reply was produced. Recorded in the audit trail (non-sensitive).
REPLY_SOURCE_TEMPLATE = "deterministic_template"
REPLY_SOURCE_MOCK = "deterministic_mock"
REPLY_SOURCE_HTTP = "external_model"


class CustomerModelError(RuntimeError):
    """Raised when a customer-model implementation cannot produce a reply.

    The caller must treat this as a **fall back to the deterministic
    template**, never as a reason to serve an unvalidated reply.
    """


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


def _env_flag(name: str) -> bool:
    value = os.getenv(name, "")
    return value.strip().lower() in ("1", "true", "yes", "on")


def is_llm_reply_enabled() -> bool:
    """Whether a non-default (non-template) implementation may be used.

    The template is the default and needs no switch. Any other
    implementation must be enabled explicitly, so that a stray environment
    variable can never silently start calling a provider.
    """
    return _env_flag("ENABLE_LLM_REPLY")


def configured_implementation() -> str:
    """The implementation the environment selects.

    Unknown names fall back to the deterministic template: an
    unrecognised configuration must not start a network call, and it must
    not fail the request either. The caller can see which one was used in
    ``reply_source``.
    """
    raw = (os.getenv("CUSTOMER_MODEL") or "").strip().lower()
    if not raw:
        return DEFAULT_IMPLEMENTATION
    if raw in KNOWN_IMPLEMENTATIONS:
        return raw
    return DEFAULT_IMPLEMENTATION


def active_implementation() -> str:
    """The implementation that will actually be used.

    A non-default implementation is used only when it is explicitly
    enabled. This is the "swap by configuration alone" rule: the decision
    is made entirely by environment variables.
    """
    implementation = configured_implementation()
    if implementation == DEFAULT_IMPLEMENTATION:
        return DEFAULT_IMPLEMENTATION
    if not is_llm_reply_enabled():
        return DEFAULT_IMPLEMENTATION
    return implementation


def describe_configuration() -> Dict[str, Any]:
    """A non-sensitive description of the port's configuration.

    It reports **whether** a credential is present, never the credential.
    """
    return {
        "configured": configured_implementation(),
        "active": active_implementation(),
        "llm_reply_enabled": is_llm_reply_enabled(),
        "credential_present": bool((os.getenv("OPENROUTER_API_KEY") or "").strip()),
        "default_implementation": DEFAULT_IMPLEMENTATION,
    }


# ---------------------------------------------------------------------------
# The fact set the port is given
# ---------------------------------------------------------------------------


def build_model_facts(facts: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Reduce the fact set to exactly the fields the port may use.

    The port is given a **read-only, explicit** view of the facts - not the
    whole fact set, and never the raw inventory, never a dealer chat and
    never a sender identity. ``price_min_pkr`` / ``price_median_pkr`` /
    ``price_max_pkr`` are present only when the cell is answerable, so a
    thin cell cannot be phrased with a price even by a model that invents
    one (and if it did, the M5 validator would block it).
    """
    if not isinstance(facts, dict):
        return {
            "answerable": False,
            "matched_plots": None,
            "observation_count": None,
            "price_min_pkr": None,
            "price_median_pkr": None,
            "price_max_pkr": None,
            "latest_date": None,
            "coverage_level": None,
            "closest_match": None,
        }

    answerable = bool(facts.get("answerable_for_demo"))

    closest = facts.get("closest_match")
    closest_view = None
    if isinstance(closest, dict):
        closest_view = {
            "block": closest.get("block"),
            "size_marla": closest.get("size_marla"),
            "same_block": bool(closest.get("same_block")),
        }

    # M8: the verified alternatives. Only entries the application marked
    # ``verified`` are passed to the port, and only the block and the
    # size travel - the port may word an alternative, never create one.
    alternatives_view = []
    raw_alternatives = facts.get("verified_alternatives")
    if isinstance(raw_alternatives, (list, tuple)):
        for item in raw_alternatives:
            if not isinstance(item, dict):
                continue
            if item.get("verified") is not True:
                continue
            alternatives_view.append({
                "block": item.get("block"),
                "size_marla": item.get("size_marla"),
            })

    return {
        "answerable": answerable,
        "matched_plots": facts.get("matched_plots"),
        "observation_count": facts.get("observation_count"),
        # A non-answerable cell carries NO price, whatever the master holds.
        "price_min_pkr": facts.get("price_min_pkr") if answerable else None,
        "price_median_pkr": facts.get("price_median_pkr") if answerable else None,
        "price_max_pkr": facts.get("price_max_pkr") if answerable else None,
        "latest_date": facts.get("latest_date"),
        "coverage_level": facts.get("coverage_level"),
        "closest_match": closest_view,
        # M8: the application's VERIFIED alternatives. The port may word
        # them; it may not invent one. Only an entry the application
        # marked ``verified`` is passed on.
        "verified_alternatives": alternatives_view,
    }


# ---------------------------------------------------------------------------
# The deterministic template (the default)
# ---------------------------------------------------------------------------


def render_template_reply(
    facts: Optional[Dict[str, Any]],
    base_reply: str = "",
    block: Optional[str] = None,
    size_marla: Optional[float] = None,
) -> str:
    """The deterministic phrasing.

    It uses the **application's own** wording so the default path is exactly
    what shipped before M6 - byte-for-byte the same sentence the M5
    validator already proved traceable. That is deliberate: the default
    path must not change behaviour, only the port's *shape* changes.

    M8: when the application has ranked VERIFIED alternatives, the
    insufficient-data reply names them as well, without a price. The
    wording is added by the application, from the fact set - never by a
    model - and the M6.1 claim guard checks the result exactly like any
    other reply.
    """
    view = build_model_facts(facts)

    if base_reply and not view.get("verified_alternatives"):
        return base_reply

    if view["answerable"] and view["price_min_pkr"] is not None:
        minimum = view["price_min_pkr"]
        maximum = view["price_max_pkr"]
        median = view["price_median_pkr"]
        count = view["matched_plots"]
        observations = view["observation_count"]
        latest = view["latest_date"]
        parts = [
            "Based on %s matching listing%s and %s recorded observation%s "
            "in the current partial Faisal Hills market data, "
            % (
                count,
                "" if count == 1 else "s",
                observations,
                "" if observations == 1 else "s",
            )
        ]
        if minimum is not None and maximum is not None:
            parts.append(
                "the asking-price range is PKR %s to PKR %s"
                % ("{:,.0f}".format(minimum), "{:,.0f}".format(maximum))
            )
        if median is not None:
            parts.append(", with a median of PKR %s" % "{:,.0f}".format(median))
        if latest:
            parts.append(". Latest observation date: %s" % latest)
        parts.append(
            ". These are dealer asking prices, not confirmed sold prices. "
            "Human approval is required before sending."
        )
        return "".join(parts)

    # Not enough data: name the closest match, never a number.
    closest = view.get("closest_match")
    alternatives = view.get("verified_alternatives") or []

    if base_reply:
        # The application's own wording is preserved byte-for-byte, and
        # the verified alternatives are appended by the application.
        base = base_reply
    elif closest and closest.get("size_marla") is not None:
        base = (
            "I need to confirm the current market information with our team "
            "before giving you a price. The closest match with more data is "
            "a %s marla plot in Block %s."
            % (
                "{:g}".format(float(closest["size_marla"])),
                closest.get("block"),
            )
        )
    else:
        base = (
            "I need to confirm the current market information with our team "
            "before giving you a price."
        )

    # M8: the verified alternatives are named as well, WITHOUT a price -
    # the dealer is pointed at real cells, and the number comes from the
    # answerable path or from a human. The wording never claims
    # availability: the master is a partial snapshot of asking prices.
    named = []
    for item in alternatives:
        size = item.get("size_marla")
        block_code = item.get("block")
        if size is None or not block_code:
            continue
        # The closest match is already named in the sentence above.
        if (closest and closest.get("size_marla") is not None
                and block_code == closest.get("block")
                and abs(float(size) - float(closest["size_marla"])) <= 0.001):
            continue
        named.append(
            "a %s marla plot in Block %s"
            % ("{:g}".format(float(size)), block_code)
        )

    if named:
        return (
            "%s Other verified alternatives with more data are %s. "
            "Tell me your preferred size or block and I can narrow them "
            "down." % (base, _join_phrases(named))
        )

    return base


def _join_phrases(items):
    """Join a list of phrases into a readable English list."""
    items = [str(item) for item in items if str(item).strip()]
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    if len(items) == 2:
        return "%s and %s" % (items[0], items[1])
    return "%s and %s" % (", ".join(items[:-1]), items[-1])


# ---------------------------------------------------------------------------
# The deterministic mock (offline provider-swap stand-in)
# ---------------------------------------------------------------------------

# The mock is deterministic: the same facts always produce the same text.
# It re-phrases the template's facts in a different sentence shape, so the
# provider-swap test can prove that a *different* implementation produced
# a reply while the numbers stayed the same and still validated.
MOCK_PREFIX = "Here is what the current Faisal Hills market data shows"


def render_mock_reply(
    facts: Optional[Dict[str, Any]],
    base_reply: str = "",
    block: Optional[str] = None,
    size_marla: Optional[float] = None,
) -> str:
    """A deterministic, offline, in-process stand-in for a hosted model.

    It phrases the same approved facts in a different sentence shape. It
    makes no network call, needs no key, and is used to prove that the port
    can be swapped without touching the lookup, the policy or the validator.
    """
    view = build_model_facts(facts)
    if view["answerable"] and view["price_min_pkr"] is not None:
        count = view["matched_plots"]
        minimum = view["price_min_pkr"]
        median = view["price_median_pkr"]
        maximum = view["price_max_pkr"]
        latest = view["latest_date"]
        text = (
            "%s: %s matching listing%s, asking prices from PKR %s to PKR %s, "
            "median PKR %s"
            % (
                MOCK_PREFIX,
                count,
                "" if count == 1 else "s",
                "{:,.0f}".format(minimum),
                "{:,.0f}".format(maximum),
                "{:,.0f}".format(median),
            )
        )
        if latest:
            text += ", latest observation date %s" % latest
        # M6.1: the mock must keep the SAME provenance the template
        # keeps. It originally said only "these are dealer asking
        # prices", which dropped the "not confirmed sold prices" marker
        # - a provenance loss the M6.1 claim guard (market/reply_guard.py)
        # now detects. The mock is a stand-in for a hosted model, and a
        # model that drops the marker is exactly the failure mode the
        # guard exists to catch, so the shipped mock must not do it.
        text += (
            ". These are dealer asking prices, not confirmed sold prices, "
            "and a member of our team approves every reply before it is "
            "sent."
        )
        return text

    closest = view.get("closest_match")
    if closest and closest.get("size_marla") is not None:
        return (
            "%s: there is not enough data for that size yet, so I will not "
            "quote a number. The closest match with more data is a %s marla "
            "plot in Block %s, and a member of our team will confirm the "
            "current market information."
            % (
                MOCK_PREFIX,
                "{:g}".format(float(closest["size_marla"])),
                closest.get("block"),
            )
        )

    return (
        "%s: there is not enough data yet, so I will not quote a number, and "
        "a member of our team will confirm the current market information."
        % MOCK_PREFIX
    )


# ---------------------------------------------------------------------------
# The external model implementation (opt-in, never the default)
# ---------------------------------------------------------------------------

HTTP_PROMPT = (
    "You are a real estate assistant for Faisal Hills Islamabad/Taxila.\n"
    "Rewrite the reply below in clear, friendly dealer language.\n"
    "Rules:\n"
    "1. Use ONLY the numbers that appear in the supplied facts. Never add, "
    "change, round or estimate a number.\n"
    "2. If a fact is null, do not mention it. Never say a price unless the "
    "facts contain one.\n"
    "3. Do not name dealers, senders, plot owners or any private detail.\n"
    "4. Reply with the rewritten text only - no preamble, no JSON.\n"
    "5. Keep EVERY disclaimer the reply already contains. If the reply "
    "says the prices are asking prices and not confirmed sold prices, "
    "keep both; if it says a member of the team must approve it, keep "
    "that. Dropping a disclaimer is a rejected reply.\n"
    "6. Never say a plot is available, in stock, for sale or guaranteed. "
    "Never name a block or a size that is not in the facts.\n"
    "\n"
    "FACTS:\n{facts}\n"
    "\n"
    "REPLY TO REWRITE:\n{reply}\n"
)


def _http_reply(
    facts: Optional[Dict[str, Any]],
    base_reply: str,
    block: Optional[str],
    size_marla: Optional[float],
) -> str:
    """Call an external chat-completions endpoint.

    This is **never** reached in the default configuration. It is reached
    only when an operator has set ``CUSTOMER_MODEL=http``,
    ``ENABLE_LLM_REPLY=1`` and supplied a credential. It spends money, so it
    is deliberately the most awkward path to turn on.
    """
    api_key = (os.getenv("OPENROUTER_API_KEY") or "").strip()
    if not api_key:
        raise CustomerModelError("no credential configured for the http customer model")

    url = (os.getenv("CUSTOMER_MODEL_URL") or "").strip()
    if not url:
        raise CustomerModelError("CUSTOMER_MODEL_URL is not configured")

    model = (os.getenv("CUSTOMER_MODEL_NAME") or "").strip()
    if not model:
        raise CustomerModelError("CUSTOMER_MODEL_NAME is not configured")

    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": HTTP_PROMPT.format(
                    facts=json.dumps(build_model_facts(facts), sort_keys=True, default=str),
                    reply=base_reply or "",
                ),
            }
        ],
        "temperature": 0.0,
    }

    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": "Bearer %s" % api_key,
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            data = json.loads(response.read().decode("utf-8"))
        content = data["choices"][0]["message"]["content"].strip()
    except urllib.error.HTTPError as exc:
        raise CustomerModelError("customer model HTTP %s" % exc.code) from exc
    except urllib.error.URLError as exc:
        raise CustomerModelError("customer model unreachable: %s" % exc.reason) from exc
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise CustomerModelError("customer model returned an unusable payload") from exc

    if not content:
        raise CustomerModelError("customer model returned an empty reply")
    return content


# ---------------------------------------------------------------------------
# The port
# ---------------------------------------------------------------------------


def phrase_reply(
    facts: Optional[Dict[str, Any]] = None,
    base_reply: str = "",
    block: Optional[str] = None,
    size_marla: Optional[float] = None,
    implementation: Optional[str] = None,
) -> Dict[str, Any]:
    """Phrase a reply through the configured customer-model implementation.

    Returns::

        {"reply": str, "reply_source": str, "implementation": str,
         "fell_back": bool, "error": Optional[str]}

    The reply is **never** trusted by the caller. It is the M5 validator's
    job to decide whether the numbers in it trace to an approved fact, and
    that validation happens *after* this function, on every path, exactly as
    it did before the port existed.

    A failure of a non-default implementation is a **fall back to the
    deterministic template**, not an error the customer sees.
    """
    chosen = implementation or active_implementation()

    if chosen == IMPLEMENTATION_TEMPLATE:
        return {
            "reply": render_template_reply(facts, base_reply, block, size_marla),
            "reply_source": REPLY_SOURCE_TEMPLATE,
            "implementation": IMPLEMENTATION_TEMPLATE,
            "fell_back": False,
            "error": None,
        }

    if chosen == IMPLEMENTATION_MOCK:
        return {
            "reply": render_mock_reply(facts, base_reply, block, size_marla),
            "reply_source": REPLY_SOURCE_MOCK,
            "implementation": IMPLEMENTATION_MOCK,
            "fell_back": False,
            "error": None,
        }

    if chosen == IMPLEMENTATION_HTTP:
        try:
            reply = _http_reply(facts, base_reply, block, size_marla)
        except CustomerModelError as exc:
            # Fall back to the deterministic template. The failure is
            # reported so the operator can see it, but the customer still
            # gets a validated answer.
            return {
                "reply": render_template_reply(facts, base_reply, block, size_marla),
                "reply_source": REPLY_SOURCE_TEMPLATE,
                "implementation": IMPLEMENTATION_TEMPLATE,
                "fell_back": True,
                "error": str(exc),
            }
        return {
            "reply": reply,
            "reply_source": REPLY_SOURCE_HTTP,
            "implementation": IMPLEMENTATION_HTTP,
            "fell_back": False,
            "error": None,
        }

    # An unknown implementation never reaches here (configured_implementation
    # normalises it), but the port must not fail closed on a typo.
    return {
        "reply": render_template_reply(facts, base_reply, block, size_marla),
        "reply_source": REPLY_SOURCE_TEMPLATE,
        "implementation": IMPLEMENTATION_TEMPLATE,
        "fell_back": True,
        "error": "unknown customer model implementation %r" % chosen,
    }
