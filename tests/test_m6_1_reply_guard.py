"""M6.1 - reply claim / shape / provenance hardening.

The M6 milestone left one gap: the model ports existed, but nothing
stopped model-generated **wording** from introducing a claim the
approved master does not support. M5's validator checks **numbers**;
it cannot see a claim that carries no new number.

This module proves the gap is closed. Every test here is written
against a **measured** behaviour of the approved master, not against an
assumption.

The three holes this closes were measured before the guard was
written - all three passed the M5 numeric validator:

  1. an availability claim on a cell the application already refused
     to answer ("Yes, we have 5 marla plots in Block C" - the only
     number is the customer's own size, which the validator permits);
  2. a size claim that rides in on the observation date ("we also have
     10 marla plots" - 10 is permitted because the approved date is
     2026-10-07);
  3. a scope claim ("we also have plots in Block D" - no number at all,
     so the numeric validator cannot see it).

Run with:  python -m pytest tests/test_m6_1_reply_guard.py -q
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
from market import reply_guard  # noqa: E402

# Every answerable cell in the active scope, measured against the
# approved master (374 rows; 339 in scope for A/B/C).
ANSWERABLE = [
    ("A", 5), ("A", 7), ("A", 10), ("A", 20), ("A", 40),
    ("B", 5), ("B", 10), ("B", 14), ("B", 20),
    ("C", 5), ("C", 7), ("C", 20),
]

# The three thin cells, measured against the approved master.
THIN = [("A", 14), ("B", 7), ("C", 10)]

# Replies that the M5 numeric validator ACCEPTS but that assert
# something the approved master does not support. These are the
# regression cases for the gap.
#
# The list is measured, not assumed: each reply below was run through
# `market.fact_validator.validate_reply` and passed. A reply that the
# numeric validator already caught (for example "Yes, we have 5 marla
# plots in Block C" - the number 5 is not in the C/7 fact set) is NOT
# in this list, because it proves nothing about the claim guard.
NUMERICALLY_VALID_BUT_UNSUPPORTED = [
    # 10 is a permitted number: the approved observation date is
    # 2026-10-07, so the date's parts are whitelisted.
    "Based on the data, we also have 10 marla plots in Block C.",
    # No number at all - the numeric validator cannot see a scope claim.
    "We also have plots in Block D.",
    # The only number is the requested size, which the validator permits
    # because it is the customer's own figure.
    "We have 7 marla plots available in Block C.",
    "There are 7 marla plots in Block C for sale.",
]


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


def _facts(block, size_marla):
    return price_lookup.lookup_price(block=block, size_marla=size_marla)


# ---------------------------------------------------------------------------
# The gap itself: these three pass the M5 numeric validator today
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("rogue", NUMERICALLY_VALID_BUT_UNSUPPORTED)
def test_m6_1_the_numeric_validator_alone_does_not_see_these_claims(rogue):
    """The premise of this milestone, proved.

    Each rogue reply passes the M5 numeric validator - otherwise the
    claim guard would be redundant and this milestone would be
    unnecessary. The gap is real.
    """
    from market import fact_validator

    result = _facts("C", 7)
    validation = fact_validator.validate_reply(
        rogue, result["facts"], context={"size_marla": 7}
    )
    assert validation.ok is True, (
        "the premise changed: the M5 validator now catches this reply "
        "(%s)" % validation.reason
    )


@pytest.mark.parametrize("rogue", NUMERICALLY_VALID_BUT_UNSUPPORTED)
def test_m6_1_the_claim_guard_rejects_what_the_numeric_validator_accepts(rogue):
    """The gap is closed: the claim guard refuses the same replies."""
    result = _facts("C", 7)
    report = reply_guard.guard_reply(
        rogue, result["facts"], filters=result["filters"]
    )
    assert report.ok is False, (
        "the claim guard accepted an unsupported claim: %r" % rogue
    )
    assert report.violations


# ---------------------------------------------------------------------------
# No false positives: every real reply must still pass
# ---------------------------------------------------------------------------


def test_m6_1_every_answerable_reply_passes_the_claim_guard():
    """Zero false positives on the real reply set."""
    for block, size_marla in ANSWERABLE:
        result = _facts(block, size_marla)
        report = reply_guard.guard_reply(
            result["reply"], result["facts"], filters=result["filters"]
        )
        assert report.ok is True, (
            (block, size_marla), report.violations, result["reply"]
        )
        assert report.state == reply_guard.STATE_ANSWERABLE


def test_m6_1_every_thin_reply_passes_the_claim_guard():
    """The "not enough data" reply keeps its hand-off and is not blocked."""
    for block, size_marla in THIN:
        result = _facts(block, size_marla)
        report = reply_guard.guard_reply(
            result["reply"], result["facts"], filters=result["filters"]
        )
        assert report.ok is True, (
            (block, size_marla), report.violations, result["reply"]
        )
        assert report.state == reply_guard.STATE_INSUFFICIENT


def test_m6_1_the_pipeline_reports_the_claim_guard_on_every_path():
    """The guard runs on the serving path, not only in the unit tests."""
    for block, size_marla in ANSWERABLE + THIN:
        result = handle_message(
            "What is the price of a %s marla plot in Block %s?"
            % (size_marla, block)
        )
        assert result.get("claim_guard_ok") is True, (block, size_marla)
        assert result.get("claim_guard_blocked") is False
        assert result.get("claim_guard", {}).get("state") in (
            reply_guard.STATE_ANSWERABLE,
            reply_guard.STATE_INSUFFICIENT,
        )


# ---------------------------------------------------------------------------
# Scope
# ---------------------------------------------------------------------------


def test_m6_1_a_reply_naming_a_parked_block_is_rejected():
    result = _facts("C", 7)
    for rogue in (
        "We also have plots in Block D.",
        "Executive Block has 7 marla plots at PKR 9,000,000.",
        "There are 7 marla plots in Block E for sale.",
    ):
        report = reply_guard.guard_reply(
            rogue, result["facts"], filters=result["filters"]
        )
        assert report.ok is False, rogue
        assert any(
            v["code"] == "out_of_scope_block" for v in report.violations
        ), report.violations


def test_m6_1_a_reply_naming_an_in_scope_block_is_not_rejected():
    """A block the scope DOES cover must not be flagged."""
    result = _facts("C", 7)
    report = reply_guard.guard_reply(
        "The closest match with more data is a 5 marla plot in Block B.",
        result["facts"], filters=result["filters"],
    )
    # Block B is in scope, so there is no scope violation. The reply may
    # still fail the provenance rule - it is not an answerable reply.
    assert not any(
        v["code"] == "out_of_scope_block" for v in report.violations
    ), report.violations


# ---------------------------------------------------------------------------
# Unsupported sizes and pairs
# ---------------------------------------------------------------------------


def test_m6_1_a_size_the_evidence_does_not_cover_is_rejected():
    result = _facts("C", 7)
    report = reply_guard.guard_reply(
        "We also have 10 marla plots in Block C.",
        result["facts"], filters=result["filters"],
    )
    assert report.ok is False
    assert any(v["code"] == "unsupported_size" for v in report.violations)


def test_m6_1_a_block_and_size_combination_the_evidence_does_not_cover_is_rejected():
    """Both parts individually known, the combination unknown."""
    result = _facts("C", 7)
    # 7 marla is the requested size; Block B is in scope; but no
    # evidence covers 7 marla in Block B.
    report = reply_guard.guard_reply(
        "The closest match with more data is a 7 marla plot in Block B.",
        result["facts"], filters=result["filters"],
    )
    assert report.ok is False
    assert any(v["code"] == "unsupported_pair" for v in report.violations)


def test_m6_1_the_requested_size_itself_is_permitted():
    """The customer's own figure may be echoed."""
    result = _facts("C", 7)
    report = reply_guard.guard_reply(
        "We are checking 7 marla in Block C for you.",
        result["facts"], filters=result["filters"],
    )
    assert not any(
        v["code"] in ("unsupported_size", "unsupported_pair")
        for v in report.violations
    ), report.violations


