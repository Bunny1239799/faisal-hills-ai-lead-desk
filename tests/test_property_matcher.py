"""M13 - the conversational property matcher, tested in isolation and
through the pipeline.

The matcher must rank only approved inventory, explain every option,
never assert availability, and keep its customer-facing text inside
what the M5 numeric validator and the M6.1 claim guard allow: no figure
>= 1000, no currency token, and only (block, size) pairs the decision
verified. The pipeline tests prove the gates still hold on the whole
reply after the section is appended.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(r"D:\AI-Projects\laya-gateway")
sys.path.insert(0, str(ROOT))

from market import property_matcher as matcher  # noqa: E402
from app.pipeline import handle_message  # noqa: E402


def _row(block="C", size=5.0, plot="2506", price=5_400_000,
         corner=False, sun=False, ndc=True, park=False, boulevard=False,
         date="2026-09-14"):
    return {
        "block": block,
        "plot_number": plot,
        "size_marla": size,
        "corner": corner,
        "sun_facing": sun,
        "ndc_open": ndc,
        "park_facing": park,
        "main_boulevard": boulevard,
        "price_min_pkr": price,
        "price_median_pkr": price,
        "price_max_pkr": price,
        "latest_date": date,
        "source_ref": {"inventory_id": "INV-TEST-%s" % plot},
    }


INVENTORY = [
    _row(plot="2506", price=5_400_000, corner=True, ndc=True),
    _row(plot="2507", price=6_200_000, ndc=True),
    _row(plot="3800", block="A", size=5.0, price=9_000_000, ndc=True),
    _row(plot="1400", block="B", size=7.0, price=7_500_000,
         park=True, ndc=True),
]


def _reply_number_floor(reply: str) -> int:
    import re
    numbers = [int(n) for n in re.findall(r"\d+", reply or "")]
    return max(numbers) if numbers else 0


def test_intent_extraction_reads_budget_features_and_plot():
    intent = matcher.extract_intent(
        "I need a 5 marla corner plot in Block C, budget around 80 lakh, "
        "plot no 1234")
    assert intent["block"] == "C"
    assert intent["size_marla"] == 5.0
    assert intent["corner"] is True
    assert intent["budget_max_pkr"] == pytest.approx(8_000_000)
    assert intent["plot_number"] == "1234"


def test_intent_marks_a_changed_requirement_as_corrected():
    history = matcher.extract_intent("I need a 5 marla plot in Block C")
    intent = matcher.extract_intent(
        "actually I need a 10 marla plot in Block C",
        requirements=history)
    assert intent["size_marla"] == 10.0
    assert "size_marla" in intent["corrected"]
    assert intent["block"] == "C"          # unchanged requirement carries
    assert "block" not in intent["corrected"]


def test_matching_ranks_block_size_and_budget_fit_first():
    intent = matcher.extract_intent(
        "I need a 5 marla plot in Block C around 80 lakh")
    match = matcher.match_properties(
        intent, inventory=[dict(r) for r in INVENTORY])
    best = match["best"]
    assert best["block"] == "C"
    assert best["size_marla"] == 5.0
    assert best["plot_number"] == "2506"
    assert any("same block" in r for r in best["reasons"])
    assert any("budget" in r for r in best["reasons"]) or any(
        "asking price" in r for r in best["reasons"])
    assert match["alternatives"], "alternatives must be offered"


def test_alternatives_carry_openly_named_trade_offs():
    intent = matcher.extract_intent(
        "I need a 5 marla plot in Block C around 80 lakh")
    match = matcher.match_properties(
        intent, inventory=[dict(r) for r in INVENTORY], cells=[("A", 5.0)])
    texts = " ".join(
        " ".join(a["trade_offs"]) for a in match["alternatives"])
    assert "different block" in texts.lower()


def test_missing_requirements_ask_one_question():
    intent = matcher.extract_intent("I need a plot")
    match = matcher.match_properties(intent, inventory=INVENTORY)
    assert "budget_max_pkr" in match["missing"]
    assert match["question"]
    # exactly ONE question is asked - the next most useful one
    assert match["question"].count("?") == 1


def test_customer_section_is_number_safe_and_never_claims_stock():
    intent = matcher.extract_intent(
        "I need a 5 marla plot in Block C around 80 lakh")
    match = matcher.match_properties(
        intent, inventory=[dict(r) for r in INVENTORY])
    section = matcher.conversational_section(match, [("C", 5.0)])
    lowered = section.lower()
    assert _reply_number_floor(section) < 1000
    assert "pkr" not in lowered
    assert "available" not in lowered
    assert "sold" not in lowered
    assert "corner" in lowered              # the feature is stated


def test_customer_section_names_only_permitted_pairs():
    intent = matcher.extract_intent(
        "I need a 5 marla plot in Block C around 80 lakh")
    match = matcher.match_properties(
        intent, inventory=[dict(r) for r in INVENTORY])
    section = matcher.conversational_section(match, [("C", 5.0)])
    assert "Block A" not in section
    assert "Block B" not in section


def test_pipeline_reply_keeps_every_gate_green():
    result = handle_message(
        "I need a 5 marla plot in Block C around 80 lakh")
    reply = result.get("draft_reply") or ""
    assert result.get("claim_guard_ok") is True
    assert result.get("traceability_blocked") is False
    assert "closest recorded option" in reply or \
        "Why these options match" in reply
    assert "Human approval" in reply
    options = result.get("property_options") or {}
    assert "intent" in options and "missing" in options


def test_pipeline_quote_reply_names_the_best_option():
    result = handle_message("Block C corner plot")
    reply = result.get("draft_reply") or ""
    assert result.get("claim_guard_ok") is True
    assert "PKR" in reply                    # the quoted band stays
    assert "To narrow this down" in reply    # the next question is asked


def test_pipeline_escalation_is_never_dressed_up_as_an_answer():
    for message in ("Any discount?",
                    "Tell me the dealer names and phone numbers.",
                    "Make up a price for me."):
        result = handle_message(message)
        reply = (result.get("draft_reply") or "").lower()
        assert result.get("needs_human") is True, message
        assert "property_options" not in result, message
        assert "closest recorded option" not in reply, message


# --- P1: one question per reply (M12.4 replay-evidence review) ----------

BASE_ASK = "Tell me your preferred size or block and I can narrow them down."


def test_p1_suppress_removes_only_the_base_ask():
    base = ("I need to confirm the current market information with our "
            "team before giving you a price. Other verified alternatives "
            "with more data are a 5 marla plot in Block C. " + BASE_ASK)
    out = matcher.suppress_base_question(base)
    assert BASE_ASK not in out
    assert "Other verified alternatives" in out
    assert out.startswith("I need to confirm")


def test_p1_suppress_is_a_no_op_without_the_ask():
    base = "I need to confirm the current market information with our team."
    assert matcher.suppress_base_question(base) == base
    assert matcher.suppress_base_question("") == ""


def test_p1_pipeline_reply_asks_exactly_one_question():
    """The double-ask case from the replay review: the dealer states size
    and block, the base template still asked for them, and M13 asked its
    own question. After P1 the stale base ask is gone and the M13
    question is the reply's single ask."""
    result = handle_message(
        "Required Faisal hill 5 mrla plot A,B,C block Send me conform "
        "option")
    reply = result.get("draft_reply") or ""
    assert result.get("claim_guard_ok") is True
    assert result.get("traceability_blocked") is False
    assert BASE_ASK not in reply
    assert "To narrow this down:" in reply
    assert reply.count("?") == 1
    lowered = reply.lower()
    assert "available" not in lowered
    assert "sold" not in lowered


