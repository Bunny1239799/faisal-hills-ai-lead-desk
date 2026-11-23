"""M6 - the replaceable customer-facing model / phrasing port.

Covers the FH-02 section 6 M6 acceptance criteria:

  (a) with the model OFF (the default), the demo path still answers
      correctly from templates;
  (b) with the model ON, every number in the reply passes the M5 validator
      and unsupported claims = 0;
  (c) the implementation can be swapped by changing env vars only - no code
      change in the lookup, the policy or the validator;
  (d) the model can only change the WORDING: it may never supply a fact,
      calculate a price, widen the scope, or bypass validation.

The port is exercised **offline**: the "mock" implementation is a
deterministic in-process stand-in. No provider is called, no key is read,
no quota is spent.
"""

import io
import json
import os
import sys

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from app import customer_model  # noqa: E402
from app.pipeline import handle_message  # noqa: E402
from market import price_lookup  # noqa: E402
from market.fact_validator import extract_numbers, validate_reply  # noqa: E402

ANSWERABLE = [("A", 5), ("A", 7), ("A", 10), ("A", 20), ("B", 5), ("B", 10),
              ("B", 14), ("B", 20), ("C", 5), ("C", 7), ("C", 20)]
THIN = [("A", 14), ("B", 7), ("C", 10), ("C", 14)]


@pytest.fixture(autouse=True)
def _clean_env():
    """Every test starts from the DEFAULT configuration."""
    saved = {}
    for name in ("CUSTOMER_MODEL", "ENABLE_LLM_REPLY", "CUSTOMER_MODEL_URL",
                 "CUSTOMER_MODEL_NAME", "OPENROUTER_API_KEY"):
        saved[name] = os.environ.pop(name, None)
    yield
    for name, value in saved.items():
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value


# ---------------------------------------------------------------------------
# The port's own contract
# ---------------------------------------------------------------------------


def test_m6_the_default_implementation_is_the_deterministic_template():
    assert customer_model.configured_implementation() == "template"
    assert customer_model.active_implementation() == "template"
    assert customer_model.DEFAULT_IMPLEMENTATION == "template"


def test_m6_the_port_makes_no_network_call_by_default():
    """The default path must not touch the network and must not read a
    credential."""
    os.environ["OPENROUTER_API_KEY"] = "sk-not-a-real-key"
    outcome = customer_model.phrase_reply(
        facts=price_lookup.lookup_price(block="C", size_marla=7)["facts"],
        base_reply="",
    )
    assert outcome["implementation"] == "template"
    assert outcome["reply_source"] == "deterministic_template"
    assert outcome["fell_back"] is False
    assert outcome["error"] is None


def test_m6_an_unknown_implementation_falls_back_to_the_template():
    os.environ["CUSTOMER_MODEL"] = "not-a-real-model"
    outcome = customer_model.phrase_reply(facts=None, base_reply="hello")
    assert outcome["implementation"] == "template"
    assert outcome["reply_source"] == "deterministic_template"
    assert outcome["reply"] == "hello"


def test_m6_a_non_default_implementation_needs_the_explicit_switch():
    """A stray CUSTOMER_MODEL variable must never start a provider."""
    os.environ["CUSTOMER_MODEL"] = "http"
    assert customer_model.configured_implementation() == "http"
    assert customer_model.active_implementation() == "template"

    os.environ["ENABLE_LLM_REPLY"] = "1"
    assert customer_model.active_implementation() == "http"


def test_m6_the_configuration_description_never_leaks_the_credential():
    os.environ["OPENROUTER_API_KEY"] = "sk-secret-value-12345"
    description = customer_model.describe_configuration()
    assert description["credential_present"] is True
    assert "sk-secret-value-12345" not in json.dumps(description)


def test_m6_the_port_receives_no_sender_identity_and_no_raw_text():
    """The port may only see an explicit, read-only view of the facts."""
    facts = price_lookup.lookup_price(block="C", size_marla=7)["facts"]
    view = customer_model.build_model_facts(facts)

    assert set(view) == {
        "answerable", "matched_plots", "observation_count", "price_min_pkr",
        "price_median_pkr", "price_max_pkr", "latest_date", "coverage_level",
        "closest_match",
        # M8: the application's verified alternatives. The port may word
        # them; it may never create one. Only the block and the size
        # travel, so the field cannot carry a price, a count or any
        # private detail.
        "verified_alternatives",
    }
    blob = json.dumps(view, default=str)
    assert "raw_text" not in blob
    assert "sender" not in blob
    assert "notes" not in blob
    assert "plot_number" not in blob


def test_m6_a_thin_cell_gives_the_port_no_price_at_all():
    facts = price_lookup.lookup_price(block="B", size_marla=7)["facts"]
    view = customer_model.build_model_facts(facts)

    assert view["answerable"] is False
    assert view["price_min_pkr"] is None
    assert view["price_median_pkr"] is None
    assert view["price_max_pkr"] is None
    # The closest match is named, but it carries no price either.
    assert view["closest_match"]["size_marla"] == 5
    assert "price" not in json.dumps(view["closest_match"])