# ---------------------------------------------------------------------------
# Certainty and sold prices
# ---------------------------------------------------------------------------


def test_m6_1_a_certainty_claim_is_rejected():
    result = _facts("C", 7)
    for rogue in (
        "Guaranteed: 7 marla in Block C for PKR 7,900,000.",
        "Definitely 7 marla in Block C.",
        "The price is confirmed at PKR 7,900,000.",
        "We can confirm 7 marla in Block C.",
    ):
        report = reply_guard.guard_reply(
            rogue, result["facts"], filters=result["filters"]
        )
        assert report.ok is False, rogue
        assert any(
            v["code"] in ("certainty", "sold_price_claim")
            for v in report.violations
        ), report.violations

def test_m6_1_a_sold_price_claim_is_rejected():
    result = _facts("C", 7)
    report = reply_guard.guard_reply(
        "The confirmed sold price in Block C is PKR 7,900,000.",
        result["facts"], filters=result["filters"],
    )
    assert report.ok is False
    assert any(v["code"] == "sold_price_claim" for v in report.violations)


def test_m6_1_the_products_own_sold_price_disclaimer_is_not_a_claim():
    """The negative form must not trip the sold-price rule."""
    result = _facts("C", 7)
    report = reply_guard.guard_reply(
        "These are dealer asking prices, not confirmed sold prices. "
        "Human approval is required before sending.",
        result["facts"], filters=result["filters"],
    )
    assert not any(
        v["code"] == "sold_price_claim" for v in report.violations
    ), report.violations


