"""Pilot feedback, lead sources and the weekly owner report.

Checked here:
* the fixed source vocabulary (422 outside it), default OPERATOR_DESK,
  operator changes journaled in the lead timeline;
* structured feedback: every enum validated (422 on anything else),
  stored with operator + timestamp + a conversation-context REFERENCE,
  readable per lead;
* the weekly report aggregates RECORDED data: lead overview (stages,
  sources, follow-ups), AI performance (drafts, actions, rates),
  response quality (feedback + the honest time proxy), inventory
  intelligence (shapes, never message text), follow-up performance,
  safety (scan over replies) and recommendations derived by sorting;
* exports (markdown + csv) render the same numbers;
* privacy: no report or export contains dealer/customer message text,
  phone numbers or plot identifiers - even when the underlying turns
  exist.
"""

from __future__ import annotations

import re
import uuid

import pytest

import app.server as server
from market import lead_pipeline as lp
from market.pilot_feedback import (LEAD_SOURCES, PilotFeedbackStore,
                                   report_csv, report_markdown)

_PHONE = re.compile(r"(?:\+92|0)3\d{2}[- ]?\d{7}")
_PLOT = re.compile(r"\b[A-Z]{1,2}-\d{2,}\b")


@pytest.fixture(autouse=True)
def _stores(tmp_path, monkeypatch):
    monkeypatch.setenv("M11_STATE_DB", str(tmp_path / "state.db"))
    monkeypatch.setenv("M11_DEMAND_DB", str(tmp_path / "demand.db"))
    monkeypatch.setenv("M12_LOG_DB", str(tmp_path / "log.db"))
    monkeypatch.setenv("LEAD_PIPELINE_DB", str(tmp_path / "pipeline.db"))
    monkeypatch.setenv("PILOT_FEEDBACK_DB", str(tmp_path / "feedback.db"))


def _lead(prefix="pfr", turns=("I need a plot", "5 marla", "block C",
                               "around 80 lakh")) -> str:
    sid = prefix + "-" + uuid.uuid4().hex[:6]
    for message in turns:
        server.conversation_endpoint(message=message, session_id=sid,
                                     username="tester")
    return sid


VALID_FEEDBACK = {
    "quality": "USEFUL", "grounding": "GROUNDED", "time_saved": "MEDIUM",
    "would_send": "YES", "issue": "NONE", "note": "Clear band, customer happy.",
}


# ---------------------------------------------------------------------------
# lead source
# ---------------------------------------------------------------------------

def test_every_lead_defaults_to_operator_desk():
    sid = _lead()
    view = server.lead_pipeline_detail_endpoint(sid, username="tester")
    assert view["source"] == "OPERATOR_DESK"


def test_source_changes_are_validated_and_journaled():
    from fastapi import HTTPException

    sid = _lead()
    view = server.lead_source_endpoint(sid, {"source": "WHATSAPP_MANUAL"},
                                       username="tester")
    assert view["source"] == "WHATSAPP_MANUAL"
    entries = [e for e in view["stage_history"]
               if e.get("kind") == "source"]
    assert entries and entries[-1]["from"] == "OPERATOR_DESK"
    assert entries[-1]["to"] == "WHATSAPP_MANUAL"

    with pytest.raises(HTTPException) as caught:
        server.lead_source_endpoint(sid, {"source": "INSTAGRAM"},
                                    username="tester")
    assert caught.value.status_code == 422
    assert "INSTAGRAM" not in LEAD_SOURCES


def test_source_values_come_from_the_fixed_list_only():
    assert LEAD_SOURCES == ("OPERATOR_DESK", "DEMO", "MANUAL_ENTRY",
                            "WHATSAPP_MANUAL", "WEBSITE", "REFERRAL",
                            "OTHER")


# ---------------------------------------------------------------------------
# feedback
# ---------------------------------------------------------------------------

def test_valid_feedback_round_trips_with_context_reference():
    sid = _lead()
    result = server.pilot_feedback_post_endpoint(
        sid, dict(VALID_FEEDBACK), username="tester")
    assert result["recorded"] is True
    row = result["feedback"]
    assert row["operator"] == "tester"
    assert row["created_at"]
    assert row["context_ref"].startswith("conversation:turns=4")
    assert "last_route=" in row["context_ref"]

    listed = server.pilot_feedback_get_endpoint(sid, username="tester")
    assert listed["feedback"][0]["quality"] == "USEFUL"


@pytest.mark.parametrize("override", [
    {"quality": "GREAT"}, {"grounding": "MAYBE"},
    {"time_saved": "LOADS"}, {"would_send": "PERHAPS"},
    {"issue": "EVERYTHING"},
    {"quality": None, "grounding": None,
     "time_saved": None, "would_send": None,
     "issue": None},
])
def test_invalid_feedback_is_refused_not_defaulted(override):
    from fastapi import HTTPException

    sid = _lead()
    payload = dict(VALID_FEEDBACK)
    payload.update(override)
    with pytest.raises(HTTPException) as caught:
        server.pilot_feedback_post_endpoint(sid, payload, username="tester")
    assert caught.value.status_code == 422
    listed = server.pilot_feedback_get_endpoint(sid, username="tester")
    assert listed["feedback"] == []


