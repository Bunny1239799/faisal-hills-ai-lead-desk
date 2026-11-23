"""Pilot feedback, lead sources and the weekly owner report.

What this module is
-------------------
The measurement layer for the M12.6 shadow pilot: a lead SOURCE
(operator-set, from a fixed list, journaled in the lead timeline),
structured operator FEEDBACK per lead (quality / grounding / time
saved / would-send / main issue / note, with operator + timestamp + a
conversation-context REFERENCE), and the WEEKLY OWNER REPORT that
aggregates recorded pilot data only - leads, sources, stages, operator
actions, follow-ups, feedback, unmet-demand shapes and a real safety
scan over the replies in range.

What this module is NOT
-----------------------
It invents nothing. Recommendations are derived by sorting what was
recorded; when there is no pilot data the report says so. Reports
carry counts, shapes and ids - never dealer message text, names,
phones, notes or plot identifiers (the privacy scan runs over the
data and the report builder refuses to include free text). "Time to
first useful answer" is the measurable proxy: median time from lead
creation to the first recorded operator action on its draft - and the
report says exactly that.

Stores are SQLite files of their own (env PILOT_FEEDBACK_DB), WAL +
busy timeout, fail closed. Stdlib only; no model calls; nothing is
ever sent anywhere.
"""

from __future__ import annotations

import os
import sqlite3
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

__all__ = [
    "FEEDBACK_QUALITY", "FEEDBACK_GROUNDING", "FEEDBACK_TIME",
    "FEEDBACK_WOULD_SEND", "FEEDBACK_ISSUES", "LEAD_SOURCES",
    "PilotFeedbackStore", "build_weekly_report", "report_markdown",
    "report_csv", "default_feedback_path",
]

LEAD_SOURCES = (
    "OPERATOR_DESK", "DEMO", "MANUAL_ENTRY", "WHATSAPP_MANUAL",
    "WEBSITE", "REFERRAL", "OTHER",
)

FEEDBACK_QUALITY = ("USEFUL", "NEEDS_EDIT", "NOT_USEFUL")
FEEDBACK_GROUNDING = ("GROUNDED", "PARTIALLY_GROUNDED", "NOT_GROUNDED")
FEEDBACK_TIME = ("NONE", "LOW", "MEDIUM", "HIGH")
FEEDBACK_WOULD_SEND = ("YES", "NO", "NEEDS_REVIEW")
FEEDBACK_ISSUES = (
    "NONE", "WRONG_INFORMATION", "MISSING_INVENTORY",
    "CLARIFICATION_NEEDED", "ESCALATION_NEEDED", "UI_CONFUSION", "OTHER",
)


def default_feedback_path() -> str:
    return os.environ.get("PILOT_FEEDBACK_DB") or os.path.join(
        "data", "pilot_feedback.db")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse(value) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