# ---------------------------------------------------------------------------
# Availability
# ---------------------------------------------------------------------------


def test_m6_1_a_stock_claim_about_the_requested_cell_is_rejected():
    """The master is a partial snapshot of asking prices, not an
    availability feed."""
    result = _facts("C", 7)
    for rogue in (
        "We have 7 marla plots available in Block C.",
        "There are 7 marla plots in Block C for sale.",
        "We have 7 marla plots in stock in Block C.",
    ):
        report = reply_guard.guard_reply(
            rogue, result["facts"], filters=result["filters"]
        )
        assert report.ok is False, rogue
        assert any(
            v["code"] == "unsupported_availability" for v in report.violations
        ), report.violations


def test_m6_1_a_stock_claim_about_the_closest_match_cell_is_permitted():
    """Pointing a dealer at a cell the master DOES support is the
    product's explicit purpose (handoff v2 section 7.4 / FH-02 R17)."""
    result = _facts("B", 7)
    assert result["facts"]["answerable_for_demo"] is False
    closest = result["facts"]["closest_match"]
    assert closest is not None

    report = reply_guard.guard_reply(
        "There are %g marla plots available in Block %s."
        % (closest["size_marla"], closest["block"]),
        result["facts"], filters=result["filters"],
    )
    assert not any(
        v["code"] == "unsupported_availability" for v in report.violations
    ), report.violations


# ---------------------------------------------------------------------------
# Provenance
# ---------------------------------------------------------------------------


def test_m6_1_an_answerable_reply_that_drops_the_asking_price_marker_is_rejected():
    result = _facts("C", 7)
    report = reply_guard.guard_reply(
        "The range is PKR 6,000,000 to PKR 11,500,000, median PKR "
        "7,900,000. These are not confirmed sold prices. Human approval "
        "is required before sending.",
        result["facts"], filters=result["filters"],
    )
    assert report.ok is False
    assert any(v["code"] == "provenance_lost" for v in report.violations)


def test_m6_1_an_answerable_reply_that_drops_the_sold_price_disclaimer_is_rejected():
    result = _facts("C", 7)
    report = reply_guard.guard_reply(
        "Based on 21 matching listings, the asking-price range is PKR "
        "6,000,000 to PKR 11,500,000, with a median of PKR 7,900,000. "
        "Human approval is required before sending.",
        result["facts"], filters=result["filters"],
    )
    assert report.ok is False
    assert any(v["code"] == "provenance_lost" for v in report.violations)


def test_m6_1_an_answerable_reply_that_drops_the_approval_marker_is_rejected():
    result = _facts("C", 7)
    report = reply_guard.guard_reply(
        "Based on 21 matching listings, the asking-price range is PKR "
        "6,000,000 to PKR 11,500,000, with a median of PKR 7,900,000. "
        "These are dealer asking prices, not confirmed sold prices.",
        result["facts"], filters=result["filters"],
    )
    assert report.ok is False
    assert any(v["code"] == "provenance_lost" for v in report.violations)


def test_m6_1_a_fact_set_without_approved_provenance_is_rejected():
    """Provenance must survive from fact generation to final response."""
    result = _facts("C", 7)
    facts = dict(result["facts"])
    facts["facts_source"] = "somewhere else"
    report = reply_guard.guard_reply(
        result["reply"], facts, filters=result["filters"]
    )
    assert report.ok is False
    assert any(v["code"] == "provenance_lost" for v in report.violations)


# ---------------------------------------------------------------------------
# Refusal / insufficient-data semantics cannot be weakened
# ---------------------------------------------------------------------------