# ---------------------------------------------------------------------------
# (a) with the model OFF the demo path still answers from templates
# ---------------------------------------------------------------------------


def test_m6_with_the_model_off_the_demo_path_answers_correctly():
    for block, size_marla in ANSWERABLE:
        result = handle_message(
            "What is the price of a %s marla plot in Block %s?" % (size_marla, block)
        )
        assert result.get("traceability_ok") is True, (block, size_marla)
        assert result.get("traceability_blocked") is False
        assert result.get("reply_source") == "deterministic_template"
        assert result.get("customer_model", {}).get("implementation") == "template"
        facts = (result.get("market_facts") or {}).get("facts") or {}
        assert facts.get("price_median_pkr") is not None
        assert "PKR" in (result.get("draft_reply") or "")


def test_m6_the_default_reply_is_unchanged_by_the_port():
    """The default path must produce exactly the wording M5 already proved
    traceable - the port must not alter the shipped behaviour.

    M13: the conversational property-options layer APPENDS its section
    to the default wording, so the shipped wording is checked as the
    FIRST LINE of the draft."""
    expected = price_lookup.lookup_price(block="C", size_marla=7)["reply"]
    result = handle_message("What is the price of a 7 marla plot in Block C?")
    first_line = (result.get("draft_reply") or "").splitlines()[0]
    assert first_line == expected


# ---------------------------------------------------------------------------
# (b) with the model ON every number still passes the M5 validator
# ---------------------------------------------------------------------------


def test_m6_with_the_model_on_every_number_still_validates():
    os.environ["CUSTOMER_MODEL"] = "mock"
    os.environ["ENABLE_LLM_REPLY"] = "1"

    for block, size_marla in ANSWERABLE:
        result = handle_message(
            "What is the price of a %s marla plot in Block %s?" % (size_marla, block)
        )
        assert result.get("traceability_ok") is True, (block, size_marla)
        assert result.get("traceability_blocked") is False
        assert result.get("reply_source") == "deterministic_mock"
        facts = (result.get("market_facts") or {}).get("facts") or {}
        validation = validate_reply(
            result.get("draft_reply") or "",
            facts,
            context={"size_marla": size_marla},
        )
        assert validation.ok is True, validation.reason


def test_m6_with_the_model_on_a_thin_reply_still_carries_no_price():
    os.environ["CUSTOMER_MODEL"] = "mock"
    os.environ["ENABLE_LLM_REPLY"] = "1"

    for block, size_marla in THIN:
        result = handle_message(
            "What is the price of a %s marla plot in Block %s?" % (size_marla, block)
        )
        reply = result.get("draft_reply") or ""
        assert "PKR" not in reply
        for _raw, value in extract_numbers(reply):
            assert value < 1000
        assert result.get("traceability_ok") is True


def test_m6_the_mock_produces_a_different_wording_but_the_same_numbers():
    """The swap must be real: different wording, identical facts."""
    os.environ["CUSTOMER_MODEL"] = "mock"
    os.environ["ENABLE_LLM_REPLY"] = "1"
    mocked = handle_message("What is the price of a 7 marla plot in Block C?")
    mocked_reply = mocked.get("draft_reply") or ""

    os.environ["CUSTOMER_MODEL"] = "template"
    templated = handle_message("What is the price of a 7 marla plot in Block C?")
    template_reply = templated.get("draft_reply") or ""

    assert mocked_reply != template_reply
    assert mocked_reply.startswith(customer_model.MOCK_PREFIX)
    # The same FACTS: every number the mock produced is one the template
    # also produced, i.e. it came from the same approved fact set. A model
    # may phrase fewer facts, but never a different one.
    template_numbers = [v for _r, v in extract_numbers(template_reply)]
    mock_numbers = [v for _r, v in extract_numbers(mocked_reply)]
    assert mock_numbers, "the mock reply carried no number at all"
    for value in mock_numbers:
        assert value in template_numbers, (
            "the mock introduced a number the template did not: %r" % value
        )


# ---------------------------------------------------------------------------
# (c) the provider can be swapped by configuration alone
# ---------------------------------------------------------------------------


def test_m6_the_swap_needs_no_change_in_the_lookup_policy_or_validator():
    """Swapping the implementation must not touch the fact set, the policy
    decision or the validator's verdict."""
    baseline = handle_message("What is the price of a 7 marla plot in Block C?")
    baseline_facts = (baseline.get("market_facts") or {}).get("facts") or {}

    os.environ["CUSTOMER_MODEL"] = "mock"
    os.environ["ENABLE_LLM_REPLY"] = "1"
    swapped = handle_message("What is the price of a 7 marla plot in Block C?")
    swapped_facts = (swapped.get("market_facts") or {}).get("facts") or {}

    assert swapped_facts == baseline_facts
    assert (swapped.get("decision") or {}).get("action") == \
           (baseline.get("decision") or {}).get("action")
    assert swapped.get("traceability_ok") == baseline.get("traceability_ok")


