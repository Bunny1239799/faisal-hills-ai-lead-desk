"""The lead pipeline: every conversation becomes a trackable lead.

What this module is
-------------------
The lead layer on top of the conversation system: a stage per lead
(NEW / QUALIFYING / QUALIFIED / FOLLOW_UP / ESCALATED / TAKEN_OVER /
CLOSED_LOST / CLOSED_WON), operator notes, an operator-set follow-up
date, a full stage-history audit trail - and, DERIVED live from the
existing recorded data (never stored twice), the transparent
temperature, the 0-100 score, the routing suggestion, the follow-up
queue membership and a deterministic follow-up DRAFT.

What this module is NOT
-----------------------
It is not intelligence. The stage a lead sits in changes only by
operator approval, with exactly two automatic exceptions that mirror
existing product behavior: ESCALATED when a turn escalates, and
TAKEN_OVER when the operator takes over. Nothing auto-closes. The
score and temperature are TRANSPARENT arithmetic over known
qualification fields - displayed with their rules - and never a
prediction of intent or conversion. The follow-up draft is assembled
from words the conversation already established (stated size/block)
plus safe, non-committal wording: no price, no availability promise,
no pressure, no private data - and it is a DRAFT; only a human can
act on it.

The store lives in a SQLite file of its own (env ``LEAD_PIPELINE_DB``,
default ``data/lead_pipeline.db``) and fails closed like the others.
Deterministic, stdlib-only, no model calls.
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

__all__ = [
    "LEAD_STAGES",
    "LeadPipelineStore",
    "default_pipeline_path",
    "lead_view",
    "routing_suggestion",
    "score_lead",
    "suggest_stage",
    "temperature_of",
    "draft_follow_up",
]

LEAD_STAGES = (
    "NEW",
    "QUALIFYING",
    "QUALIFIED",
    "SITE_VISIT_REQUESTED",
    "SITE_VISIT_CONFIRMED",
    "FOLLOW_UP",
    "ESCALATED",
    "TAKEN_OVER",
    "CLOSED_LOST",
    "CLOSED_WON",
)

# the fixed lead-source vocabulary (pilot reporting, 2026-10-24)
LEAD_SOURCES = (
    "OPERATOR_DESK", "DEMO", "MANUAL_ENTRY", "WHATSAPP_MANUAL",
    "WEBSITE", "REFERRAL", "OTHER",
)

# the transparent score weights (displayed in the UI, verbatim)
SCORE_WEIGHTS = {
    "budget": 20, "block": 15, "size": 15, "purpose": 15,
    "timeline": 15, "recent_activity": 10, "no_unresolved_escalation": 10,
}

RECENT_WINDOW_HOURS = 48          # "recent activity" is a displayed rule
NO_ACTIVITY_DAYS = 7              # "no recent activity" for cold queue


def default_pipeline_path() -> str:
    return os.environ.get("LEAD_PIPELINE_DB") or os.path.join(
        "data", "lead_pipeline.db")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse(value) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


class LeadPipelineStore:
    """Lead records, stage history, notes and follow-up dates."""

    def __init__(self, path: Optional[str] = None) -> None:
        self.path = path or default_pipeline_path()

    def _connect(self) -> sqlite3.Connection:
        directory = os.path.dirname(os.path.abspath(self.path))
        if directory and not os.path.isdir(directory):
            os.makedirs(directory, exist_ok=True)
        # timeout: the desk fires several list/detail reads at once,
        # and a read must wait for a writer, not fail closed to empty
        conn = sqlite3.connect(self.path, timeout=10)
        try:
            conn.execute("PRAGMA journal_mode=WAL")
        except Exception:
            pass
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS leads (
                lead_id           TEXT PRIMARY KEY,
                label             TEXT NOT NULL,
                source            TEXT NOT NULL DEFAULT 'Operator Desk',
                stage             TEXT NOT NULL DEFAULT 'NEW',
                stage_history     TEXT NOT NULL DEFAULT '[]',
                assigned_operator TEXT,
                notes             TEXT NOT NULL DEFAULT '[]',
                follow_up_due_at  TEXT,
                created_at        TEXT NOT NULL,
                updated_at        TEXT NOT NULL
            )
            """
        )
        conn.commit()
        return conn

    # -- record lifecycle -------------------------------------------
    def ensure_lead(self, lead_id: str, label: Optional[str] = None,
                    source: str = "OPERATOR_DESK") -> bool:
        """A conversation becomes a lead the first time it is seen."""
        if not lead_id:
            return False
        stamp = _now()
        try:
            conn = self._connect()
        except Exception:
            return False
        try:
            conn.execute(
                "INSERT OR IGNORE INTO leads (lead_id, label, source, "
                "stage, stage_history, notes, created_at, updated_at) "
                "VALUES (?, ?, ?, 'NEW', ?, '[]', ?, ?)",
                (str(lead_id), str(label or lead_id), str(source),
                 json.dumps([{"to": "NEW", "at": stamp, "by": "system",
                              "reason": "conversation started"}]),
                 stamp, stamp),
            )
            conn.commit()
            return True
        except Exception:
            return False
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def get(self, lead_id: str) -> Optional[Dict[str, Any]]:
        if not lead_id:
            return None
        try:
            conn = self._connect()
        except Exception:
            return None
        try:
            row = conn.execute(
                "SELECT lead_id, label, source, stage, stage_history, "
                "assigned_operator, notes, follow_up_due_at, "
                "created_at, updated_at FROM leads WHERE lead_id = ?",
                (str(lead_id),)).fetchone()
        except Exception:
            return None
        finally:
            try:
                conn.close()
            except Exception:
                pass
        if not row:
            return None
        return {
            "lead_id": row[0], "label": row[1], "source": row[2],
            "stage": row[3],
            "stage_history": json.loads(row[4] or "[]"),
            "assigned_operator": row[5],
            "notes": json.loads(row[6] or "[]"),
            "follow_up_due_at": row[7],
            "created_at": row[8], "updated_at": row[9],
        }

    def list_ids(self) -> List[str]:
        try:
            conn = self._connect()
        except Exception:
            return []
        try:
            rows = conn.execute(
                "SELECT lead_id FROM leads ORDER BY updated_at DESC"
            ).fetchall()
        except Exception:
            return []
        finally:
            try:
                conn.close()
            except Exception:
                pass
        return [row[0] for row in rows]

    # -- stage transitions -------------------------------------------
    def _set_stage(self, lead_id: str, stage: str, by: str,
                   reason: str) -> bool:
        current = self.get(lead_id)
        if not current or stage not in LEAD_STAGES:
            return False
        if current["stage"] == stage:
            return True
        history = current["stage_history"]
        history.append({"from": current["stage"], "to": stage,
                        "at": _now(), "by": by, "reason": reason})
        try:
            conn = self._connect()
        except Exception:
            return False
        try:
            conn.execute(
                "UPDATE leads SET stage = ?, stage_history = ?, "
                "updated_at = ? WHERE lead_id = ?",
                (stage, json.dumps(history, ensure_ascii=False),
                 _now(), str(lead_id)),
            )
            conn.commit()
            return True
        except Exception:
            return False
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def mark_escalated(self, lead_id: str) -> bool:
        """The ONE automatic exception beside take-over: the existing
        escalation rules set ESCALATED on their own."""
        return self._set_stage(lead_id, "ESCALATED", "system",
                               "a turn escalated to human review")

    def mark_taken_over(self, lead_id: str) -> bool:
        return self._set_stage(lead_id, "TAKEN_OVER", "system",
                               "the operator took the conversation over")

    def operator_set_stage(self, lead_id: str, stage: str,
                           operator: str = "operator") -> bool:
        """Operator-approved transition. CLOSED_* stages exist ONLY
        here - nothing in the system closes a lead by itself."""
        if stage not in LEAD_STAGES:
            return False
        return self._set_stage(lead_id, stage, operator,
                               "operator approved the stage change")

    # -- follow-up dates and notes -----------------------------------
    def set_follow_up(self, lead_id: str, due_at: Optional[str]) -> bool:
        try:
            conn = self._connect()
        except Exception:
            return False
        try:
            conn.execute(
                "UPDATE leads SET follow_up_due_at = ?, updated_at = ? "
                "WHERE lead_id = ?", (due_at, _now(), str(lead_id)))
            conn.commit()
            return conn.total_changes > 0
        except Exception:
            return False
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def add_note(self, lead_id: str, text: str,
                 author: str = "operator") -> bool:
        lead = self.get(lead_id)
        if not lead or not str(text).strip():
            return False
        notes = lead["notes"]
        notes.append({"text": str(text).strip(), "at": _now(),
                      "by": author})
        try:
            conn = self._connect()
        except Exception:
            return False
        try:
            conn.execute(
                "UPDATE leads SET notes = ?, updated_at = ? WHERE "
                "lead_id = ?", (json.dumps(notes, ensure_ascii=False),
                                _now(), str(lead_id)))
            conn.commit()
            return True
        except Exception:
            return False
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def set_label(self, lead_id: str, label: str) -> bool:
        if not label or not label.strip():
            return False
        try:
            conn = self._connect()
        except Exception:
            return False
        try:
            conn.execute(
                "UPDATE leads SET label = ?, updated_at = ? WHERE "
                "lead_id = ?", (label.strip(), _now(), str(lead_id)))
            conn.commit()
            return conn.total_changes > 0
        except Exception:
            return False
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def set_source(self, lead_id: str, source: str,
                   operator: str = "operator") -> bool:
        """Operator-set lead source, from the fixed list only. The
        change is journaled in the lead timeline."""
        if source not in LEAD_SOURCES:
            return False
        current = self.get(lead_id)
        if not current or current.get("source") == source:
            return bool(current)
        history = current["stage_history"]
        history.append({"kind": "source", "from": current.get("source"),
                        "to": source, "at": _now(), "by": operator,
                        "reason": "operator set the lead source"})
        try:
            conn = self._connect()
        except Exception:
            return False
        try:
            conn.execute(
                "UPDATE leads SET source = ?, stage_history = ?, "
                "updated_at = ? WHERE lead_id = ?",
                (source, json.dumps(history, ensure_ascii=False),
                 _now(), str(lead_id)))
            conn.commit()
            return True
        except Exception:
            return False
        finally:
            try:
                conn.close()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# DERIVED, TRANSPARENT lead intelligence (computed, never stored)
