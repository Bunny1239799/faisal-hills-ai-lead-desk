"""M9 - the qualification layer as the product actually uses it.

The unit tests in ``test_m9_qualify.py`` cover the rules. This module
covers the WIRING: the pipeline, the API, the conversation state, and
the model port.

The properties that matter here:

  * the pipeline's reply agrees with the decision the application made;
  * a requirement stated over several messages is used;
  * a requirement never leaks between conversations;
  * a model may word the reply but may not supply a requirement, a
    price or a property;
  * the M5 and M6.1 gates still hold on every M9 reply;
  * the M7 privacy boundary is intact on the M9 surface.
"""

from __future__ import annotations

import os
import sqlite3
import sys

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from app import pipeline as _pipeline  # noqa: E402
from market import decision as _decision  # noqa: E402
from market import fact_guard  # noqa: E402
from market import qualify as _qualify  # noqa: E402
from market import reply_guard  # noqa: E402


# ---------------------------------------------------------------------------
# The pipeline
# ---------------------------------------------------------------------------


class TestM9Pipeline:

    def test_an_exact_match_reports_the_quote_action(self):
        result = _pipeline.handle_message(
            "What is the price of a 7 marla plot in Block C?")
        action = result.get("next_best_action") or {}
        assert action.get("action") == _decision.ACTION_QUOTE
        assert action.get("requires_human_approval") is True

    def test_a_thin_cell_reports_the_alternatives_action(self):
        result = _pipeline.handle_message(
            "What is the price of a 10 marla plot in Block C?")
        action = result.get("next_best_action") or {}
        assert action.get("action") == _decision.ACTION_OFFER

    def test_the_stated_requirements_are_reported(self):
        result = _pipeline.handle_message(
            "What is the price of a 10 marla plot in Block C? "
            "My budget is 6 million.")
        stated = result.get("requirements_stated") or {}
        assert stated.get("budget_max_pkr") == 6_000_000.0
        assert stated.get("size_marla") == 10.0

    def test_a_budget_narrows_the_alternatives_the_reply_may_name(self):
        # C/7 starts at 6,000,000; B/10 starts at 9,300,000. A 6M
        # budget rules B/10 and A/10 out.
        result = _pipeline.handle_message(
            "What is the price of a 10 marla plot in Block C? "
            "My budget is 6 million.")
        alternatives = result.get("verified_alternatives") or []
        named = [(a["block"], a["size_marla"]) for a in alternatives]
        assert ("B", 10.0) not in named
        assert ("A", 10.0) not in named
        assert ("C", 7.0) in named

    def test_a_preferred_block_ranks_the_alternatives(self):
        # The M2 filter extractor treats a named block as THE block, so
        # "I prefer Block B" makes the lookup price B/10 - an exact,
        # answerable match - and there is nothing to rank. The M9
        # ranking is exercised on the cells that remain alternatives,
        # so the request here names a size with no answerable cell.
        result = _pipeline.handle_message(
            "What is the price of a 10 marla plot in Block C?")
        alternatives = result.get("verified_alternatives") or []
        assert alternatives
        # The block preference re-ranks without removing.
        decision = _decision.decide(
            {"options": alternatives, "exact_match": None,
             "thin_cells": []},
            _qualify.extract_requirements("I prefer Block B"),
        )
        assert decision["options"][0]["block"] == "B"
        assert len(decision["options"]) == len(alternatives)

    def test_a_budget_that_excludes_everything_asks_a_question(self):
        result = _pipeline.handle_message(
            "What is the rate of 10 marla in Block C? Budget 5 million.")
        action = result.get("next_best_action") or {}
        assert action.get("action") == _decision.ACTION_CLARIFY
        reply = result.get("draft_reply") or ""
        assert "budget" in reply.lower()

    def test_the_clarifying_reply_does_not_offer_the_options_it_excludes(self):
        # D-58/D-59: the question must REPLACE the alternatives, not
        # sit in front of them. A question followed by the very options
        # it was meant to narrow is not a question.
        result = _pipeline.handle_message(
            "What is the rate of 10 marla in Block C? Budget 5 million.")
        reply = result.get("draft_reply") or ""
        assert "Other verified alternatives" not in reply
        assert "Block B" not in reply
        assert "Block A" not in reply

    def test_a_clarifying_reply_still_keeps_the_hand_off(self):
        result = _pipeline.handle_message(
            "What is the rate of 10 marla in Block C? Budget 5 million.")
        reply = result.get("draft_reply") or ""
        assert "our team" in reply
        assert "Human approval" in reply

    def test_the_clarifying_reply_passes_both_final_gates(self):
        result = _pipeline.handle_message(
            "What is the rate of 10 marla in Block C? Budget 5 million.")
        assert result.get("traceability_ok") is True
        assert result.get("traceability_blocked") is not True
        guard = result.get("claim_guard") or {}
        assert guard.get("ok") is True

    def test_a_thin_cell_is_never_quoted(self):
        result = _pipeline.handle_message(
            "What is the price of a 10 marla plot in Block C?")
        reply = result.get("draft_reply") or ""
        # The C/10 cell has 2 listings - below the threshold - so no
        # price for it may appear.
        assert "PKR" not in reply
        assert result.get("market_answerable") is False

    def test_an_escalated_message_never_reaches_the_market_layer(self):
        result = _pipeline.handle_message(
            "What is the price of a 7 marla plot in Block C? "
            "Is the title clear and is the NOC ready?")
        assert result.get("needs_human") is True
        assert result.get("market_facts") is None

    def test_the_internal_m9_keys_never_reach_the_result(self):
        result = _pipeline.handle_message(
            "What is the price of a 10 marla plot in Block C?")
        assert "_fh_m9_decision" not in result
        assert "_fh_market_facts" not in result
        assert "_fh_market_filters" not in result
        assert "_fh_reply_changed" not in result