def test_m6_1_a_thin_reply_that_answers_is_rejected():
    """A reply must not turn "insufficient data" into a confident answer."""
    result = _facts("B", 7)
    for rogue in (
        "Yes, we have 7 marla plots in Block B.",
        "PKR 7,750,000 for 7 marla in Block B.",
    ):
        report = reply_guard.guard_reply(
            rogue, result["facts"], filters=result["filters"]
        )
        assert report.ok is False, rogue


def test_m6_1_a_thin_reply_that_drops_the_hand_off_is_rejected():
    """A reply that says nothing about a human must be refused.

    The reply names the SAME cell the evidence covers, so the only
    thing wrong with it is the missing hand-off: it states the cell's
    count and stops there.
    """
    result = _facts("B", 7)
    report = reply_guard.guard_reply(
        "Block B has 2 listings at 7 marla.",
        result["facts"], filters=result["filters"],
    )
    assert report.ok is False
    assert any(v["code"] == "deferral_lost" for v in report.violations)


def test_m6_1_a_thin_reply_that_keeps_the_hand_off_is_accepted():
    """The other side of the same rule: a correct deferral passes.

    A refusal in the customer's own words is still a refusal, so the
    guard accepts it without demanding the application's exact
    wording.
    """
    result = _facts("B", 7)
    report = reply_guard.guard_reply(
        "I am not able to quote a price for 7 marla in Block B.",
        result["facts"], filters=result["filters"],
    )
    assert report.ok is True, report.violations

    report = reply_guard.guard_reply(
        "I need to confirm the current market information with our team "
        "before giving you a price for 7 marla in Block B.",
        result["facts"], filters=result["filters"],
    )
    assert report.ok is True, report.violations


def test_m6_1_a_hold_reply_must_keep_the_hand_off():
    report = reply_guard.guard_reply(
        "Thank you for your message. A member of our team will review it "
        "and reply personally.",
        None, action="escalate",
    )
    assert report.ok is True
    assert report.state == reply_guard.STATE_HOLD

    report = reply_guard.guard_reply(
        "We have plenty of 7 marla plots in Block C available right now.",
        None, action="escalate",
    )
    assert report.ok is False


# ---------------------------------------------------------------------------
# End to end: the model port cannot smuggle a claim past the guard
# ---------------------------------------------------------------------------


def test_m6_1_a_model_reply_with_an_unsupported_claim_is_blocked():
    """The port is not a trust boundary for claims either."""
    import app.pipeline as pipeline

    os.environ["CUSTOMER_MODEL"] = "mock"
    os.environ["ENABLE_LLM_REPLY"] = "1"

    original = pipeline._customer_model.phrase_reply

    def rogue(*args, **kwargs):
        outcome = original(*args, **kwargs)
        outcome = dict(outcome)
        # Every number in this reply is permitted by the M5 validator
        # (7 is the requested size, 10 rides in on the observation date
        # 2026-10-07), so only the CLAIM guard can catch it.
        outcome["reply"] = (
            "Yes! We have 7 marla plots in Block C available right now, "
            "and we also have 10 marla plots in Block C."
        )
        outcome["reply_source"] = "deterministic_mock"
        return outcome

    pipeline._customer_model.phrase_reply = rogue
    try:
        result = handle_message("What is the price of a 7 marla plot in Block C?")
    finally:
        pipeline._customer_model.phrase_reply = original

    # The numeric validator passed this reply - the claim guard caught it.
    assert result.get("traceability_ok") is True
    assert result.get("claim_guard_blocked") is True
    assert result.get("claim_guard_ok") is False
    assert "available" not in (result.get("draft_reply") or "").lower()
    assert result.get("market_facts") is None
    assert result.get("needs_human") is True
    assert result["decision"]["action"] == "escalate"
    assert "unsupported_claim_in_draft" in result["decision"]["reasons"]


def test_m6_1_a_blocked_claim_is_indistinguishable_to_the_customer():
    """A blocked claim reads exactly like a blocked number."""
    import app.pipeline as pipeline

    os.environ["CUSTOMER_MODEL"] = "mock"
    os.environ["ENABLE_LLM_REPLY"] = "1"

    original = pipeline._customer_model.phrase_reply

    def rogue(*args, **kwargs):
        outcome = original(*args, **kwargs)
        outcome = dict(outcome)
        outcome["reply"] = "Yes, we have 7 marla plots in Block C available."
        return outcome

    pipeline._customer_model.phrase_reply = rogue
    try:
        result = handle_message("What is the price of a 7 marla plot in Block C?")
    finally:
        pipeline._customer_model.phrase_reply = original

    reply = result.get("draft_reply") or ""
    assert "member of our team" in reply.lower()
    assert "PKR" not in reply
    assert result.get("market_facts") is None