# ---------------------------------------------------------------------------

def _fields_known(state_fields: Dict[str, Any]) -> Dict[str, bool]:
    known = {}
    for key in ("budget", "block", "size", "purpose", "timeline"):
        entry = (state_fields or {}).get(key) or {}
        known[key] = entry.get("status") not in (None, "unknown") and \
            entry.get("value") not in (None, "", {})
    return known


def _summary_numbers(conversation_log, session_id: str):
    turns = conversation_log.transcript(session_id)
    escalations = sum(1 for t in turns if t.get("escalation"))
    return {
        "turns": len(turns),
        "escalations": escalations,
        "last_activity": turns[-1]["created_at"] if turns else None,
        "last_dealer_message":
            turns[-1]["dealer_message"] if turns else None,
    }


def temperature_of(fields_known: Dict[str], last_activity,
                   unresolved_escalation: bool,
                   now: Optional[datetime] = None):
    """The transparent temperature. The rule is the display."""
    now = now or datetime.now(timezone.utc)
    known = sum(1 for value in fields_known.values() if value)
    last = _parse(last_activity)
    recent = bool(last and (now - last) <=
                  timedelta(hours=RECENT_WINDOW_HOURS))
    if known >= 4 and recent and not unresolved_escalation:
        return "HOT"
    if known >= 2 or (recent and known >= 1):
        return "WARM"
    return "COLD"


