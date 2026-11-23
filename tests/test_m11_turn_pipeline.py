"""M11.3 - the turn pipeline.

What the tests prove:

* the turn reaches the **application's** decision layer - the pipeline
  adds no decision of its own;
* the four routes are **read** from the M9 decision, never computed by
  a new rule;
* the reply is the application's own validated reply, and both final
  gates still ran;
* the requirements **accumulate** across turns, and a correction is
  recorded;
* no live model call is made;
* the unmet-demand record carries a size, a block and a budget band -
  and nothing else.
"""

from __future__ import annotations

import os
import sys
import uuid
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.turn_pipeline import (
    ROUTE_ALTERNATIVE,
    ROUTE_CLARIFY,
    ROUTE_ESCALATE,
    ROUTE_EXACT,
    run_turn,
)
from market.lead_state import LeadStateStore
from market.unmet_demand import UnmetDemandStore


@pytest.fixture()
def stores():
    """A temporary lead-state store and a temporary demand log."""
    with tempfile.TemporaryDirectory() as tmp:
        yield (LeadStateStore(os.path.join(tmp, "state.db")),
               UnmetDemandStore(os.path.join(tmp, "demand.db")))


def _turn(stores, message, session=None):
    """Run one turn in a FRESH session.

    The application's own conversation state lives in the lead's messages,
    so every test needs its own session id - otherwise one test's
    conversation would answer the next test's question.
    """
    state_store, demand_store = stores
    if session is None:
        session = "sess-%s" % uuid.uuid4().hex
    return run_turn(message, session, store=state_store,
                     demand_store=demand_store)


class TestTheRoutes:
    def test_an_exact_cell_routes_to_exact(self, stores):
        result = _turn(stores, "7 marla in Block C")
        assert result["route"] == ROUTE_EXACT
        assert result["escalation"] is False
        assert "PKR" in result["reply"]

    def test_a_thin_cell_routes_to_alternative(self, stores):
        """B/7 has 2 listings: no price, but a verified alternative."""
        result = _turn(stores, "7 marla in Block B")
        assert result["route"] == ROUTE_ALTERNATIVE
        assert result["verified_options"]

    def test_a_parked_block_routes_to_escalate(self, stores):
        result = _turn(stores, "5 marla in Block D")
        assert result["route"] == ROUTE_ESCALATE
        assert result["escalation"] is True
        assert "PKR" not in result["reply"]

    def test_a_discount_request_routes_to_escalate(self, stores):
        result = _turn(stores, "give me 20% off a 7 marla plot in Block C")
        assert result["route"] == ROUTE_ESCALATE
        assert "PKR" not in result["reply"]

    def test_a_turn_with_nothing_stated_routes_to_clarify(self, stores):
        result = _turn(stores, "I need a plot")
        assert result["route"] == ROUTE_CLARIFY
        assert result["lead_state"]["fields"]["size"]["status"] == "unknown"

    def test_every_route_is_reachable(self, stores):
        routes = set()
        for message, session in (
            ("7 marla in Block C", "r1"),
            ("7 marla in Block B", "r2"),
            ("I need a plot", "r3"),
            ("5 marla in Block D", "r4"),
        ):
            routes.add(_turn(stores, message, session)["route"])
        assert routes == {ROUTE_EXACT, ROUTE_ALTERNATIVE, ROUTE_CLARIFY,
                          ROUTE_ESCALATE}


class TestTheDecisionIsTheApplications:
    def test_the_route_is_read_from_the_m9_decision(self, stores, monkeypatch):
        """The pipeline does not decide: it reads the application's action."""
        import app.turn_pipeline as turn_pipeline

        result = _turn(stores, "7 marla in Block C")
        assert result["route"] == ROUTE_EXACT
        assert result["next_action"]["action"] == "quote_exact_match"
        assert turn_pipeline._ACTION_ROUTES["quote_exact_match"] == ROUTE_EXACT

    def test_the_reason_is_the_applications_own(self, stores):
        result = _turn(stores, "7 marla in Block C")
        assert result["reason"]
        assert result["next_action"]["reason"] == result["reason"]

    def test_the_gates_ran(self, stores):
        result = _turn(stores, "7 marla in Block C")
        assert result["gates"]["traceability_ok"] is True
        assert result["gates"]["claim_guard_ok"] is True

    def test_no_live_model_call_is_made(self, stores, monkeypatch):
        """The reply is the deterministic template reply."""
        import app.customer_model as customer_model

        def _boom(*args, **kwargs):  # pragma: no cover - must not run
            raise AssertionError("the M11 turn pipeline must not call a model")

        monkeypatch.setattr(customer_model, "generate_customer_reply", _boom,
                            raising=False)
        result = _turn(stores, "7 marla in Block C")
        assert result["reply"]
        assert result["normalized"]["text"] == "7 marla in Block C"