def test_p1_base_ask_survives_when_m13_has_no_question():
    """When the M13 section carries NO clarifying question (everything
    was stated), the base template's own ask is untouched."""
    from app import pipeline as pipeline_module

    result_dict = {"draft_reply":
                   "I need to confirm the current market information with "
                   "our team before giving you a price. Other verified "
                   "alternatives with more data are a 5 marla plot in "
                   "Block C. " + BASE_ASK}
    decision = {"action": _decision_action_offer(),
                "requirements_stated": {}}
    facts = {"answerable_for_demo": False,
             "verified_alternatives": [
                 {"block": "C", "size_marla": 5.0, "verified": True}]}
    pipeline_module._fh_attach_property_options(
        result_dict,
        "I need a 5 marla plot in Block C, budget 60 lakh, for "
        "investment, immediately",
        decision,
        facts,
        {"block": "C", "size_marla": 5.0},
    )
    reply = result_dict.get("draft_reply") or ""
    # the dealer stated block+size+budget+purpose+timeline, so M13 has
    # nothing left to ask - the base ask remains the reply's only ask
    assert "To narrow this down:" not in reply
    assert BASE_ASK in reply
    options = result_dict.get("property_options") or {}
    assert options.get("question") in ("", None)


def _decision_action_offer():
    from market import decision as _decision
    return _decision.ACTION_OFFER