TEMPERATURE_RULE = (
    "HOT: 4-5 qualification fields known, activity within %d hours, and "
    "no unresolved escalation. WARM: 2-3 fields known, or recent activity "
    "with incomplete qualification. COLD: 0-1 fields known, or no recent "
    "activity. This is a transparent qualification-progress indicator, "
    "not a prediction of intent." % RECENT_WINDOW_HOURS
)


def score_lead(fields_known: Dict[str], last_activity,
               unresolved_escalation: bool,
               now: Optional[datetime] = None) -> Dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    last = _parse(last_activity)
    recent = bool(last and (now - last) <=
                  timedelta(hours=RECENT_WINDOW_HOURS))
    reasons, missing = [], []
    for field in ("budget", "block", "size", "purpose", "timeline"):
        if fields_known.get(field):
            reasons.append("%s known (+%d)" % (field.title(),
                                               SCORE_WEIGHTS[field]))
        else:
            missing.append(field)
    score = sum(SCORE_WEIGHTS[f] for f in
                ("budget", "block", "size", "purpose", "timeline")
                if fields_known.get(f))
    if recent:
        score += SCORE_WEIGHTS["recent_activity"]
        reasons.append("recent activity (+10)")
    else:
        missing.append("recent activity")
    if not unresolved_escalation:
        score += SCORE_WEIGHTS["no_unresolved_escalation"]
        reasons.append("no unresolved escalation (+10)")
    else:
        missing.append("resolved escalation")
    return {
        "score": score,
        "reasons": reasons,
        "missing": missing,
        "formula": "budget 20 + block 15 + size 15 + purpose 15 + "
                   "timeline 15 + recent activity 10 + no unresolved "
                   "escalation 10 (a transparent progress score, not a "
                   "conversion prediction)",
    }