class TestTheStateAccumulates:
    def test_the_requirements_accumulate_across_turns(self, stores):
        session = "acc-1"
        _turn(stores, "5 marla", session)
        result = _turn(stores, "Block C", session)
        fields = result["lead_state"]["fields"]
        assert fields["size"]["value"] == 5.0
        assert fields["size"]["source_turn"] == 1
        assert fields["block"]["value"] == "C"
        assert fields["block"]["source_turn"] == 2

    def test_a_correction_is_recorded(self, stores):
        session = "corr-1"
        _turn(stores, "my budget is 8 million", session)
        result = _turn(stores, "actually my budget is 12 million", session)
        budget = result["lead_state"]["fields"]["budget"]
        assert budget["value"] == {"min_pkr": 12000000, "max_pkr": 12000000}
        assert budget["status"] == "corrected"
        assert budget["source_turn"] == 2
        assert result["changes"][0]["field"] == "budget"
        assert result["changes"][0]["old"] == {
            "min_pkr": 8000000, "max_pkr": 8000000}

    def test_the_turn_number_advances(self, stores):
        session = "turn-1"
        assert _turn(stores, "5 marla", session)["turn"] == 1
        assert _turn(stores, "Block C", session)["turn"] == 2

    def test_the_state_survives_a_new_store_on_the_same_file(self, stores):
        state_store, demand_store = stores
        run_turn("5 marla", "s1", store=state_store,
                 demand_store=demand_store)
        reopened = LeadStateStore(state_store.path)
        assert reopened.load("s1").value("size") == 5.0

    def test_an_unknown_field_stays_unknown(self, stores):
        result = _turn(stores, "5 marla in Block C")
        assert result["lead_state"]["fields"]["purpose"]["status"] == "unknown"
        assert result["lead_state"]["fields"]["timeline"]["status"] == "unknown"


class TestTheNormalizerRunsFirst:
    def test_a_dimension_name_is_normalized_before_the_turn(self, stores):
        result = _turn(stores, "30x60 plot in Block C")
        assert result["lead_state"]["fields"]["size"]["value"] == 7.0

    def test_a_roman_urdu_amount_is_normalized_before_the_turn(self, stores):
        result = _turn(stores, "5 marla block c, budget 80 lakh")
        assert result["lead_state"]["fields"]["budget"]["value"] == {
            "min_pkr": 8000000, "max_pkr": 8000000}


class TestTheUnmetDemand:
    def test_a_thin_cell_records_the_demand_shape(self, stores):
        result = _turn(stores, "7 marla in Block B")
        assert result["unmet_demand"] == {
            "size_marla": 7.0,
            "block": "B",
            "budget_band": None,
            "route": ROUTE_ALTERNATIVE,
        }

    def test_an_exact_answer_records_no_demand(self, stores):
        result = _turn(stores, "7 marla in Block C")
        assert result["unmet_demand"] is None

    def test_a_turn_with_nothing_stated_records_no_demand(self, stores):
        result = _turn(stores, "I need a plot")
        assert result["unmet_demand"] is None

    def test_the_budget_is_recorded_as_a_band_not_a_figure(self, stores):
        """C/7 starts at 6.0M, so a 5 million budget excludes the cell."""
        result = _turn(stores, "7 marla in Block C, budget 5 million")
        assert result["route"] == ROUTE_ALTERNATIVE
        assert result["unmet_demand"]["budget_band"] == "5M-10M"
        assert "5000000" not in str(result["unmet_demand"])

    def test_the_record_carries_no_private_data(self, stores):
        result = _turn(stores, "7 marla in Block B, budget 80 lakh")
        record = result["unmet_demand"]
        assert set(record) == {"size_marla", "block", "budget_band", "route"}
        blob = str(record)
        assert "probe" not in blob
        assert "s1" not in blob


class TestTheVerifiedOptions:
    def test_an_exact_answer_names_the_cell_it_priced(self, stores):
        result = _turn(stores, "7 marla in Block C")
        assert len(result["verified_options"]) == 1
        option = result["verified_options"][0]
        assert option["block"] == "C"
        assert option["size_marla"] == 7.0
        assert option["verified"] is True

    def test_the_options_carry_no_price(self, stores):
        result = _turn(stores, "7 marla in Block B")
        for option in result["verified_options"]:
            assert "price" not in option
            assert "PKR" not in str(option)

    def test_an_escalated_turn_names_no_option(self, stores):
        result = _turn(stores, "5 marla in Block D")
        assert result["verified_options"] == []

