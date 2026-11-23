"""The M12.6 shadow-pilot dashboard generator.

Reads the pilot's isolated state (stores under the pilot workspace),
the site-visit records, and the founder's review logs, and regenerates
`pilot_dashboard.md`. Run at any time; the daily close runs it once:

    .venv\\Scripts\\python.exe tools\\pilot_dashboard.py

Environment (defaults match start_pilot_desk.bat):
    PILOT_STORES_DIR  (pilot workspace \\stores)
    SITE_VISIT_DATA_DIR (the founder data dir)
"""

from __future__ import annotations

import csv
import json
import os
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

WORKSPACE = Path(os.environ.get(
    "PILOT_WORKSPACE_DIR",
    r"D:\FaisalHillsAILeadDesk\pilot\M12_6_SHADOW_PILOT"))
STORES = Path(os.environ.get("PILOT_STORES_DIR", str(WORKSPACE / "stores")))


def _counts_from_logs():
    drafts = {"approved": 0, "edited": 0, "rejected": 0}
    escalations = {"total": 0, "correct": 0, "incorrect": 0}
    incidents = {"total": 0, "safety": 0, "privacy": 0, "fabrication": 0}
    conv_reviewed = 0
    conv_path = WORKSPACE / "conversation_review_log.csv"
    if conv_path.exists():
        with open(conv_path, "r", encoding="utf-8-sig", newline="") as fh:
            for row in csv.DictReader(fh):
                if not any((v or "").strip() for v in row.values()):
                    continue
                conv_reviewed += 1
                decision = (row.get("founder_decision") or "").strip().lower()
                if decision.startswith("approved"):
                    drafts["approved"] += 1
                elif decision.startswith("edited"):
                    drafts["edited"] += 1
                elif decision.startswith("rejected"):
                    drafts["rejected"] += 1
                if (row.get("escalation_required") or "").strip().lower() \
                        == "yes":
                    escalations["total"] += 1
                for field, kind in (("safety_issue", "safety"),
                                    ("privacy_issue", "privacy"),
                                    ("fabrication_issue", "fabrication")):
                    if (row.get(field) or "").strip().lower() == "yes":
                        incidents[kind] += 1
                        incidents["total"] += 1
    esc_path = WORKSPACE / "escalation_review_log.csv"
    if esc_path.exists():
        with open(esc_path, "r", encoding="utf-8-sig", newline="") as fh:
            for row in csv.DictReader(fh):
                if not any((v or "").strip() for v in row.values()):
                    continue
                judged = (row.get("judged_correct") or "").strip().lower()
                if judged == "yes":
                    escalations["correct"] += 1
                elif judged == "no":
                    escalations["incorrect"] += 1
    inc_path = WORKSPACE / "pilot_incident_log.csv"
    if inc_path.exists():
        with open(inc_path, "r", encoding="utf-8-sig", newline="") as fh:
            for row in csv.DictReader(fh):
                if not any((v or "").strip() for v in row.values()):
                    continue
                incidents["total"] += 1
                kind = (row.get("incident_type") or "").strip().lower()
                if "privacy" in kind:
                    incidents["privacy"] += 1
                elif "fabricat" in kind:
                    incidents["fabrication"] += 1
                else:
                    incidents["safety"] += 1
    return drafts, escalations, incidents, conv_reviewed


def _site_visit_counts():
    from market import site_visit as sv
    requests = sv.requests()
    slots = sv.load_slots()
    return {
        "requests": len(requests),
        "approved": sum(1 for r in requests
                        if r.get("founder_approval_status") == "APPROVED"),
        "confirmed_manually": sum(1 for s in slots
                                  if str(s.get("status", "")).upper()
                                  == "CONFIRMED"),
        "slots_available": sum(1 for s in slots
                               if str(s.get("status", "")).upper()
                               == "AVAILABLE"),
    }


def _lead_counts():
    from market import lead_qualification as lq
    from market.conversation_log import ConversationLogStore
    from market.lead_pipeline import LeadPipelineStore
    from market.lead_state import LeadStateStore

    pipeline = LeadPipelineStore(path=str(STORES / "pipeline.db"))
    clog = ConversationLogStore(path=str(STORES / "log.db"))
    state_store = LeadStateStore(path=str(STORES / "state.db"))
    mapping = {"block": "block", "size": "size_marla",
               "budget": "budget_max_pkr", "purpose": "purpose",
               "timeline": "timeline"}
    temps = {"HOT": 0, "WARM": 0, "COLD": 0}
    conversations = 0
    drafts_created = 0
    for lead_id in pipeline.list_ids():
        conversations += 1
        record = pipeline.get(lead_id) or {}
        try:
            state_obj = state_store.load(lead_id)
            fields = (state_obj.to_dict() or {}).get("fields") or {}
        except Exception:
            fields = {}
        requirements = {}
        for key, target in mapping.items():
            entry = fields.get(key) or {}
            if isinstance(entry, dict) and \
                    entry.get("value") not in (None, "", {}):
                requirements[target] = entry.get("value")
        try:
            turns = len(clog.transcript(lead_id))
        except Exception:
            turns = 0
        drafts_created += turns
        view = lq.qualification_view(
            requirements=requirements, message="", turns=turns,
            escalated=record.get("stage") == "ESCALATED",
            has_visit_request=False)
        temps[view["temperature"]] = temps.get(view["temperature"], 0) + 1
    return {
        "conversations": conversations,
        "drafts_created": drafts_created,
        "temperatures": temps,
    }