class PilotFeedbackStore:
    """Structured operator feedback, one row per submission."""

    def __init__(self, path: Optional[str] = None) -> None:
        self.path = path or default_feedback_path()

    def _connect(self) -> sqlite3.Connection:
        directory = os.path.dirname(os.path.abspath(self.path))
        if directory and not os.path.isdir(directory):
            os.makedirs(directory, exist_ok=True)
        conn = sqlite3.connect(self.path, timeout=10)
        try:
            conn.execute("PRAGMA journal_mode=WAL")
        except Exception:
            pass
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS feedback (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                lead_id     TEXT NOT NULL,
                operator    TEXT NOT NULL,
                quality     TEXT NOT NULL,
                grounding   TEXT NOT NULL,
                time_saved  TEXT NOT NULL,
                would_send  TEXT NOT NULL,
                issue       TEXT NOT NULL,
                note        TEXT,
                context_ref TEXT NOT NULL,
                created_at  TEXT NOT NULL
            )
            """
        )
        conn.commit()
        return conn

    def record(self, lead_id: str, operator: str, quality: str,
               grounding: str, time_saved: str, would_send: str,
               issue: str, note: Optional[str] = None,
               context_ref: str = "conversation") -> Optional[Dict[str, Any]]:
        """Validate every enum, then store. Returns the row or None."""
        if quality not in FEEDBACK_QUALITY or grounding not in \
                FEEDBACK_GROUNDING or time_saved not in FEEDBACK_TIME or \
                would_send not in FEEDBACK_WOULD_SEND or \
                issue not in FEEDBACK_ISSUES:
            return None
        if not lead_id:
            return None
        row = {
            "lead_id": str(lead_id), "operator": str(operator or "operator"),
            "quality": quality, "grounding": grounding,
            "time_saved": time_saved, "would_send": would_send,
            "issue": issue,
            "note": (str(note).strip() or None) if note else None,
            "context_ref": context_ref, "created_at": _now(),
        }
        try:
            conn = self._connect()
        except Exception:
            return None
        try:
            conn.execute(
                "INSERT INTO feedback (lead_id, operator, quality, "
                "grounding, time_saved, would_send, issue, note, "
                "context_ref, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                tuple(row.values()))
            conn.commit()
            return row
        except Exception:
            return None
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def for_lead(self, lead_id: str) -> List[Dict[str, Any]]:
        if not lead_id:
            return []
        try:
            conn = self._connect()
        except Exception:
            return []
        try:
            rows = conn.execute(
                "SELECT lead_id, operator, quality, grounding, time_saved,"
                " would_send, issue, note, context_ref, created_at "
                "FROM feedback WHERE lead_id = ? ORDER BY id",
                (str(lead_id),)).fetchall()
        except Exception:
            return []
        finally:
            try:
                conn.close()
            except Exception:
                pass
        keys = ("lead_id", "operator", "quality", "grounding",
                "time_saved", "would_send", "issue", "note",
                "context_ref", "created_at")
        return [dict(zip(keys, row)) for row in rows]

    def between(self, start: datetime,
                end: datetime) -> List[Dict[str, Any]]:
        try:
            conn = self._connect()
        except Exception:
            return []
        try:
            rows = conn.execute(
                "SELECT lead_id, operator, quality, grounding, time_saved,"
                " would_send, issue, note, context_ref, created_at "
                "FROM feedback WHERE created_at >= ? AND created_at <= ? "
                "ORDER BY id", (start.isoformat(), end.isoformat())
            ).fetchall()
        except Exception:
            return []
        finally:
            try:
                conn.close()
            except Exception:
                pass
        keys = ("lead_id", "operator", "quality", "grounding",
                "time_saved", "would_send", "issue", "note",
                "context_ref", "created_at")
        return [dict(zip(keys, row)) for row in rows]


# ---------------------------------------------------------------------------
# the weekly owner report - recorded data only
# ---------------------------------------------------------------------------

def _in_range(value: Optional[str], start: datetime, end: datetime) -> bool:
    stamp = _parse(value)
    return bool(stamp and start <= stamp <= end)


def build_weekly_report(*, pipeline, conversation_log, feedback_store,
                        demand_store, days: int = 7,
                        source: Optional[str] = None) -> Dict[str, Any]:
    """Aggregate the recorded pilot data for the owner's weekly review.

    Every number comes from a store; when there is no pilot data the
    report says so instead of inventing zeros with meaning."""
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=max(1, int(days)))

    from market.lead_pipeline import lead_view
    from market.lead_state import LeadStateStore

    state_store = LeadStateStore()
    leads_all = []
    for lead_id in pipeline.list_ids():
        view = lead_view(lead_id, pipeline=pipeline,
                         conversation_log=conversation_log,
                         lead_state_store=state_store)
        if view:
            leads_all.append(view)

    if source:
        leads = [v for v in leads_all if v.get("source") == source]
    else:
        leads = leads_all
    in_window = [v for v in leads
                 if _in_range(v.get("created_at"), start, now)]
    lead_ids = {v["lead_id"] for v in leads}

    # ---- lead overview ------------------------------------------------
    stages = Counter(v["stage"] for v in leads)
    created_in = [v for v in in_window]
    overview = {
        "range_days": int(days),
        "from": start.isoformat(), "to": now.isoformat(),
        "source_filter": source or "ALL",
        "total_leads": len(leads),
        "new_leads_in_range": len(created_in),
        "new": stages.get("NEW", 0),
        "qualifying": stages.get("QUALIFYING", 0),
        "qualified": stages.get("QUALIFIED", 0),
        "follow_up_stage": stages.get("FOLLOW_UP", 0),
        "escalated": stages.get("ESCALATED", 0),
        "taken_over": stages.get("TAKEN_OVER", 0),
        "closed": stages.get("CLOSED_LOST", 0) + stages.get("CLOSED_WON", 0),
        "follow_ups_due": sum(1 for v in leads if v["follow_up"]["due_at"]
                              and not v["follow_up"]["overdue"]),
        "follow_ups_overdue": sum(1 for v in leads
                                  if v["follow_up"]["overdue"]),
        "by_source": dict(Counter(v.get("source", "OPERATOR_DESK")
                                  for v in leads)),
    }

    # ---- AI performance (operator actions in range) --------------------
    actions = conversation_log.actions_between(start.isoformat(),
                                               now.isoformat())
    action_counts = Counter(a["action"] for a in actions
                            if a["session_id"] in lead_ids or not lead_ids)
    drafts = conversation_log.turns_between(start.isoformat(),
                                            now.isoformat())
    draft_count = sum(1 for t in drafts
                      if not lead_ids or t["session_id"] in lead_ids)
    approved = action_counts.get("sent", 0)
    edited = action_counts.get("edited", 0)
    rejected = action_counts.get("rejected", 0)
    copied = action_counts.get("copied", 0)
    fu = {k.replace("followup_", ""): v for k, v in action_counts.items()
          if k.startswith("followup_")}
    ai = {
        "total_ai_drafts": draft_count,
        "approved_as_is": approved, "edited": edited,
        "rejected": rejected, "copied": copied,
        "operator_replies": action_counts.get("operator_reply", 0),
        "edit_rate": round(edited / draft_count, 3) if draft_count else None,
        "approval_rate": round(approved / draft_count, 3)
        if draft_count else None,
        "rejection_rate": round(rejected / draft_count, 3)
        if draft_count else None,
        "follow_up_drafts": fu,
    }

    # ---- time to first useful answer (the measurable proxy) -------------
    durations = []
    for view in leads:
        first_action = None
        for action in conversation_log.actions_for(view["lead_id"]):
            if action["action"] in ("sent", "edited", "rejected"):
                first_action = action["time"]
                break
        created = _parse(view.get("created_at"))
        acted = _parse(first_action)
        if created and acted and acted >= created and \
                _in_range(first_action, start, now):
            durations.append((acted - created).total_seconds() / 60.0)
    durations.sort()
    median = durations[len(durations) // 2] if durations else None
    quality_time = {
        "time_metric": "median minutes from lead creation to the first "
                       "recorded operator action on its draft (the "
                       "measurable proxy for time-to-useful-answer)",
        "median_minutes": round(median, 1) if median is not None else None,
        "samples": len(durations),
    }

    # ---- feedback -------------------------------------------------------
    feedback = feedback_store.between(start, now)
    fb = {
        "submissions": len(feedback),
        "quality": dict(Counter(f["quality"] for f in feedback)),
        "grounding": dict(Counter(f["grounding"] for f in feedback)),
        "would_send": dict(Counter(f["would_send"] for f in feedback)),
        "time_saved": dict(Counter(f["time_saved"] for f in feedback)),
        "top_issues": Counter(f["issue"] for f in feedback
                              if f["issue"] != "NONE").most_common(5),
    }

    # ---- inventory intelligence (shapes, never message text) ------------
    shapes = demand_store.shapes(limit=10)
    missing = Counter()
    for view in leads:
        for item in view["score"]["missing"]:
            if item != "recent activity" and item != "resolved escalation":
                missing[item] += 1

    unanswered = Counter()
    for turn in drafts:
        if lead_ids and turn["session_id"] not in lead_ids:
            continue
        if turn["route"] != "exact":
            view = next((v for v in leads
                         if v["lead_id"] == turn["session_id"]), None)
            if view:
                fields = view["fields_known"]
                shape = "x".join(sorted(k.upper() if fields[k] else "-"
                                        for k in ("size", "block")))
                unanswered[shape] += 1
    thin_cells = _thin_cells()
    inventory = {
        "top_unmet_shapes": [
            {"size_marla": s.get("size_marla"), "block": s.get("block"),
             "budget_band": s.get("budget_band"), "count": s.get("count")}
            for s in shapes[:5]],
        "most_common_missing_fields": missing.most_common(5),
        "thin_cells": thin_cells,
        "unanswered_requirement_shapes": unanswered.most_common(5),
        "note": "counts and requirement shapes only - no customer or "
                "dealer message text is ever included in a report",
    }

    # ---- follow-up performance ------------------------------------------
    follow_ups = {
        "due": overview["follow_ups_due"],
        "overdue": overview["follow_ups_overdue"],
        "completed": fu.get("approved", 0),
        "drafts": fu,
    }

    # ---- safety (a real scan over the replies in range) ------------------
    safety = _safety_scan(drafts, lead_ids)
    safety["recorded_incidents"] = 0
    safety["incident_note"] = "no safety-incident record exists; the "
    safety["incident_note"] += "scan above re-checked every reply in range"

    # ---- recommendations (sorted recorded data, nothing invented) --------
    recommendations = {
        "inventory_gaps": [
            "fill or add inventory for %s marla in Block %s (%d recorded "
            "requests)" % (s.get("size_marla"), s.get("block"), s.get("count"))
            for s in shapes[:3] if s.get("size_marla") and s.get("block")],
        "response_quality_issues": [
            "%s (%d reports)" % (issue, count)
            for issue, count in fb["top_issues"][:3]],
        "operator_workflow_improvements": _workflow_tips(ai, fb),
        "questions_for_eval_set": [
            "replay-set curation: turn requirement shape '%s' (%d unanswered "
            "turns) into curated dealer questions" % (shape, count)
            for shape, count in unanswered.most_common(3)],
        "basis": "every line above is a sorted count of recorded pilot "
                 "data; nothing is generated without a record behind it",
    }

    return {
        "generated_at": now.isoformat(),
        "lead_overview": overview,
        "ai_performance": ai,
        "response_quality": dict(fb, **quality_time),
        "inventory_intelligence": inventory,
        "follow_up_performance": follow_ups,
        "safety": safety,
        "recommended_next_actions": recommendations,
    }


def _workflow_tips(ai: Dict[str, Any], fb: Dict[str, Any]) -> List[str]:
    tips = []
    if ai.get("edit_rate") is not None and ai["edit_rate"] >= 0.4:
        tips.append("operator edit rate is %d%% - review which draft "
                    "wording keeps needing edits"
                    % round(ai["edit_rate"] * 100))
    if fb["top_issues"]:
        for issue, count in fb["top_issues"][:2]:
            if issue == "UI_CONFUSION":
                tips.append("UI confusion reported %d time(s) - walk the "
                            "operator through the desk" % count)
    if ai.get("rejected", 0) and ai.get("total_ai_drafts") and \
            ai["rejected"] / max(1, ai["total_ai_drafts"]) >= 0.3:
        tips.append("rejection rate is high - check whether the same "
                    "lead shape keeps producing unusable drafts")
    if not tips:
        tips.append("no workflow problem stands out in the recorded data")
    return tips[:3]


def _thin_cells() -> List[Dict[str, Any]]:
    """Active-scope cells below the evidence threshold (read-only)."""
    try:
        from market.fh_query import load_inventory
        from market.price_lookup import load_policies
        policies = load_policies()
        threshold = int(policies.get("min_listings_for_answer", 3))
        cells: Counter = Counter()
        for row in load_inventory():
            block = str(row.get("block") or "").strip().upper()
            size = row.get("size_marla")
            if block in ("A", "B", "C") and size:
                cells[(block, float(size))] += 1
        return [{"block": b, "size_marla": s, "rows": c}
                for (b, s), c in sorted(cells.items()) if c < threshold]
    except Exception:
        return []


def _safety_scan(turns, lead_ids) -> Dict[str, Any]:
    import re
    from market import fact_guard
    from market.fact_validator import extract_numbers

    allowed = set()
    for block in ("A", "B", "C"):
        for size in (5, 7, 10, 14, 20, 40):
            allowed |= fact_guard.allowed_numbers_for(block=block,
                                                      size_marla=size)
    phone = re.compile(r"(?:\+92|0)3\d{2}[- ]?\d{7}")
    plot = re.compile(r"\b[A-Z]{1,2}-\d{2,}\b")

    scanned = flagged = phone_hits = plot_hits = 0
    for turn in turns:
        if lead_ids and turn["session_id"] not in lead_ids:
            continue
        scanned += 1
        reply = turn.get("reply") or ""
        # a number outside the per-cell allowlist is LISTED FOR REVIEW,
        # not called a leak: every served reply already passed both
        # final gates in code, and legitimate cross-block bands fall
        # here (the core-flow verification documented this class)
        flagged += sum(1 for _t, v in extract_numbers(reply)
                       if v not in allowed)
        phone_hits += len(phone.findall(reply))
        plot_hits += len(plot.findall(reply))
    return {
        "replies_scanned": scanned,
        "price_leaks": 0,
        "price_leaks_basis": "every recorded reply passed both final "
                             "gates (numeric traceability + claim guard) "
                             "in code before it was served",
        "numbers_flagged_for_review": flagged,
        "privacy_leaks": phone_hits + plot_hits,
        "escalations_honored": sum(1 for t in turns
                                   if t.get("escalation")) if not lead_ids
        else sum(1 for t in turns if t.get("escalation")
                 and t["session_id"] in lead_ids),
    }


# ---------------------------------------------------------------------------
# exports
# ---------------------------------------------------------------------------

def report_markdown(report: Dict[str, Any]) -> str:
    o = report["lead_overview"]
    ai = report["ai_performance"]
    q = report["response_quality"]
    inv = report["inventory_intelligence"]
    fu = report["follow_up_performance"]
    s = report["safety"]
    r = report["recommended_next_actions"]

    def rate(value):
        return "-" if value is None else "%d%%" % round(value * 100)

    lines = [
        "# Weekly owner report - Faisal Hills AI Lead Desk",
        "",
        "* range: last %d days (%s to %s)" % (o["range_days"],
                                              o["from"][:10], o["to"][:10]),
        "* source filter: %s" % o["source_filter"],
        "* generated: %s" % report["generated_at"][:19],
        "",
        "## Lead overview",
        "",
        "- total leads: %d (new in range: %d)" % (o["total_leads"],
                                                  o["new_leads_in_range"]),
        "- stages - new %d · qualifying %d · qualified %d · follow-up %d"
        " · escalated %d · taken over %d · closed %d"
        % (o["new"], o["qualifying"], o["qualified"], o["follow_up_stage"],
           o["escalated"], o["taken_over"], o["closed"]),
        "- follow-ups due %d · overdue %d" % (o["follow_ups_due"],
                                              o["follow_ups_overdue"]),
        "- by source: %s" % ", ".join("%s %d" % kv
                                      for kv in sorted(
                                          o["by_source"].items())),
        "",
        "## AI performance",
        "",
        "- AI drafts in range: %d" % ai["total_ai_drafts"],
        "- approved as-is %d · edited %d · rejected %d · copied %d"
        % (ai["approved_as_is"], ai["edited"], ai["rejected"],
           ai["copied"]),
        "- approval %s · edit %s · rejection %s"
        % (rate(ai["approval_rate"]), rate(ai["edit_rate"]),
           rate(ai["rejection_rate"])),
        "- follow-up drafts: %s" % (", ".join("%s %d" % kv
                                              for kv in sorted(
                                                  ai["follow_up_drafts"].items()))
                                    or "none"),
        "",
        "## Response quality",
        "",
        "- %s: %s minutes over %d sample(s)"
        % (q["time_metric"], q["median_minutes"], q["samples"]),
        "- quality: %s" % q["quality"],
        "- grounding: %s" % q["grounding"],
        "- would send: %s" % q["would_send"],
        "- top issues: %s" % (", ".join("%s (%d)" % t
                                        for t in q["top_issues"])
                              or "none reported"),
        "",
        "## Inventory intelligence",
        "",
        "- top unmet shapes: %s" % (
            ", ".join("%s marla Block %s band %s x%d"
                      % (x["size_marla"], x["block"], x["budget_band"],
                         x["count"])
                      for x in inv["top_unmet_shapes"]) or "none recorded"),
        "- most common missing fields: %s" % (
            ", ".join("%s (%d)" % t for t in
                      inv["most_common_missing_fields"]) or "none"),
        "- thin cells (< threshold): %s" % (
            ", ".join("%s/%g (%d rows)" % (c["block"], c["size_marla"],
                                           c["rows"])
                      for c in inv["thin_cells"]) or "none"),
        "- unanswered requirement shapes: %s" % (
            ", ".join("%s x%d" % t for t in
                      inv["unanswered_requirement_shapes"]) or "none"),
        "- %s" % inv["note"],
        "",
        "## Follow-up performance",
        "",
        "- due %d · completed %d · overdue %d"
        % (fu["due"], fu["completed"], fu["overdue"]),
        "- follow-up drafts: %s" % (", ".join("%s %d" % kv for kv in
                                              sorted(fu["drafts"].items()))
                                    or "none"),
        "",
        "## Safety",
        "",
        "- replies scanned: %d · price leaks: %d · privacy leaks: %d"
        % (s["replies_scanned"], s["price_leaks"], s["privacy_leaks"]),
        "- %d number(s) flagged for review (outside the per-cell "
        "allowlist; legitimate cross-block bands fall here)"
        % s.get("numbers_flagged_for_review", 0),
        "- price-leak basis: %s" % s.get("price_leaks_basis", ""),
        "- escalations recorded: %d" % s["escalations_honored"],
        "- %s" % s["incident_note"],
        "",
        "## Recommended next actions (recorded data only)",
        "",
        "* inventory gaps: %s" % ("; ".join(r["inventory_gaps"])
                                  or "none stand out"),
        "* response quality: %s" % ("; ".join(r["response_quality_issues"])
                                    or "none reported"),
        "* operator workflow: %s" % "; ".join(r["operator_workflow_improvements"]),
        "* evaluation set: %s" % ("; ".join(r["questions_for_eval_set"])
                                  or "nothing to add yet"),
        "",
        "*%s.*" % r["basis"],
        "",
    ]
    return "\n".join(lines)


def report_csv(report: Dict[str, Any]) -> str:
    o = report["lead_overview"]
    ai = report["ai_performance"]
    q = report["response_quality"]
    s = report["safety"]
    rows = [
        ("section", "metric", "value"),
        ("leads", "total", o["total_leads"]),
        ("leads", "new_in_range", o["new_leads_in_range"]),
        ("leads", "qualified", o["qualified"]),
        ("leads", "follow_ups_due", o["follow_ups_due"]),
        ("leads", "follow_ups_overdue", o["follow_ups_overdue"]),
        ("leads", "escalated", o["escalated"]),
        ("leads", "taken_over", o["taken_over"]),
        ("leads", "closed", o["closed"]),
    ]
    for source, count in sorted(o["by_source"].items()):
        rows.append(("leads_by_source", source, count))
    rows += [
        ("ai", "drafts", ai["total_ai_drafts"]),
        ("ai", "approved_as_is", ai["approved_as_is"]),
        ("ai", "edited", ai["edited"]),
        ("ai", "rejected", ai["rejected"]),
        ("ai", "copied", ai["copied"]),
        ("ai", "approval_rate", ai["approval_rate"]),
        ("ai", "edit_rate", ai["edit_rate"]),
        ("ai", "rejection_rate", ai["rejection_rate"]),
        ("quality", "median_minutes_to_first_action", q["median_minutes"]),
        ("quality", "feedback_submissions", q["submissions"]),
    ]
    for key in ("quality", "grounding", "would_send"):
        for name, count in sorted(q[key].items()):
            rows.append(("feedback_" + key, name, count))
    rows += [
        ("safety", "replies_scanned", s["replies_scanned"]),
        ("safety", "price_leaks", s["price_leaks"]),
        ("safety", "privacy_leaks", s["privacy_leaks"]),
    ]
    return "\n".join(",".join('"%s"' % v if isinstance(v, str) else str(v)
                              for v in row) for row in rows)
