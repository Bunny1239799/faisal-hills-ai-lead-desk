"""The founder-only lead-pipeline report (pilot feature 1's view).

Builds a privacy-safe markdown report from the recorded lead state:
per lead - temperature, score with the verbatim breakdown, stage,
known/missing requirements, recommended next action and the site-visit
state. No dealer contacts, no raw WhatsApp messages, no private notes.

Usage:
    .venv\\Scripts\\python.exe tools\\founder_pipeline_report.py [out.md]
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from market import lead_qualification as lq  # noqa: E402
from market import site_visit as sv  # noqa: E402


def build() -> str:
    from market.conversation_log import ConversationLogStore
    from market.lead_pipeline import LeadPipelineStore
    from market.lead_state import LeadStateStore

    pipeline = LeadPipelineStore()
    clog = ConversationLogStore()
    state_store = LeadStateStore()
    mapping = {"block": "block", "size": "size_marla",
               "budget": "budget_max_pkr", "purpose": "purpose",
               "timeline": "timeline"}

    lines = [
        "# Founder Lead-Pipeline Report",
        "",
        "Generated %s. Privacy-safe by construction: no dealer contacts,"
        " no raw WhatsApp messages, no private notes." %
        datetime.now().strftime("%Y-%m-%d %H:%M"),
        "",
    ]
    count = 0
    for lead_id in pipeline.list_ids():
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
        turns = len(clog.transcript(lead_id))
        view = lq.qualification_view(
            requirements=requirements,
            message="",
            turns=turns,
            escalated=record.get("stage") == "ESCALATED",
            has_visit_request=sv.has_request_for_lead(lead_id),
        )
        count += 1
        lines += [
            "## %s — %s" % (lead_id, record.get("label", "")),
            "",
            "- Temperature: **%s**  ·  Score: **%d/100**  ·  Stage: %s"
            " (suggested: %s)" % (view["temperature"], view["score"],
                                  record.get("stage"),
                                  view["stage_suggestion"]),
            "- Known requirements: %s" % json.dumps(
                {k: v for k, v in view["known_requirements"].items()
                 if v not in (None, "", [], False)},
                ensure_ascii=False),
            "- Missing requirements: %s" % (
                ", ".join(view["missing_requirements"]) or "none"),
            "- Recommended next action: %s" % view["recommended_next_action"],
            "- Site-visit interest: %s · request on file: %s" % (
                "yes" if view["site_visit_interest"] else "no",
                "yes" if sv.has_request_for_lead(lead_id) else "no"),
            "- Conversation summary: %s" % (record.get("label") or ""),
            "- Last activity: %s" % record.get("updated_at", ""),
            "- Requires founder approval: yes (every draft and every "
            "site-visit confirmation)",
            "",
        ]
    if not count:
        lines += ["No leads recorded yet.", ""]
    return "\n".join(lines)


def main() -> int:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else \
        ROOT / "docs" / "reports" / "founder_pipeline_report.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(build(), encoding="utf-8")
    print("written:", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