# ---------------------------------------------------------------------------
# The narrowing-only invariant, across the whole surface
# ---------------------------------------------------------------------------


class TestM9NarrowingOnlyInvariant:
    """Qualification can remove and re-rank. It can never add.

    This is checked over every request the master supports, with every
    combination of requirements the product recognises - so the
    invariant is measured, not asserted.
    """

    def _all_requests(self):
        for block in ("A", "B", "C"):
            for size in (5, 7, 10, 14, 20, 40):
                yield block, size

    def test_qualification_never_adds_an_option(self):
        from market import recommend as _recommend

        requirements = [
            _qualify.empty_requirements(),
            _qualify.empty_requirements(budget_max_pkr=6_000_000.0),
            _qualify.empty_requirements(budget_min_pkr=12_000_000.0),
            _qualify.empty_requirements(budget_min_pkr=5_000_000.0,
                           budget_max_pkr=20_000_000.0),
            _qualify.empty_requirements(block="A"),
            _qualify.empty_requirements(block="B"),
            _qualify.empty_requirements(size_marla=5.0),
            _qualify.empty_requirements(size_marla=10.0),
            _qualify.empty_requirements(purpose="commercial"),
            _qualify.empty_requirements(purpose="investment"),
            _qualify.empty_requirements(timeline="immediate"),
            _qualify.empty_requirements(budget_max_pkr=6_000_000.0, block="A",
                           size_marla=5.0, purpose="investment",
                           timeline="three_months"),
        ]

        checked = 0
        for block, size in self._all_requests():
            try:
                rec = _recommend.build_recommendations(
                    block=block, size_marla=size, include_listings=False)
            except Exception:
                continue
            original = [
                (o["block"], o["size_marla"]) for o in rec.get("options") or []
            ]
            for reqs in requirements:
                res = _qualify.apply_requirements(
                    rec.get("options") or [], reqs)
                kept = [(o["block"], o["size_marla"])
                        for o in res["options"]]
                # A SUBSET: nothing new, nothing duplicated.
                assert set(kept) <= set(original), (block, size, reqs)
                assert len(kept) == len(set(kept)), (block, size, reqs)
                checked += 1
        assert checked > 100, "the invariant was barely tested"

    def test_the_decision_never_offers_a_cell_the_recommendation_did_not(self):
        from market import recommend as _recommend

        for block, size in self._all_requests():
            try:
                rec = _recommend.build_recommendations(
                    block=block, size_marla=size, include_listings=False)
            except Exception:
                continue
            known = {(o["block"], o["size_marla"])
                     for o in rec.get("options") or []}
            if rec.get("exact_match"):
                known.add((rec["exact_match"]["block"],
                           rec["exact_match"]["size_marla"]))
            for reqs in (
                _qualify.empty_requirements(),
                _qualify.empty_requirements(budget_max_pkr=8_000_000.0),
                _qualify.empty_requirements(block="A", size_marla=5.0),
            ):
                out = _decision.decide(rec, reqs)
                for option in out["options"]:
                    assert (option["block"], option["size_marla"]) in known

    def test_no_qualified_option_is_below_the_evidence_threshold(self):
        from market import recommend as _recommend

        for block, size in self._all_requests():
            try:
                rec = _recommend.build_recommendations(
                    block=block, size_marla=size, include_listings=False)
            except Exception:
                continue
            thin = {(c["block"], c["size_marla"])
                    for c in rec.get("thin_cells") or []}
            for reqs in (
                _qualify.empty_requirements(),
                _qualify.empty_requirements(budget_max_pkr=30_000_000.0),
                _qualify.empty_requirements(block="C"),
            ):
                out = _decision.decide(rec, reqs)
                for option in out["options"]:
                    assert (option["block"], option["size_marla"]) not in thin


