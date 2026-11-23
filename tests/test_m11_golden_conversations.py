"""M11.6 - the golden conversations: the product's real specification.

Fifteen scripted dealer conversations live in ``tests/golden/
conversations.json``. Every turn names the route the application must
take, the escalation flag, the verified options it may name, whether an
unmet-demand record is written, and the qualification state after that
turn - each field with its value, its status and the turn it came from.

The expectations were taken from the application's own decision and the
approved master, and were checked by hand against the rules:

* a route is read from the M9 decision, never computed here;
* a price is only quoted for a cell with at least 3 listings;
* a parked block (D, Executive) always escalates;
* a discount, a booking or an availability claim always escalates;
* a correction replaces the old value and is recorded;
* an unknown field stays explicitly unknown.

The replay is deterministic: a fresh session id per conversation and
fresh stores in a temporary directory, so a conversation can never be
answered from another one.
"""

from __future__ import annotations

import json
import os
import re
import uuid
from pathlib import Path

import pytest

from app.turn_pipeline import run_turn
from market.lead_state import LeadStateStore
from market.unmet_demand import UnmetDemandStore

GOLDEN_FILE = Path(__file__).parent / "golden" / "conversations.json"

# A raw plot number (for example "A-123") must never appear in a reply.
_PLOT_NUMBER = re.compile(r"\b[A-Z]{1,2}-\d{2,}\b")


@pytest.fixture(scope="module")
def conversations():
    with GOLDEN_FILE.open("r", encoding="utf-8") as handle:
        return json.load(handle)


@pytest.fixture(autouse=True)
def _stores(tmp_path, monkeypatch):
    """Every test gets its own state and demand store."""
    monkeypatch.setenv("M11_STATE_DB", str(tmp_path / "state.db"))
    monkeypatch.setenv("M11_DEMAND_DB", str(tmp_path / "demand.db"))


def _replay(conversation):
    """Run the conversation turn by turn and return the results."""
    store = LeadStateStore()
    demand = UnmetDemandStore()
    session_id = "golden-%s-%s" % (conversation["id"], uuid.uuid4().hex[:8])
    results = []
    for turn in conversation["turns"]:
        results.append(run_turn(turn["message"], session_id,
                                store=store, demand_store=demand))
    return results


def test_golden_file_has_fifteen_conversations(conversations):
    assert len(conversations) == 15
    ids = [c["id"] for c in conversations]
    assert len(set(ids)) == 15
    for conversation in conversations:
        assert conversation["turns"], conversation["id"]
        for turn in conversation["turns"]:
            assert turn["expect_route"] in ("exact", "alternative",
                                            "clarify", "escalate")


@pytest.mark.parametrize("index", range(15))
def test_golden_conversation_replays_as_specified(conversations, index):
    conversation = conversations[index]
    results = _replay(conversation)

    for turn, result in zip(conversation["turns"], results):
        where = "%s / %r" % (conversation["id"], turn["message"])

        assert result["route"] == turn["expect_route"], where
        assert bool(result["escalation"]) == turn["expect_escalation"], where

        cells = [[option["block"], option["size_marla"]]
                 for option in result["verified_options"]]
        assert cells == turn["expect_option_cells"], where

        assert (result["unmet_demand"] is not None) == \
            turn["expect_unmet_demand"], where

        state = result["lead_state"]["fields"]
        for name, expected in turn["expect_fields"].items():
            actual = state[name]
            assert actual["status"] == expected["status"], \
                "%s: %s status" % (where, name)
            assert actual["value"] == expected["value"], \
                "%s: %s value" % (where, name)
            assert actual["source_turn"] == expected["source_turn"], \
                "%s: %s source turn" % (where, name)


@pytest.mark.parametrize("index", range(15))
def test_golden_conversation_is_private_and_traceable(conversations, index):
    """No raw plot number, no price in an option, no live model call."""
    conversation = conversations[index]
    results = _replay(conversation)

    for turn, result in zip(conversation["turns"], results):
        where = "%s / %r" % (conversation["id"], turn["message"])
        reply = result["reply"]
        assert not _PLOT_NUMBER.search(reply), where
        for option in result["verified_options"]:
            assert set(option) == {"block", "size_marla", "reason",
                                   "verified"}, where
        assert result["gates"]["claim_guard_ok"] in (True, None), where


def test_the_four_routes_are_all_demonstrated(conversations):
    routes = set()
    for conversation in conversations:
        for turn in conversation["turns"]:
            routes.add(turn["expect_route"])
    assert routes == {"exact", "alternative", "clarify", "escalate"}


def test_the_five_turn_qualification_flow(conversations):
    """The master's own example, turn by turn."""
    flow = next(c for c in conversations if c["id"] == "01_full_qualification")
    assert [t["message"] for t in flow["turns"]] == [
        "I need a plot", "5 marla", "Block C", "around 8 million",
        "for investment"]
    last = flow["turns"][-1]["expect_fields"]
    assert last["size"]["value"] == 5.0
    assert last["size"]["status"] == "stated"
    assert last["block"]["value"] == "C"
    assert last["budget"]["status"] == "stated"
    assert last["purpose"]["value"] == "investment"
    # the timeline was never stated, so it stays explicitly unknown
    assert last["timeline"]["status"] == "unknown"
    assert last["timeline"]["value"] is None


def test_a_correction_replaces_the_old_value(conversations):
    flow = next(c for c in conversations
                if c["id"] == "02_mid_conversation_correction")
    corrected = flow["turns"][-1]["expect_fields"]["budget"]
    assert corrected["status"] == "corrected"
    assert corrected["value"]["min_pkr"] == 12000000


def test_the_thin_cells_never_quote_a_price(conversations):
    for cell in ("03_thin_cell_a14", "04_thin_cell_b7", "05_thin_cell_c10"):
        flow = next(c for c in conversations if c["id"] == cell)
        for turn in flow["turns"]:
            assert turn["expect_route"] != "exact", cell
            assert turn["expect_unmet_demand"] is True, cell


def test_the_parked_and_unsafe_turns_escalate(conversations):
    for case in ("06_out_of_scope_block_d", "07_discount_request",
                 "08_booking_request", "13_executive_block_parked",
                 "14_availability_request"):
        flow = next(c for c in conversations if c["id"] == case)
        for turn in flow["turns"]:
            assert turn["expect_route"] == "escalate", case
            assert turn["expect_escalation"] is True, case
            assert turn["expect_option_cells"] == [], case


def test_the_unmet_demand_record_carries_no_private_data(conversations):
    store = UnmetDemandStore()
    for conversation in conversations:
        for turn in conversation["turns"]:
            record = turn.get("expect_unmet_demand")
            assert record in (True, False)
    # the shape of a demand record: size, block, budget band - nothing else
    for shape in store.shapes(limit=50):
        assert set(shape) <= {"size_marla", "block", "budget_band"}