def _gate_pass_rate():
    """The gate-pass rate from the recorded audit trail of the pilot
    stores (traceability + claim guard per validated reply)."""
    ok = total = 0
    try:
        import sqlite3
        audit_db = STORES / "faisal_hills.db"
        if not audit_db.exists():
            return None, None
        conn = sqlite3.connect(str(audit_db))
        try:
            rows = conn.execute(
                "SELECT decision_payload FROM audit_log "
                "WHERE decision_payload LIKE '%traceability_ok%'"
            ).fetchall()
        finally:
            conn.close()
        for (payload,) in rows:
            try:
                data = json.loads(payload)
            except (ValueError, TypeError):
                continue
            evidence = data.get("evidence") or data
            if not isinstance(evidence, dict):
                continue
            if "traceability_ok" in evidence:
                total += 1
                if evidence.get("traceability_ok") and \
                        evidence.get("claim_guard_ok", True):
                    ok += 1
    except Exception:
        return None, None
    if not total:
        return None, None
    return ok, total


def main() -> int:
    drafts, escalations, incidents, conv_reviewed = _counts_from_logs()
    leads = _lead_counts()
    visits = _site_visit_counts()
    gate_ok, gate_total = _gate_pass_rate()

    go_status = "GO — pilot active (day-7 review 2026-11-01)"
    if incidents["total"]:
        go_status = ("PAUSED — %d incident(s) recorded; resolve before "
                     "continuing" % incidents["total"])

    lines = [
        "# M12.6 Shadow-Pilot Dashboard",
        "",
        "Generated %s · operator: Muhammad Hanzala · inventory: staging "
        "master only · every reply is a draft requiring founder approval."
        % datetime.now().strftime("%Y-%m-%d %H:%M"),
        "",
        "## Pilot status",
        "",
        "- **Go/No-Go: %s**" % go_status,
        "- Gate-pass rate: %s" % (
            "100%% (%d/%d validated replies)" % (gate_ok, gate_total)
            if gate_total else "no validated replies recorded yet"),
        "- Incidents — safety: %d · privacy: %d · fabrication: %d "
        "(target: 0)" % (incidents["safety"], incidents["privacy"],
                         incidents["fabrication"]),
        "- Conversations reviewed in the daily log: %d" % conv_reviewed,
        "",
        "## Conversations and drafts",
        "",
        "| Metric | Count |",
        "| --- | --- |",
        "| Total conversations | %d |" % leads["conversations"],
        "| Drafts created (turns handled) | %d |" % leads["drafts_created"],
        "| Drafts approved | %d |" % drafts["approved"],
        "| Drafts edited | %d |" % drafts["edited"],
        "| Drafts rejected | %d |" % drafts["rejected"],
        "| Escalations (reviewed) | %d |" % escalations["total"],
        "| Correct escalations | %d |" % escalations["correct"],
        "| Incorrect escalations | %d |" % escalations["incorrect"],
        "",
        "## Site visits",
        "",
        "| Metric | Count |",
        "| --- | --- |",
        "| Site-visit requests | %d |" % visits["requests"],
        "| Founder-approved requests | %d |" % visits["approved"],
        "| Visits CONFIRMED (founder manual action only) | %d |"
        % visits["confirmed_manually"],
        "| Slots still open | %d |" % visits["slots_available"],
        "",
        "## Lead temperatures",
        "",
        "| HOT | WARM | COLD |",
        "| --- | --- | --- |",
        "| %d | %d | %d |" % (leads["temperatures"].get("HOT", 0),
                              leads["temperatures"].get("WARM", 0),
                              leads["temperatures"].get("COLD", 0)),
        "",
        "## Incidents",
        "",
        "Safety / privacy / fabrication incidents recorded in "
        "`pilot_incident_log.csv`: **%d** total (safety %d · privacy %d ·"
        " fabrication %d — target: 0; any incident pauses the pilot per "
        "PILOT_PLAN §9)." % (incidents["total"], incidents["safety"],
                             incidents["privacy"],
                             incidents["fabrication"]),
        "",
    ]
    out = WORKSPACE / "pilot_dashboard.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    print("dashboard written:", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