def suggest_stage(route: Optional[str], fields_known: Dict[str],
                  escalated: bool, taken_over: bool) -> str:
    """A SUGGESTION only; the operator approves every change except the
    two automatic flags (escalated / taken over)."""
    if escalated:
        return "ESCALATED"
    if taken_over:
        return "TAKEN_OVER"
    known = sum(1 for value in fields_known.values() if value)
    if route in ("exact", "alternative") and known >= 3:
        return "QUALIFIED"
    if route == "clarify" or known >= 1:
        return "QUALIFYING"
    return "NEW"


def routing_suggestion(temperature: str, escalated: bool, unmet: bool,
                       taken_over: bool) -> str:
    if escalated:
        return "Human review required"
    if taken_over:
        return "Operator owns conversation"
    if unmet:
        return "Review inventory gap"
    if temperature == "HOT":
        return "Contact today"
    if temperature == "WARM":
        return "Follow up within 48 hours"
    return "Nurture later"


def _conversation_summary(turns: int, fields_known: Dict[str],
                          route: Optional[str], escalations: int) -> str:
    parts = ["%d exchange%s recorded" % (turns, "s" if turns != 1 else "")]
    stated = [key for key in ("size", "block", "budget", "purpose",
                              "timeline") if fields_known.get(key)]
    if stated:
        parts.append("stated: " + ", ".join(stated))
    else:
        parts.append("no requirements stated yet")
    if route:
        parts.append("last application route: " + route)
    if escalations:
        parts.append("%d escalation%s" % (escalations,
                                          "s" if escalations != 1 else ""))
    return "; ".join(parts) + "."


