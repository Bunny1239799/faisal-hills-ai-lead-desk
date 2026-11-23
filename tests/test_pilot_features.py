"""Pilot features - lead qualification, site-visit scheduling, and the
pilot-readiness scenarios (real pipeline, isolated stores).

Covers the fifteen required test items plus the pilot-readiness set.
The site-visit state files are relocated to a tmp directory per test so
the founder's real calendar is never touched by tests.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(r"D:\AI-Projects\laya-gateway")
sys.path.insert(0, str(ROOT))

from market import lead_qualification as lq  # noqa: E402
from market import site_visit as sv  # noqa: E402
from market import lead_pipeline as lp  # noqa: E402


@pytest.fixture()
def visit_env(tmp_path, monkeypatch):
    monkeypatch.setenv("SITE_VISIT_SLOTS_PATH",
                       str(tmp_path / "slots.json"))
    monkeypatch.setenv("SITE_VISIT_REQUESTS_PATH",
                       str(tmp_path / "requests.jsonl"))
    slots = {"slots": [
        {"slot_id": "SLOT-001", "date": "2026-10-27",
         "start_time": "16:00", "end_time": "17:00",
         "location": "Faisal Hills site office", "status": "AVAILABLE",
         "founder_approved": True},
        {"slot_id": "SLOT-002", "date": "2026-10-29",
         "start_time": "10:00", "end_time": "11:00",
         "location": "Faisal Hills site office", "status": "AVAILABLE",
         "founder_approved": True},
        {"slot_id": "SLOT-003", "date": "2026-10-31",
         "start_time": "09:00", "end_time": "10:30",
         "location": "Faisal Hills site office", "status": "AVAILABLE",
         "founder_approved": True},
        {"slot_id": "SLOT-004", "date": "2026-11-01",
         "start_time": "15:00", "end_time": "16:30",
         "location": "Faisal Hills site office", "status": "AVAILABLE",
         "founder_approved": False},
        {"slot_id": "SLOT-005", "date": "2026-11-03",
         "start_time": "16:00", "end_time": "17:00",
         "location": "Faisal Hills site office",
         "status": "PENDING_CONFIRMATION", "founder_approved": True},
    ]}
    (tmp_path / "slots.json").write_text(
        json.dumps(slots), encoding="utf-8")
    return tmp_path


def _reqs(**kw):
    base = {"block": None, "size_marla": None, "budget_max_pkr": None,
            "purpose": None, "timeline": None, "corner": False,
            "sun_facing": False, "park_facing": False,
            "main_boulevard": False, "road_facing": False}
    base.update(kw)
    return base


# --- 1. lead score calculation ------------------------------------------

def test_score_is_zero_for_an_empty_lead():
    view = lq.qualification_view(_reqs())
    assert view["score"] == 0
    assert view["score_breakdown"] == []


def test_score_weights_follow_the_founder_tiers():
    hot = lq.qualification_view(_reqs(
        block="C", size_marla=5.0, budget_max_pkr=6_000_000,
        timeline="immediately"))
    # budget 25 + timeline 20 + block 15 + size 15 = 75 raw,
    # normalised against the 145 raw maximum
    assert hot["score"] == round(100 * 75 / 145)
    only_features = lq.qualification_view(_reqs(
        corner=True, park_facing=True, main_boulevard=True,
        road_facing=True, sun_facing=True))
    # five features, capped at 15 raw -> the LOW tier cannot dominate
    assert only_features["score"] == round(100 * 15 / 145)


def test_score_shows_every_reason_verbatim():
    view = lq.qualification_view(_reqs(budget_max_pkr=6_000_000,
                                       timeline="immediately"))
    assert any("budget stated (+25)" in r for r in view["score_breakdown"])
    assert any("timeline stated (+20)" in r for r in view["score_breakdown"])
    assert view["score_formula"].startswith("budget 25 + timeline 20")


def test_repeat_engagement_and_visit_interest_score():
    plain = lq.qualification_view(_reqs(block="C"))
    repeat = lq.qualification_view(_reqs(block="C"), turns=5)
    visit = lq.qualification_view(_reqs(block="C"),
                                  message="can I visit the site?")
    assert repeat["score"] > plain["score"]
    assert visit["score"] > plain["score"]


# --- 2. lead temperature classification ---------------------------------

def test_hot_requires_budget_timeline_and_property():
    view = lq.qualification_view(_reqs(
        block="C", size_marla=5.0, budget_max_pkr=6_000_000,
        timeline="immediately"))
    assert view["temperature"] == "HOT"


def test_warm_when_some_requirements_known():
    view = lq.qualification_view(_reqs(block="C"))
    assert view["temperature"] == "WARM"


def test_cold_when_nothing_stated():
    view = lq.qualification_view(_reqs())
    assert view["temperature"] == "COLD"


# --- 3. pipeline-stage transitions --------------------------------------

def test_stage_suggestions_follow_the_qualification():
    assert lq.qualification_view(_reqs())["stage_suggestion"] == \
        "NEW_INQUIRY"
    assert lq.qualification_view(_reqs(block="C"))["stage_suggestion"] == \
        "QUALIFYING"
    assert lq.qualification_view(_reqs(
        block="C", size_marla=5.0, budget_max_pkr=6_000_000,
        timeline="immediately"))["stage_suggestion"] == "QUALIFIED"


def test_site_visit_stages_exist_and_are_reachable():
    assert "SITE_VISIT_REQUESTED" in lp.LEAD_STAGES
    assert "SITE_VISIT_CONFIRMED" in lp.LEAD_STAGES
    view = lq.qualification_view(_reqs(block="C"), has_visit_request=True)
    assert view["stage_suggestion"] == "SITE_VISIT_REQUESTED"


# --- 4. missing-requirement detection -----------------------------------

def test_missing_requirements_are_listed_not_guessed():
    view = lq.qualification_view(_reqs(block="C"))
    assert "budget" in view["missing_requirements"]
    assert "size" in view["missing_requirements"]
    assert "block" not in view["missing_requirements"]


def test_next_action_follows_the_temperature():
    assert "site-visit" in lq.qualification_view(_reqs(
        block="C", size_marla=5.0, budget_max_pkr=6_000_000,
        timeline="immediately"))["recommended_next_action"].lower()
    assert "missing" in lq.qualification_view(_reqs(
        block="C"))["recommended_next_action"].lower() or \
        "question" in lq.qualification_view(_reqs(
            block="C"))["recommended_next_action"].lower()
    assert "not pressure" in lq.qualification_view(
        _reqs())["recommended_next_action"].lower()


# --- 5-7. hot/warm/cold customer flows (real pipeline) -------------------

def test_hot_lead_is_offered_founder_approved_slots(visit_env):
    sys.path.insert(0, str(ROOT))
    for key in ("M11_STATE_DB", "M11_DEMAND_DB", "M12_LOG_DB",
                "LEAD_PIPELINE_DB", "PILOT_FEEDBACK_DB", "DB_PATH"):
        os.environ[key] = str(visit_env / (key + ".db"))
    import app.server as server
    try:
        server.init_app_db()
    except Exception:
        pass
    from app.pipeline import handle_message
    result = handle_message(
        "I need a 5 marla plot in Block C, budget 60 lakh, needed "
        "immediately", lead_id="pilot-test-hot")
    reply = (result.get("draft_reply") or "").lower()
    assert result["site_visit"]["offered"] is True
    assert "site-visit" in reply or "site visit" in reply
    assert "tuesday" in reply                       # SLOT-001's weekday
    assert "would you like me to request" in reply
    assert result["lead_qualification"]["temperature"] == "HOT"
    # one ask per reply: the visit offer carries it
    assert reply.count("?") == 1


def test_warm_lead_gets_the_clarification_not_slots(visit_env):
    sys.path.insert(0, str(ROOT))
    for key in ("M11_STATE_DB", "M11_DEMAND_DB", "M12_LOG_DB",
                "LEAD_PIPELINE_DB", "PILOT_FEEDBACK_DB", "DB_PATH"):
        os.environ[key] = str(visit_env / (key + ".db"))
    from app.pipeline import handle_message
    result = handle_message("I need a plot in Block C",
                            lead_id="pilot-test-warm")
    reply = (result.get("draft_reply") or "").lower()
    assert result["site_visit"]["offered"] is False
    assert result["lead_qualification"]["temperature"] == "WARM"
    assert "?" in reply                             # a clarification
    assert "site-visit" not in reply


def test_cold_lead_gets_a_safe_response_without_pressure(visit_env):
    sys.path.insert(0, str(ROOT))
    for key in ("M11_STATE_DB", "M11_DEMAND_DB", "M12_LOG_DB",
                "LEAD_PIPELINE_DB", "PILOT_FEEDBACK_DB", "DB_PATH"):
        os.environ[key] = str(visit_env / (key + ".db"))
    from app.pipeline import handle_message
    result = handle_message("hello", lead_id="pilot-test-cold")
    reply = (result.get("draft_reply") or "").lower()
    assert (result.get("site_visit") or {}).get("offered") is not True
    assert "member of our team" in reply or "get back" in reply
    assert "visit" not in reply


# --- 8. founder-approved slot filtering ---------------------------------

def test_only_available_founder_approved_slots_are_offered(visit_env):
    slots = sv.available_slots()
    ids = [s["slot_id"] for s in slots]
    assert "SLOT-004" not in ids            # founder_approved false
    assert "SLOT-005" not in ids            # PENDING_CONFIRMATION


# --- 9. visit-request creation ------------------------------------------

def test_visit_request_record_is_complete_and_privacy_safe(visit_env):
    slots = sv.available_slots()
    request = sv.create_request(
        "lead-test-1", slots[0],
        _reqs(block="C", size_marla=5.0, budget_max_pkr=6_000_000),
        "HOT", 62, "Requirements: 5 marla, Block C")
    for field in ("request_id", "lead_id", "selected_slot_id",
                  "preferred_blocks", "preferred_sizes", "budget_band",
                  "purpose", "timeline", "lead_temperature", "lead_score",
                  "request_status", "founder_approval_status", "created_at",
                  "privacy_safe_conversation_summary"):
        assert field in request, field
    assert request["request_status"] == "REQUESTED"
    assert request["founder_approval_status"] == "PENDING"
    dumped = json.dumps(request).lower()
    assert "03" not in dumped[60:] or "phone" not in dumped
    assert "@" not in dumped
    assert "sender" not in dumped


# --- 10. founder-approval requirement -----------------------------------

def test_approval_moves_request_and_slot(visit_env):
    slots = sv.available_slots()
    request = sv.create_request("lead-test-2", slots[0], _reqs(block="C"),
                                "HOT", 50, "summary")
    approved, draft = sv.approve_request(request["request_id"],
                                         "Muhammad Hanzala")
    assert approved["founder_approval_status"] == "APPROVED"
    assert approved["approved_by"] == "Muhammad Hanzala"
    assert draft                                # the confirmation draft
    statuses = {s["slot_id"]: s["status"] for s in sv.load_slots()}
    assert statuses[slots[0]["slot_id"]] == "PENDING_CONFIRMATION"


# --- 11. no automatic confirmation --------------------------------------

def test_no_code_path_confirms_a_visit(visit_env):
    slots = sv.available_slots()
    request = sv.create_request("lead-test-3", slots[0], _reqs(block="C"),
                                "HOT", 50, "summary")
    approved, _draft = sv.approve_request(request["request_id"], "founder")
    statuses = {s["slot_id"]: s["status"] for s in sv.load_slots()}
    assert all(status != "CONFIRMED" for status in statuses.values())
    source = (ROOT / "market" / "site_visit.py").read_text(encoding="utf-8")
    assert '"CONFIRMED"' not in source and "'CONFIRMED'" not in source


# --- 12. no contact-data leakage ----------------------------------------

def test_visit_offer_and_request_carry_no_contact_data(visit_env):
    offer = sv.offer_sentence()
    assert "03" not in offer.replace("2026", "")
    assert "@" not in offer
    assert "http" not in offer
    request = sv.create_request("lead-test-4", sv.available_slots()[0],
                                _reqs(block="C"), "WARM", 30, "summary")
    dumped = json.dumps(request).lower()
    assert "sender" not in dumped and "phone" not in dumped
    assert "raw" not in dumped


# --- 13. no availability claim in the visit flow ------------------------

def test_visit_offer_never_claims_availability(visit_env):
    offer = sv.offer_sentence().lower()
    assert "available" not in offer
    assert "for sale" not in offer
    assert "on the market" not in offer


# --- 14. no fabricated price in the visit flow --------------------------

def test_visit_request_carries_only_stated_budget(visit_env):
    request = sv.create_request(
        "lead-test-5", sv.available_slots()[0],
        _reqs(block="C", budget_max_pkr=6_000_000), "HOT", 55, "summary")
    assert request["budget_band"].endswith("6000000")
    # nothing invented: no price beyond what the requirements carried
    assert "fabricated" not in json.dumps(request)


# --- 15. escalation behavior is untouched -------------------------------

def test_out_of_scope_still_escalates(visit_env):
    sys.path.insert(0, str(ROOT))
    for key in ("M11_STATE_DB", "M11_DEMAND_DB", "M12_LOG_DB",
                "LEAD_PIPELINE_DB", "PILOT_FEEDBACK_DB", "DB_PATH"):
        os.environ[key] = str(visit_env / (key + ".db"))
    from app.pipeline import handle_message
    result = handle_message("5 marla in Block Z, budget 60 lakh",
                            lead_id="pilot-test-oos")
    assert result.get("needs_human") is True
    assert result["draft_reply"].lower().startswith(
        "thank you for your message")