# ---------------------------------------------------------------------------
# The conversation: requirements across messages
# ---------------------------------------------------------------------------


class TestM9ConversationState:

    def test_a_requirement_stated_in_an_earlier_message_is_used(self):
        lead = "m9-conv-1"
        first = _pipeline.handle_message(
            "What is the price of a 10 marla plot in Block C? "
            "My budget is 6 million.",
            lead_id=lead,
        )
        # The budget is in the FIRST message.
        stated = first.get("requirements_stated") or {}
        assert stated.get("budget_max_pkr") == 6_000_000.0

    def test_the_conversation_state_is_read_from_the_stored_messages(self):
        lead = "m9-conv-2"
        _pipeline.handle_message(
            "What is the price of a 10 marla plot in Block C? "
            "My budget is 6 million.",
            lead_id=lead,
        )
        # A SECOND message, with no budget of its own, must still know
        # the budget from the first one. It has to be a market price
        # question, because the M9 layer only runs on that path.
        second = _pipeline.handle_message(
            "What is the price of a 7 marla plot in Block C?",
            lead_id=lead,
        )
        stated = second.get("requirements_stated") or {}
        assert stated.get("budget_max_pkr") == 6_000_000.0

    def test_a_requirement_never_leaks_between_conversations(self):
        _pipeline.handle_message(
            "What is the price of a 10 marla plot in Block C? "
            "My budget is 6 million.",
            lead_id="m9-conv-3",
        )
        other = _pipeline.handle_message(
            "What is the price of a 10 marla plot in Block C?",
            lead_id="m9-conv-4",
        )
        stated = other.get("requirements_stated") or {}
        assert stated.get("budget_max_pkr") is None

    def test_a_new_requirement_replaces_the_old_one(self):
        lead = "m9-conv-5"
        _pipeline.handle_message(
            "What is the price of a 10 marla plot in Block C? "
            "My budget is 6 million.",
            lead_id=lead,
        )
        second = _pipeline.handle_message(
            "What is the price of a 10 marla plot in Block C? "
            "Actually my budget is 15 million.",
            lead_id=lead,
        )
        stated = second.get("requirements_stated") or {}
        assert stated.get("budget_max_pkr") == 15_000_000.0


# ---------------------------------------------------------------------------
# The model port
# ---------------------------------------------------------------------------