def test_m6_1_the_guard_does_not_touch_the_default_wording():
    """The default path's behaviour must be unchanged by M6.1.

    M13: the conversational property-options layer APPENDS its section
    to the default wording, so the default reply is now the FIRST LINE
    of the draft. The assertion checks that prefix - the point of this
    test is that the guard does not alter a compliant default reply,
    which the prefix check still proves.
    """
    expected = price_lookup.lookup_price(block="C", size_marla=7)["reply"]
    result = handle_message("What is the price of a 7 marla plot in Block C?")
    reply = result.get("draft_reply") or ""
    assert reply.split("\n")[0] == expected
    assert result.get("claim_guard_ok") is True


def test_m6_1_the_shipped_mock_keeps_the_provenance_markers():
    """The mock is the stand-in for a hosted model. It must not drop a
    disclaimer - that is the exact failure the guard exists to catch."""
    os.environ["CUSTOMER_MODEL"] = "mock"
    os.environ["ENABLE_LLM_REPLY"] = "1"

    for block, size_marla in ANSWERABLE:
        result = handle_message(
            "What is the price of a %s marla plot in Block %s?"
            % (size_marla, block)
        )
        assert result.get("claim_guard_ok") is True, (
            (block, size_marla), result.get("claim_guard")
        )


def test_m6_1_the_http_prompt_forbids_dropping_a_disclaimer():
    """A real model is told to keep the disclaimers."""
    prompt = customer_model.HTTP_PROMPT.lower()
    assert "disclaimer" in prompt
    assert "never say a plot is available" in prompt


# ---------------------------------------------------------------------------
# The report is safe to serve
# ---------------------------------------------------------------------------


def test_m6_1_the_guard_report_never_quotes_an_unsupported_number():
    """The report describes the violation without echoing the value.

    A violation's value is a size or a block the permitted set does not
    contain, so quoting it would put an untraceable number on a serving
    surface - the D-32 hole.
    """
    result = _facts("C", 7)
    report = reply_guard.guard_reply(
        "We also have 10 marla plots in Block C.",
        result["facts"], filters=result["filters"],
    )
    assert report.ok is False
    blob = json.dumps(report.to_dict())
    assert "10" not in blob, blob


def test_m6_1_the_guard_never_returns_a_numbered_field():
    from market.fact_validator import extract_numbers

    result = _facts("C", 7)
    report = reply_guard.guard_reply(
        "We also have 10 marla plots in Block C.",
        result["facts"], filters=result["filters"],
    )
    assert extract_numbers(json.dumps(report.to_dict())) == []


# ---------------------------------------------------------------------------
# Structure
# ---------------------------------------------------------------------------


def test_m6_1_the_guard_reads_the_single_scope_configuration():
    """The scope lives in one place (D-26)."""
    policies = price_lookup.load_policies()
    manifest = reply_guard.build_claim_manifest(
        facts=_facts("C", 7)["facts"],
        filters={"block": "C", "size_marla": 7},
    )
    assert manifest["scope_blocks"] == set(policies["active_blocks"])


def test_m6_1_the_state_is_derived_from_the_facts_not_the_reply():
    """A reply cannot declare itself answerable."""
    manifest = reply_guard.build_claim_manifest(
        facts=_facts("B", 7)["facts"],
        filters={"block": "B", "size_marla": 7},
        reply_mode="insufficient_data",
    )
    assert manifest["state"] == reply_guard.STATE_INSUFFICIENT
    assert manifest["answerable"] is False


def test_m6_1_the_control_modules_do_not_know_about_the_guard():
    """The guard is a NEW final gate; it must not be entangled with the
    lookup, the policy or the numeric validator."""
    for module in ("market/price_lookup.py", "market/fact_validator.py",
                   "app/policy.py"):
        source = io.open(
            os.path.join(PROJECT_ROOT, module), encoding="utf-8"
        ).read()
        assert "reply_guard" not in source, module


def test_m6_1_the_guard_is_stdlib_only_and_does_no_io():
    """RULES_SHORT #5: stdlib only, no model, no network."""
    source = io.open(
        os.path.join(PROJECT_ROOT, "market", "reply_guard.py"),
        encoding="utf-8",
    ).read()
    for forbidden in ("import requests", "import httpx", "urllib",
                      "open(", "subprocess", "socket"):
        assert forbidden not in source, forbidden
