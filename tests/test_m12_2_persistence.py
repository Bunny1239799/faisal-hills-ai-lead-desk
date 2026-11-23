"""M12.2 - persistence: the conversation log, the draft actions and the
operator activity view.

What is checked here:

* the store records turns and actions and reads them back, and fails
  **closed** when its file cannot be read;
* a turn run through the conversation endpoint is recorded, and the
  transcript REPLAYS exactly what was served - the dealer's own words
  and the reply the pipeline already validated (never a new answer);
* the conversation list carries the session, its last route, its
  preview and the take-over stamp;
* the draft actions and the take-over are recorded, and the activity
  view counts them - with no message text at all;
* every number the transcript serves is one the approved master may
  serve, exactly like the conversation endpoint itself.
"""

from __future__ import annotations

import os
import re
import uuid

import pytest

import app.server as server
from market import fact_guard
from market.conversation_log import ConversationLogStore
from market.fact_validator import extract_numbers

_PLOT_NUMBER = re.compile(r"\b[A-Z]{1,2}-\d{2,}\b")


@pytest.fixture(autouse=True)
def _stores(tmp_path, monkeypatch):
    monkeypatch.setenv("M11_STATE_DB", str(tmp_path / "state.db"))
    monkeypatch.setenv("M11_DEMAND_DB", str(tmp_path / "demand.db"))
    monkeypatch.setenv("M12_LOG_DB", str(tmp_path / "m12log.db"))


def _allowed_numbers():
    """Every number the approved master may serve, for any in-scope cell."""
    allowed = set()
    for block in ("A", "B", "C"):
        for size in (5, 7, 10, 14, 20, 40):
            allowed |= fact_guard.allowed_numbers_for(block=block,
                                                      size_marla=size)
    return allowed


# ---------------------------------------------------------------------------
# the store itself
# ---------------------------------------------------------------------------

def test_the_store_records_and_replays_turns(tmp_path):
    store = ConversationLogStore(str(tmp_path / "log.db"))
    assert store.record_turn("s-1", 1, "I need a plot", "A question",
                             "clarify", False)
    assert store.record_turn("s-1", 2, "5 marla block C", "A price range",
                             "exact", False)
    assert store.record_turn("s-2", 1, "Any discount?", "Escalated",
                             "escalate", True)

    turns = store.transcript("s-1")
    assert [turn["turn"] for turn in turns] == [1, 2]
    assert turns[0]["dealer_message"] == "I need a plot"
    assert turns[1]["reply"] == "A price range"
    assert turns[1]["escalation"] is False

    assert store.transcript("s-unknown") == []


def test_the_store_lists_conversations_newest_first(tmp_path):
    store = ConversationLogStore(str(tmp_path / "log.db"))
    store.record_turn("s-1", 1, "first message " + "x" * 80, "reply",
                      "clarify", False)
    store.record_turn("s-2", 1, "second message", "reply", "exact", False)

    listed = store.list_conversations()
    assert [item["session_id"] for item in listed] == ["s-2", "s-1"]
    assert listed[0]["turns"] == 1
    assert listed[0]["route"] == "exact"
    assert listed[1]["preview"].endswith("\u2026")  # the 60-char preview


def test_the_store_records_actions_and_serves_activity(tmp_path):
    store = ConversationLogStore(str(tmp_path / "log.db"))
    assert store.record_action("s-1", "sent")
    assert store.record_action("s-1", "sent")
    assert store.record_action("s-1", "rejected")
    assert store.record_action("s-2", "taken_over")
    # an action outside the vocabulary is refused
    assert not store.record_action("s-1", "deleted the lead")

    activity = store.activity(limit=10)
    assert activity["counts"] == {"sent": 2, "rejected": 1, "taken_over": 1}
    assert len(activity["recent"]) == 4
    # the events carry no message text
    for event in activity["recent"]:
        assert set(event) == {"session_id", "action", "time"}


def test_the_store_fails_closed(tmp_path):
    # a directory where the database file would be: nothing can be read
    # or written, and every call yields its empty answer
    broken = tmp_path / "log.db"
    broken.mkdir()
    store = ConversationLogStore(str(broken))
    assert store.transcript("s-1") == []
    assert store.list_conversations() == []
    assert store.activity() == {"counts": {}, "recent": [],
                                "totals": {"conversations": 0,
                                           "ai_drafts": 0,
                                           "escalations": 0}}
    assert not store.record_turn("s-1", 1, "m", "r", "clarify", False)
    assert not store.record_action("s-1", "sent")


# ---------------------------------------------------------------------------
# the routes
# ---------------------------------------------------------------------------

def test_a_turn_run_through_the_endpoint_is_recorded_and_replayed():
    session_id = "m12-2-" + uuid.uuid4().hex[:8]
    first = server.conversation_endpoint(
        message="I want a 7 marla plot in Block C",
        session_id=session_id, username="tester")
    second = server.conversation_endpoint(
        message="actually my budget is 60 lakh",
        session_id=session_id, username="tester")

    listed = server.conversations_endpoint(username="tester")
    mine = [item for item in listed["conversations"]
            if item["session_id"] == session_id]
    assert len(mine) == 1
    assert mine[0]["turns"] == 2
    assert mine[0]["route"] == second["route"]

    transcript = server.conversation_transcript_endpoint(
        session_id, username="tester")
    turns = transcript["turns"]
    assert [turn["turn"] for turn in turns] == [1, 2]
    # the replay is exact: the words the operator typed, the reply that
    # was served - nothing recomputed
    assert turns[0]["dealer_message"] == "I want a 7 marla plot in Block C"
    assert turns[0]["reply"] == first["reply"]
    assert turns[1]["reply"] == second["reply"]
    assert transcript["taken_over_at"] is None


