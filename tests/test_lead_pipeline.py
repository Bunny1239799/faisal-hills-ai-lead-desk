"""The lead pipeline: lead capture, stages, transparent scoring and
routing, the follow-up queue and the deterministic follow-up DRAFT.

Checked here:
* every conversation becomes a lead (NEW), with history;
* the TWO automatic flags (escalated / taken-over) and operator-only
  transitions (CLOSED_*), with full stage history;
* the transparent temperature and score: the exact published formula,
  the displayed rule, HOT/WARM/COLD boundaries;
* routing suggestions for each state;
* the follow-up queue sections (today / overdue / week / no-activity /
  escalated / unmet) from real dates;
* the follow-up DRAFT: assembled only from stated requirements, no
  price, no availability promise, no phone/plot pattern, no pressure -
  and nothing is ever sent by any of these endpoints.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timedelta, timezone

import pytest

import app.server as server
from market import lead_pipeline as lp

_PHONE = re.compile(r"(?:\+92|0)3\d{2}[- ]?\d{7}")
_PLOT = re.compile(r"\b[A-Z]{1,2}-\d{2,}\b")


@pytest.fixture(autouse=True)
def _stores(tmp_path, monkeypatch):
    monkeypatch.setenv("M11_STATE_DB", str(tmp_path / "state.db"))
    monkeypatch.setenv("M11_DEMAND_DB", str(tmp_path / "demand.db"))
    monkeypatch.setenv("M12_LOG_DB", str(tmp_path / "log.db"))
    monkeypatch.setenv("LEAD_PIPELINE_DB", str(tmp_path / "pipeline.db"))


def _qualified_lead(prefix="lp") -> str:
    sid = prefix + "-" + uuid.uuid4().hex[:6]
    for message in ("I need a plot", "5 marla", "block C",
                    "around 80 lakh"):
        server.conversation_endpoint(message=message, session_id=sid,
                                     username="tester")
    return sid


# ---------------------------------------------------------------------------
# capture + stages
# ---------------------------------------------------------------------------

def test_a_conversation_becomes_a_new_lead():
    sid = "lp-" + uuid.uuid4().hex[:6]
    server.conversation_endpoint(message="I need a plot",
                                 session_id=sid, username="tester")
    lead = server.lead_pipeline_detail_endpoint(sid, username="tester")
    assert lead["stage"] == "NEW"
    assert lead["stage_history"][0]["to"] == "NEW"
    assert lead["turns"] == 1


def test_escalation_sets_the_stage_automatically():
    sid = _qualified_lead()
    server.conversation_endpoint(message="Any discount?",
                                 session_id=sid, username="tester")
    lead = server.lead_pipeline_detail_endpoint(sid, username="tester")
    assert lead["stage"] == "ESCALATED"
    assert lead["stage_history"][-1]["by"] == "system"


def test_take_over_sets_the_stage_automatically():
    sid = _qualified_lead()
    server.conversation_take_over_endpoint(sid, username="tester")
    lead = server.lead_pipeline_detail_endpoint(sid, username="tester")
    assert lead["stage"] == "TAKEN_OVER"


def test_operator_changes_are_recorded_with_history_and_closed_is_operator_only():
    from fastapi import HTTPException

    sid = _qualified_lead()
    lead = server.lead_stage_endpoint(sid, {"stage": "QUALIFIED"},
                                      username="tester")
    assert lead["stage"] == "QUALIFIED"
    assert lead["stage_history"][-1]["by"] == "tester"

    closed = server.lead_stage_endpoint(sid, {"stage": "CLOSED_WON"},
                                        username="tester")
    assert closed["stage"] == "CLOSED_WON"

    with pytest.raises(HTTPException) as caught:
        server.lead_stage_endpoint(sid, {"stage": "DISMISSED"},
                                   username="tester")
    assert caught.value.status_code == 422
    with pytest.raises(HTTPException):
        server.lead_stage_endpoint("lp-unknown", {"stage": "NEW"},
                                   username="tester")


def test_notes_and_follow_up_dates_round_trip():
    sid = _qualified_lead()
    due = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
    lead = server.lead_follow_up_endpoint(sid, {"due_at": due},
                                          username="tester")
    assert lead["follow_up"]["due_this_week"] is True
    lead = server.lead_note_endpoint(sid, {"text": "Prefers evening calls."},
                                     username="tester")
    assert lead["notes"][0]["text"] == "Prefers evening calls."
    with pytest.raises(Exception):
        server.lead_note_endpoint(sid, {"text": "  "}, username="tester")


# ---------------------------------------------------------------------------
# transparent scoring, temperature, routing
# ---------------------------------------------------------------------------

def test_the_score_is_exactly_the_published_formula():
    fields = {"budget": True, "block": True, "size": True,
              "purpose": False, "timeline": False}
    recent = datetime.now(timezone.utc).isoformat()
    score = lp.score_lead(fields, recent, unresolved_escalation=False)
    assert score["score"] == 20 + 15 + 15 + 10 + 10  # 70
    assert "Block known (+15)" in score["reasons"]
    assert set(score["missing"]) == {"purpose", "timeline"}
    assert "not a conversion prediction" in score["formula"]


def test_temperature_boundaries_are_the_published_rules():
    now = datetime.now(timezone.utc)
    recent = now.isoformat()
    stale = (now - timedelta(days=10)).isoformat()
    all_fields = dict.fromkeys(
        ("budget", "block", "size", "purpose", "timeline"), True)
    few = {"budget": True}

    assert lp.temperature_of(all_fields, recent, False) == "HOT"
    # unresolved escalation drops HOT to the operator's queue
    assert lp.temperature_of(all_fields, recent, True) == "WARM"
    assert lp.temperature_of(few, recent, False) == "WARM"
    assert lp.temperature_of({}, stale, False) == "COLD"
    # the rule string says what it is
    assert "not a prediction of intent" in lp.TEMPERATURE_RULE


def test_routing_suggestions_cover_every_state():
    assert lp.routing_suggestion("HOT", False, False, False) == \
        "Contact today"
    assert lp.routing_suggestion("WARM", False, False, False) == \
        "Follow up within 48 hours"
    assert lp.routing_suggestion("COLD", False, False, False) == \
        "Nurture later"
    assert lp.routing_suggestion("HOT", True, False, False) == \
        "Human review required"
    assert lp.routing_suggestion("WARM", False, True, False) == \
        "Review inventory gap"
    assert lp.routing_suggestion("WARM", False, False, True) == \
        "Operator owns conversation"


def test_the_lead_view_derives_everything_from_recorded_data():
    sid = _qualified_lead("view")
    lead = server.lead_pipeline_detail_endpoint(sid, username="tester")
    assert lead["temperature"] in ("HOT", "WARM")
    assert 0 <= lead["score"]["score"] <= 100
    assert lead["routing"]
    assert lead["conversation_summary"].startswith("4 exchanges")
    assert set(lead["fields_known"]) <= {"budget", "block", "size",
                                         "purpose", "timeline"}
    assert lead["stage"] in lp.LEAD_STAGES


# ---------------------------------------------------------------------------
# the follow-up queue
# ---------------------------------------------------------------------------

def test_the_queue_sorts_real_dates_into_real_sections():
    sid = _qualified_lead("q")
    overdue = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    server.lead_follow_up_endpoint(sid, {"due_at": overdue},
                                   username="tester")
    queue = server.follow_ups_endpoint(username="tester")
    sections = queue["sections"]
    assert any(item["lead_id"] == sid for item in sections["overdue"])
    assert sections["overdue"][0]["follow_up"]["overdue"] is True
    assert all(item["lead_id"] != sid for item in sections["today"])


def test_escalated_leads_appear_in_the_escalated_section():
    sid = _qualified_lead("esc")
    server.conversation_endpoint(message="Any discount?",
                                 session_id=sid, username="tester")
    queue = server.follow_ups_endpoint(username="tester")
    assert any(item["lead_id"] == sid
               for item in queue["sections"]["escalated"])


# ---------------------------------------------------------------------------
# the follow-up DRAFT - safety first
# ---------------------------------------------------------------------------

def _draft_for(sid):
    queue = server.follow_ups_endpoint(username="tester")
    for items in queue["sections"].values():
        for item in items:
            if item["lead_id"] == sid:
                return item["follow_up_draft"]
    lead = server.lead_pipeline_detail_endpoint(sid, username="tester")
    return lp.draft_follow_up(lead)


def test_the_draft_is_safe_non_committal_and_labeled():
    sid = _qualified_lead("draft")
    draft = _draft_for(sid)
    text = draft["draft"]
    assert "Thank you for your interest" in text
    assert "No price or availability is confirmed" in text
    # no price, no plot, no phone, no pressure
    assert "PKR" not in text
    assert not _PHONE.search(text)
    assert not _PLOT.search(text)
    assert "human approval required" in draft["approval"]["note"].lower()
    assert draft["approval"]["required"] is True
    assert draft["evidence"]["fields_known"]  # only stated fields


def test_the_draft_asks_for_what_is_missing_when_nothing_is_stated():
    sid = "lp-" + uuid.uuid4().hex[:6]
    server.conversation_endpoint(message="hello there",
                                 session_id=sid, username="tester")
    draft = _draft_for(sid)
    assert "size and block" in draft["draft"]
    assert draft["evidence"]["fields_known"] == []


def test_no_endpoint_ever_sends_anything():
    """The pipeline API records decisions; nothing in it has any
    sending capability at all (asserted by surface: no send route)."""
    import app.server as srv
    for route in srv.app.routes:
        path = getattr(route, "path", "")
        assert "send" not in path.lower() or "draft-action" in path, path


def test_draft_actions_are_recorded_on_the_activity_log():
    sid = _qualified_lead("act")
    for action in ("followup_approved", "followup_edited",
                   "followup_rejected", "followup_copied"):
        result = server.conversation_draft_action_endpoint(
            sid, payload={"action": action}, username="tester")
        assert result["recorded"] is True
    activity = server.operator_activity_endpoint(username="tester")
    counts = activity["counts"]
    assert counts.get("followup_approved") == 1
    assert counts.get("followup_copied") == 1