def lead_view(lead_id: str, *, pipeline: LeadPipelineStore,
              conversation_log, lead_state_store) -> Optional[Dict[str, Any]]:
    """The merged, derived lead view served to the UI."""
    record = pipeline.get(lead_id)
    if not record:
        return None

    state = lead_state_store.load(lead_id)
    fields = _fields_known((state.to_dict() or {}).get("fields", {}))
    numbers = _summary_numbers(conversation_log, lead_id)
    taken_over = bool(lead_state_store.taken_over(lead_id))

    now = datetime.now(timezone.utc)
    last = _parse(numbers["last_activity"])
    days_since = (now - last).days if last else None

    # an escalation is "unresolved" while the lead still sits in the
    # ESCALATED stage (the operator moves it on after the review)
    unresolved_escalation = record["stage"] == "ESCALATED"
    temperature = temperature_of(fields, numbers["last_activity"],
                                 unresolved_escalation, now)
    score = score_lead(fields, numbers["last_activity"],
                       unresolved_escalation, now)

    due = _parse(record.get("follow_up_due_at"))
    follow_up = {
        "due_at": record.get("follow_up_due_at"),
        "overdue": bool(due and due < now),
        "due_today": bool(due and due.date() == now.date()),
        "due_this_week": bool(due and now < due <=
                              now + timedelta(days=7)),
    }

    # the follow-up queue reason (first match wins)
    reason = None
    if record["stage"] == "ESCALATED":
        reason = "escalated - human review required"
    elif follow_up["overdue"]:
        reason = "follow-up overdue"
    elif follow_up["due_today"]:
        reason = "follow-up due today"
    elif days_since is not None and days_since >= NO_ACTIVITY_DAYS:
        reason = "no activity for %d days" % days_since
    elif follow_up["due_this_week"]:
        reason = "follow-up due this week"

    view = dict(record)
    view.update({
        "temperature": temperature,
        "temperature_rule": TEMPERATURE_RULE,
        "score": score,
        "routing": routing_suggestion(temperature,
                                      unresolved_escalation,
                                      _has_unmet(conversation_log, lead_id),
                                      taken_over),
        "suggested_stage": suggest_stage(
            _last_route(conversation_log, lead_id), fields,
            unresolved_escalation, taken_over),
        "fields_known": fields,
        "requirements": (state.to_dict() or {}).get("fields", {}),
        "turns": numbers["turns"],
        "escalation_count": numbers["escalations"],
        "last_activity_at": numbers["last_activity"],
        "days_since_activity": days_since,
        "taken_over": taken_over,
        "conversation_summary": _conversation_summary(
            numbers["turns"], fields,
            _last_route(conversation_log, lead_id),
            numbers["escalations"]),
        "follow_up": follow_up,
        "follow_up_reason": reason,
        "unmet_demand": _has_unmet(conversation_log, lead_id),
        "last_dealer_message": numbers["last_dealer_message"],
    })
    return view


def _last_route(conversation_log, session_id: str):
    turns = conversation_log.transcript(session_id)
    return turns[-1]["route"] if turns else None


def _has_unmet(conversation_log, session_id: str) -> bool:
    turns = conversation_log.transcript(session_id)
    # a non-exact last turn with a stated requirement is the honest
    # unmet signal we already record per turn; the conversation log
    # keeps the routes, so a thin/alternative ending means the ask was
    # not fully met
    return bool(turns) and turns[-1]["route"] != "exact"


# ---------------------------------------------------------------------------
# the deterministic follow-up DRAFT (a draft only - a human acts on it)
# ---------------------------------------------------------------------------

def draft_follow_up(view: Dict[str, Any]) -> Dict[str, Any]:
    """A safe, non-committal follow-up draft assembled ONLY from what
    the conversation already established. No price, no availability
    promise, no pressure, no private data, no numbers beyond the
    stated size. Nothing is sent - ever - by this system."""
    fields = view.get("fields_known") or {}
    parts = ["Thank you for your interest in Faisal Hills."]
    if fields.get("size") or fields.get("block"):
        wanted = []
        if fields.get("size"):
            wanted.append("the plot size you asked about")
        if fields.get("block"):
            wanted.append("your preferred block")
        parts.append("We are reviewing current options for " +
                     " and ".join(wanted) +
                     " and will share verified details once our team "
                     "confirms them.")
    else:
        parts.append("To find you the right plot, could you share the "
                     "size and block you have in mind?")
    missing = [key for key in ("size", "block", "budget", "purpose",
                               "timeline") if not fields.get(key)]
    if "budget" in missing:
        parts.append("It would also help to know your budget range, so "
                     "we only bring you options within it.")
    parts.append("No price or availability is confirmed until a member "
                 "of our team verifies it with you personally.")
    text = " ".join(parts)

    return {
        "draft": text,
        "reason": view.get("follow_up_reason") or "operator work queue",
        "evidence": {
            "fields_known": sorted(k for k, v in fields.items() if v),
            "turns": view.get("turns"),
            "last_activity_at": view.get("last_activity_at"),
            "stated_only": "the draft uses only requirements the "
                           "customer stated; it quotes no price, "
                           "availability, plot or market statistic",
        },
        "approval": {
            "required": True,
            "note": "Human approval required. Draft only - nothing was "
                    "sent.",
        },
    }