def test_the_take_over_is_listed_and_counted():
    session_id = "m12-2-" + uuid.uuid4().hex[:8]
    server.conversation_endpoint(
        message="I want a 7 marla plot in Block C",
        session_id=session_id, username="tester")
    server.conversation_take_over_endpoint(session_id, username="tester")

    listed = server.conversations_endpoint(username="tester")
    mine = [item for item in listed["conversations"]
            if item["session_id"] == session_id]
    assert mine[0]["taken_over_at"]

    activity = server.operator_activity_endpoint(username="tester")
    assert activity["counts"].get("taken_over") == 1


def test_the_draft_actions_are_recorded_and_counted():
    session_id = "m12-2-" + uuid.uuid4().hex[:8]
    server.conversation_endpoint(
        message="I want a 7 marla plot in Block C",
        session_id=session_id, username="tester")

    for action in ("sent", "edited", "rejected", "operator_reply"):
        result = server.conversation_draft_action_endpoint(
            session_id, payload={"action": action}, username="tester")
        assert result == {"session_id": session_id, "action": action,
                          "recorded": True}

    activity = server.operator_activity_endpoint(username="tester")
    for action in ("sent", "edited", "rejected", "operator_reply"):
        assert activity["counts"].get(action) == 1

    # the activity view carries no message text
    assert "7 marla" not in str(activity)


def test_an_unknown_draft_action_is_refused():
    from fastapi import HTTPException

    session_id = "m12-2-" + uuid.uuid4().hex[:8]
    with pytest.raises(HTTPException) as caught:
        server.conversation_draft_action_endpoint(
            session_id, payload={"action": "delete everything"},
            username="tester")
    assert caught.value.status_code == 422

    with pytest.raises(HTTPException) as missing:
        server.conversation_draft_action_endpoint(
            session_id, payload=None, username="tester")
    assert missing.value.status_code == 422


def test_the_transcript_replays_the_verified_options_the_turn_served():
    """Showcase readiness (2026-11-22): a restored conversation shows the
    same verified-options panel a live turn does. The transcript replays
    exactly the options list the /api/conversation response carried -
    never a recomputed or invented one."""
    session_id = "m12-2-" + uuid.uuid4().hex[:8]
    served = server.conversation_endpoint(
        message="I want a 7 marla plot in Block C",
        session_id=session_id, username="tester")
    transcript = server.conversation_transcript_endpoint(
        session_id, username="tester")

    assert served["verified_options"], "the live turn must serve options"
    assert transcript["turns"][0]["options"] == served["verified_options"]

    # an older database without the options column still replays: the
    # migration adds the column and old turns simply carry no options
    store = ConversationLogStore(os.environ["M12_LOG_DB"])
    assert store.record_turn("legacy-1", 1, "hello", "a reply",
                             "clarify", False)
    legacy = store.transcript("legacy-1")
    assert legacy[0]["options"] == []


def test_the_pilot_metrics_total_the_recorded_turns():
    """M12.5: the founder's weekly review reads conversations, AI
    drafts, escalations and unmet demand from the activity route."""
    one = "m12-2-" + uuid.uuid4().hex[:8]
    two = "m12-2-" + uuid.uuid4().hex[:8]
    server.conversation_endpoint(
        message="I want a 7 marla plot in Block C",
        session_id=one, username="tester")
    server.conversation_endpoint(
        message="5 marla in block C", session_id=two, username="tester")
    server.conversation_endpoint(
        message="Any discount?", session_id=two, username="tester")
    server.conversation_draft_action_endpoint(
        two, payload={"action": "sent"}, username="tester")

    activity = server.operator_activity_endpoint(username="tester")
    totals = activity["totals"]
    assert totals["conversations"] >= 2
    assert totals["ai_drafts"] >= 3
    assert totals["escalations"] >= 1
    assert totals["unmet_demand"] >= 1
    # the totals carry counts only - never message text
    assert "7 marla" not in str(totals)


def test_the_transcript_serves_only_numbers_the_master_allows():
    for message in ("5 marla in block C", "7 marla Block A price",
                    "what about 10 marla in block B"):
        session_id = "m12-2-" + uuid.uuid4().hex[:8]
        served = server.conversation_endpoint(
            message=message, session_id=session_id, username="tester")
        transcript = server.conversation_transcript_endpoint(
            session_id, username="tester")

        for turn in transcript["turns"]:
            assert not _PLOT_NUMBER.search(turn["reply"])
            untraceable = {value for _text, value
                           in extract_numbers(turn["reply"])} - _allowed_numbers()
            assert untraceable == set(), (
                "the transcript served an untraceable number: %r"
                % sorted(untraceable)
            )
            # the replayed reply is byte-for-byte the served reply
            if turn["turn"] == served["turn"]:
                assert turn["reply"] == served["reply"]