def test_m6_the_lookup_policy_and_validator_sources_are_untouched_by_a_swap():
    """A swap is a configuration change; the three controlling modules must
    not change because of it."""
    import app.policy
    import market.fact_validator
    import market.price_lookup

    for module in (app.policy, market.fact_validator, market.price_lookup):
        source = io.open(module.__file__, encoding="utf-8").read()
        assert "customer_model" not in source, (
            "%s must not know about the customer-model port" % module.__name__
        )


def test_m6_the_port_does_not_modify_the_approved_master():
    import hashlib

    master = price_lookup.MASTER_PATH
    if not os.path.exists(master):
        pytest.skip("approved master is not present at its configured path")

    def digest():
        h = hashlib.sha256()
        with open(master, "rb") as handle:
            for chunk in iter(lambda: handle.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()

    before = digest()
    os.environ["CUSTOMER_MODEL"] = "mock"
    os.environ["ENABLE_LLM_REPLY"] = "1"
    for block, size_marla in ANSWERABLE:
        handle_message("What is the price of a %s marla plot in Block %s?"
                       % (size_marla, block))
    assert digest() == before


# ---------------------------------------------------------------------------
# (d) the model may tighten, never loosen
# ---------------------------------------------------------------------------


def test_m6_a_model_reply_with_an_unsupported_number_is_blocked():
    """A model that invents a price must be stopped by the M5 validator -
    the port is not a trust boundary."""
    import app.pipeline as pipeline

    os.environ["CUSTOMER_MODEL"] = "mock"
    os.environ["ENABLE_LLM_REPLY"] = "1"

    original = pipeline._customer_model.phrase_reply

    def rogue(*args, **kwargs):
        outcome = original(*args, **kwargs)
        outcome = dict(outcome)
        outcome["reply"] = (
            "Based on 21 matching listings the asking-price range is PKR "
            "6,000,000 to PKR 11,500,000, with a median of PKR 9,999,999."
        )
        outcome["reply_source"] = "deterministic_mock"
        return outcome

    pipeline._customer_model.phrase_reply = rogue
    try:
        result = handle_message("What is the price of a 7 marla plot in Block C?")
    finally:
        pipeline._customer_model.phrase_reply = original

    assert result.get("traceability_blocked") is True
    assert result.get("traceability_ok") is False
    assert "9,999,999" not in (result.get("draft_reply") or "")
    assert result.get("market_facts") is None
    assert result.get("needs_human") is True
    assert result["decision"]["action"] == "escalate"


def test_m6_a_model_cannot_soften_a_refusal():
    """The port never gets to re-word an escalated or refused message."""
    os.environ["CUSTOMER_MODEL"] = "mock"
    os.environ["ENABLE_LLM_REPLY"] = "1"

    result = handle_message("Can you give me a discount on a 5 marla plot in Block B?")
    assert result["decision"]["action"] in ("escalate", "refuse")
    assert result.get("needs_human") is True
    # The base pipeline's own hold wording is kept.
    assert "member of our team" in (result.get("draft_reply") or "").lower()
    assert "PKR" not in (result.get("draft_reply") or "")


def test_m6_a_model_cannot_widen_the_scope():
    """A parked block stays unpriced, whatever the model says."""
    os.environ["CUSTOMER_MODEL"] = "mock"
    os.environ["ENABLE_LLM_REPLY"] = "1"

    result = handle_message("What is the price of a 5 marla plot in Block E?")
    reply = result.get("draft_reply") or ""
    assert "PKR" not in reply
    assert result.get("market_facts") is None


def test_m6_the_model_is_never_asked_for_a_fact_it_could_invent():
    """The port's HTTP prompt forbids adding a number, and the fact view it
    receives is already reduced."""
    prompt = customer_model.HTTP_PROMPT.lower()
    assert "never add" in prompt
    assert "only the numbers that appear in the supplied facts" in prompt
    assert "do not quote a price" in prompt or "never say a price" in prompt


# ---------------------------------------------------------------------------
# The audit trail records where the wording came from
# ---------------------------------------------------------------------------


def test_m6_the_audit_trail_records_the_reply_source():
    import app.pipeline as pipeline

    os.environ["CUSTOMER_MODEL"] = "mock"
    os.environ["ENABLE_LLM_REPLY"] = "1"

    recorded = {}
    original = pipeline._fh_record_validated_reply

    def capture(result, facts, filters):
        recorded["source"] = result.get("reply_source")
        recorded["model"] = result.get("customer_model")
        return original(result, facts, filters)

    pipeline._fh_record_validated_reply = capture
    try:
        handle_message("What is the price of a 7 marla plot in Block C?")
    finally:
        pipeline._fh_record_validated_reply = original

    assert recorded.get("source") == "deterministic_mock"
    assert recorded.get("model", {}).get("implementation") == "mock"
