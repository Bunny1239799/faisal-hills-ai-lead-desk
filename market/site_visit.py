"""Founder-controlled site-visit scheduling (pilot features).

The AI may PROPOSE visit slots only from the founder-approved slot
calendar. It never confirms a visit, never sends a message, never
shares contacts, never claims plot availability and never promises a
price, discount or possession date.

State files (both outside the repository, in the founder's data area):

    founder_approved_visit_slots.json  - the calendar (the founder owns it)
    site_visit_requests.jsonl          - one JSON record per request

Slot lifecycle: AVAILABLE -> (founder approval of a request)
PENDING_CONFIRMATION -> (founder's manual confirmation) CONFIRMED.
The AI has no code path to CONFIRMED - that transition is a founder-only
manual action outside this module.

Request lifecycle: REQUESTED -> FOUNDER_APPROVED (via approve()).
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

DATA_DIR = Path(os.environ.get(
    "SITE_VISIT_DATA_DIR", r"D:\FaisalHillsAILeadDesk\data"))


def _slots_path() -> Path:
    """Resolved per call so tests can relocate the calendar."""
    return Path(os.environ.get(
        "SITE_VISIT_SLOTS_PATH",
        str(DATA_DIR / "founder_approved_visit_slots.json")))


def _requests_path() -> Path:
    """Resolved per call so tests can relocate the request log."""
    return Path(os.environ.get(
        "SITE_VISIT_REQUESTS_PATH",
        str(DATA_DIR / "site_visit_requests.jsonl")))


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def load_slots() -> List[Dict[str, Any]]:
    if not _slots_path().exists():
        return []
    payload = json.loads(_slots_path().read_text(encoding="utf-8"))
    return list(payload.get("slots") or [])


def _save_slots(slots: List[Dict[str, Any]]) -> None:
    path = _slots_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"slots": slots}, indent=2, ensure_ascii=False),
        encoding="utf-8")


def available_slots() -> List[Dict[str, Any]]:
    """The slots the AI may propose: founder-approved and still
    AVAILABLE. PENDING_CONFIRMATION and CONFIRMED slots are never
    offered again."""
    return [s for s in load_slots()
            if s.get("founder_approved") is True
            and str(s.get("status", "")).upper() == "AVAILABLE"]


def _weekday(date_text: str) -> str:
    try:
        return datetime.strptime(str(date_text), "%Y-%m-%d").strftime("%A")
    except ValueError:
        return ""


def _band(start_time: str) -> str:
    try:
        hour = int(str(start_time).split(":")[0])
    except (ValueError, IndexError):
        return ""
    if hour < 12:
        return "morning"
    if hour < 17:
        return "afternoon"
    return "evening"


def offer_sentence(slots: Optional[List[Dict[str, Any]]] = None) -> str:
    """A digits-free customer-facing offer sentence.

    The slots are described by weekday and time-of-day band only - no
    year, no date numerals, no 24-hour clock - so the M5 traceability
    gate finds no untraceable number in the reply. The precise date and
    time live in the slot record and the founder's approval draft.
    """
    slots = slots if slots is not None else available_slots()
    if not slots:
        return ""
    phrases = []
    seen = set()
    for slot in slots[:3]:
        day = _weekday(slot.get("date", ""))
        band = _band(slot.get("start_time", ""))
        phrase = " ".join(w for w in (
            "this" if day else "", day, "in the" if band else "", band) if w)
        if phrase and phrase not in seen:
            seen.add(phrase)
            phrases.append(phrase)
    if not phrases:
        return ""
    if len(phrases) == 1:
        return (
            "For a serious buyer, a founder-approved site-visit slot is "
            "still open %s, starting from the Faisal Hills site office. "
            "Would you like me to request that slot for you? The team "
            "will confirm every detail personally." % phrases[0])
    listing = "; or ".join(phrases)
    return (
        "For a serious buyer, the founder-approved site-visit slots "
        "still open are %s, all starting from the Faisal Hills site "
        "office. Would you like me to request one of these slots for "
        "you? The team will confirm every detail personally." % listing)


_AFFIRM_RE = re.compile(
    r"\b(yes|yeah|ok|okay|sure|works|suits|good|book|confirm|choose|"
    r"select|first|second|third|let's|lets|go with|please|request)\b",
    re.IGNORECASE)


def detect_choice(message: str,
                  slots: Optional[List[Dict[str, Any]]] = None
                  ) -> Optional[Dict[str, Any]]:
    """The chosen slot when the dealer's reply clearly picks one of the
    offered slots. Conservative: a weekday or time-of-day reference AND
    an affirmative word. Returns None when nothing clearly matches."""
    text = str(message or "").lower()
    if not text:
        return None
    slots = slots if slots is not None else available_slots()
    if not slots or not _AFFIRM_RE.search(text):
        return None
    for slot in slots:
        day = _weekday(slot.get("date", "")).lower()
        band = _band(slot.get("start_time", ""))
        if day and day in text:
            return slot
        if band and band in text:
            return slot
    return None


def requests() -> List[Dict[str, Any]]:
    if not _requests_path().exists():
        return []
    rows = []
    for line in _requests_path().read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def find_request(request_id: str) -> Optional[Dict[str, Any]]:
    for row in requests():
        if row.get("request_id") == request_id:
            return row
    return None


def has_request_for_lead(lead_key: str) -> bool:
    return any(row.get("lead_id") == lead_key for row in requests())


def create_request(lead_key: str, slot: Dict[str, Any],
                   requirements: Dict[str, Any],
                   temperature: str, score: int,
                   summary: str) -> Dict[str, Any]:
    """Record a SITE_VISIT_REQUESTED row. Privacy-safe by construction:
    requirements, temperature, score and a short conversation summary
    only - never a phone number, email, contact name or raw chat."""
    request = {
        "request_id": "SVR-%s-%s" % (
            datetime.now().strftime("%Y%m%d%H%M%S"),
            str(slot.get("slot_id", "SLOT"))),
        "lead_id": lead_key,
        "selected_slot_id": slot.get("slot_id"),
        "selected_slot_date": slot.get("date"),
        "selected_slot_time": "%s-%s" % (slot.get("start_time", ""),
                                         slot.get("end_time", "")),
        "preferred_blocks": ([requirements.get("block")]
                             if requirements.get("block") else []),
        "preferred_sizes": ([requirements.get("size_marla")]
                            if requirements.get("size_marla") not in
                            (None, "") else []),
        "budget_band": (
            "%s-%s" % (requirements.get("budget_min_pkr"),
                       requirements.get("budget_max_pkr"))
            if requirements.get("budget_max_pkr") else ""),
        "purpose": requirements.get("purpose") or "",
        "timeline": requirements.get("timeline") or "",
        "lead_temperature": temperature,
        "lead_score": score,
        "request_status": "REQUESTED",
        "founder_approval_status": "PENDING",
        "created_at": _now(),
        "privacy_safe_conversation_summary": str(summary or "")[:300],
    }
    requests_path = _requests_path()
    requests_path.parent.mkdir(parents=True, exist_ok=True)
    with open(requests_path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(request, ensure_ascii=False) + "\n")
    return request


def approve_request(request_id: str, approved_by: str
                    ) -> Tuple[Optional[Dict[str, Any]], str]:
    """The founder's approval: the request moves to FOUNDER_APPROVED and
    the slot to PENDING_CONFIRMATION. The returned draft is what the
    operator may send AFTER this approval - sent manually, never
    automatically. No code path ever sets CONFIRMED."""
    rows = requests()
    request = None
    for row in rows:
        if row.get("request_id") == request_id:
            request = row
            break
    if request is None or request.get("founder_approval_status") == \
            "APPROVED":
        return request, ""

    request["founder_approval_status"] = "APPROVED"
    request["approved_by"] = approved_by
    request["approved_at"] = _now()

    with open(_requests_path(), "w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    slots = load_slots()
    for slot in slots:
        if slot.get("slot_id") == request.get("selected_slot_id"):
            slot["status"] = "PENDING_CONFIRMATION"
            _save_slots(slots)
            break

    draft = (
        "Thank you for choosing a site visit. A member of our team will "
        "confirm the exact time and meeting point with you personally "
        "before the visit.")
    return request, draft