def test_the_store_validates_enums_directly():
    store = PilotFeedbackStore()
    assert store.record("x", "op", quality="USEFUL",
                        grounding="GROUNDED", time_saved="LOW",
                        would_send="NO", issue="OTHER") is not None
    assert store.record("x", "op", quality="PERFECT",
                        grounding="GROUNDED", time_saved="LOW",
                        would_send="NO", issue="OTHER") is None


# ---------------------------------------------------------------------------
# the weekly report
# ---------------------------------------------------------------------------

def _seed_week(username="tester"):
    sid = _lead("wk1")
    server.conversation_draft_action_endpoint(
        sid, {"action": "sent"}, username=username)
    server.pilot_feedback_post_endpoint(sid, dict(VALID_FEEDBACK),
                                        username=username)
    sid2 = _lead("wk2", turns=("Any discount?",))
    server.conversation_take_over_endpoint(sid2, username=username)
    server.lead_source_endpoint(sid2, {"source": "REFERRAL"},
                                username=username)
    return sid, sid2


def test_the_report_aggregates_recorded_data():
    sid, sid2 = _seed_week()
    report = server.weekly_report_endpoint(username="tester")
    overview = report["lead_overview"]
    ai = report["ai_performance"]
    quality = report["response_quality"]

    assert overview["total_leads"] >= 2
    assert overview["by_source"].get("REFERRAL") == 1
    assert overview["by_source"].get("OPERATOR_DESK") >= 1
    assert overview["escalated"] >= 1 or overview["taken_over"] >= 1

    assert ai["total_ai_drafts"] >= 5       # 4 + 1 recorded turns
    assert ai["approved_as_is"] >= 1
    assert ai["approval_rate"] is not None

    assert quality["submissions"] >= 1
    assert quality["quality"].get("USEFUL") == 1
    assert quality["median_minutes"] is not None  # one action sample
    assert "measurable proxy" in quality["time_metric"]

    safety = report["safety"]
    assert safety["replies_scanned"] >= 5
    assert safety["privacy_leaks"] == 0
    assert safety["price_leaks"] == 0
    assert "gates" in safety["price_leaks_basis"]

    inventory = report["inventory_intelligence"]
    assert isinstance(inventory["top_unmet_shapes"], list)
    assert isinstance(inventory["thin_cells"], list) and \
        inventory["thin_cells"]        # the master has known thin cells

    recs = report["recommended_next_actions"]
    assert recs["basis"].startswith("every line above is a sorted count")


def test_the_source_filter_narrows_the_report():
    sid, sid2 = _seed_week()
    report = server.weekly_report_endpoint(source="REFERRAL",
                                           username="tester")
    assert report["lead_overview"]["source_filter"] == "REFERRAL"
    assert report["lead_overview"]["total_leads"] == 1
    assert report["lead_overview"]["by_source"] == {"REFERRAL": 1}
    with pytest.raises(Exception):
        server.weekly_report_endpoint(source="INSTAGRAM",
                                      username="tester")


def test_exports_render_the_same_numbers():
    _seed_week()
    report = server.weekly_report_endpoint(username="tester")
    markdown = report_markdown(report)
    csv_text = report_csv(report)

    assert "Weekly owner report" in markdown
    assert "price leaks: 0" in markdown
    assert "privacy leaks: 0" in markdown
    assert "by source: OPERATOR_DESK" in markdown or \
        "REFERRAL 1" in markdown
    assert csv_text.splitlines()[0] == '"section","metric","value"'
    assert '"ai","approved_as_is"' in csv_text
    assert '"safety","privacy_leaks",0' in csv_text


def test_reports_never_expose_private_data():
    """The dealer's own words exist in the turns - none of them may
    appear in a report or export; no phone or plot pattern either."""
    marker = "around 80 lakh"           # the dealer's literal wording
    sid = _lead()
    assert server.lead_pipeline_detail_endpoint(
        sid, username="tester")["turns"] == 4   # the turns really exist

    report = server.weekly_report_endpoint(username="tester")
    markdown = report_markdown(report)
    csv_text = report_csv(report)
    for text in (str(report), markdown, csv_text):
        assert marker not in text
        assert not _PHONE.search(text)
        assert not _PLOT.search(text)


def test_an_empty_pilot_reports_honestly():
    report = server.weekly_report_endpoint(username="tester")
    assert report["lead_overview"]["total_leads"] == 0
    assert report["ai_performance"]["approval_rate"] is None
    markdown = report_markdown(report)
    assert "price leaks: 0" in markdown
    assert report["recommended_next_actions"][
        "operator_workflow_improvements"]