class TestM9ModelBoundary:
    """The model may word the reply. It may not supply a fact."""

    def test_the_port_never_receives_a_requirement(self):
        from app import customer_model

        facts = {
            "facts_source": reply_guard.APPROVED_SOURCE,
            "answerable_for_demo": False,
            "verified_alternatives": [
                {"block": "B", "size_marla": 10.0, "verified": True},
            ],
        }
        view = customer_model.build_model_facts(facts)
        for key in ("budget_min_pkr", "budget_max_pkr", "purpose",
                    "timeline", "requirements"):
            assert key not in view

    def test_the_port_only_sees_verified_alternatives(self):
        from app import customer_model

        facts = {
            "facts_source": reply_guard.APPROVED_SOURCE,
            "answerable_for_demo": False,
            "verified_alternatives": [
                {"block": "B", "size_marla": 10.0, "verified": True},
                # NOT verified - the port must not see it.
                {"block": "A", "size_marla": 10.0, "verified": False},
            ],
        }
        view = customer_model.build_model_facts(facts)
        assert view["verified_alternatives"] == [
            {"block": "B", "size_marla": 10.0},
        ]

    def test_a_model_requirement_must_pass_the_gate_before_it_is_used(self):
        # The gate is the ONLY path a model-generated requirement takes.
        invented = {"budget_max_pkr": 99_000_000.0, "source": "model"}
        validated = _qualify.validate_requirement(
            invented, "5 marla in Block A")
        assert validated == {}

    def test_a_model_cannot_widen_the_option_set(self):
        from market import recommend as _recommend

        rec = _recommend.build_recommendations(
            block="C", size_marla=10, include_listings=False)
        before = len(rec["options"])

        # A model proposes a cell the dealer did NOT name. The block is
        # confirmed only because the dealer named Block A; the SIZE is
        # dropped, because the dealer said 5 marla and the model said 14.
        invented = _qualify.validate_requirement(
            {"block": "A", "size_marla": 14.0, "source": "model"},
            "5 marla in Block A")
        assert "size_marla" not in invented

        # Even a CONFIRMED block cannot add an option: the narrowing
        # returns a subset of what it was given.
        res = _qualify.apply_requirements(rec["options"], invented)
        assert len(res["options"]) <= before
        assert ("A", 14.0) not in [
            (o["block"], o["size_marla"]) for o in res["options"]]

    def test_a_model_cannot_add_a_cell_the_dealer_never_named(self):
        # A block the dealer did not name is dropped outright.
        invented = _qualify.validate_requirement(
            {"block": "A", "source": "model"},
            "5 marla in Block C")
        assert invented == {}

    def test_the_model_cannot_add_a_price_to_the_fact_set(self):
        from app import customer_model

        facts = {
            "facts_source": reply_guard.APPROVED_SOURCE,
            "answerable_for_demo": False,
            "verified_alternatives": [
                {"block": "B", "size_marla": 10.0, "verified": True,
                 "price_pkr": 12_400_000.0},
            ],
        }
        view = customer_model.build_model_facts(facts)
        # Only the block and the size travel.
        assert set(view["verified_alternatives"][0]) == {"block", "size_marla"}


# ---------------------------------------------------------------------------
# The API surface
# ---------------------------------------------------------------------------


class TestM9ApiSurface:

    def test_the_route_reports_the_decision(self):
        import app.server as server

        body = server.next_best_action_endpoint(block="C", size_marla=10)
        assert body["action"] == _decision.ACTION_OFFER
        assert body["requires_human_approval"] is True
        assert body["availability_claimed"] is False

    def test_the_route_reports_the_stated_and_the_unknown(self):
        import app.server as server

        body = server.next_best_action_endpoint(
            block="C", size_marla=10, message="My budget is 6 million.")
        assert body["requirements_stated"]["budget_max_pkr"] == 6_000_000.0
        # The unstated ones are reported as unknown, not guessed.
        assert "purpose" in body["requirements_unknown"]
        assert "timeline" in body["requirements_unknown"]
        assert "purpose" not in body["requirements_stated"]

    def test_the_route_never_carries_a_price(self):
        import app.server as server

        body = server.next_best_action_endpoint(block="C", size_marla=10)
        import json
        text = json.dumps(body, default=str)
        assert "price_min_pkr" not in text
        assert "price_median_pkr" not in text
        assert "price_max_pkr" not in text

    def test_a_parked_block_is_refused(self):
        import app.server as server
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            server.next_best_action_endpoint(block="D", size_marla=10)
        assert exc.value.status_code == 400

    def test_the_route_serves_no_dealer_content(self):
        import app.server as server

        body = server.next_best_action_endpoint(
            block="C", size_marla=10,
            message="I am Ali from Lahore, 03001234567, budget 6 million.")
        import json
        text = json.dumps(body, default=str)
        assert "Ali" not in text
        assert "03001234567" not in text
        assert "Lahore" not in text

    def test_the_route_serves_only_cells_the_application_verified(self):
        import app.server as server

        body = server.next_best_action_endpoint(block="C", size_marla=10)
        for option in body["options"]:
            assert option["block"] in ("A", "B", "C")
        # The thin cell is reported as a gap, never as an option.
        thin = {(c["block"], c["size_marla"]) for c in body["thin_cells"]}
        offered = {(o["block"], o["size_marla"]) for o in body["options"]}
        assert not (thin & offered)
