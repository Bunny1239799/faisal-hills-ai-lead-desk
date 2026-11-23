"""Presentation-readiness task - the core-flow verification driver.

Runs the ten required inquiry types against a REAL server (isolated
stores on D:), records the API request/response evidence and the
grounding checks for every turn, and captures a real-browser screenshot
of each inquiry, using the project's own harness (tests/m12_screenshots).

Outputs (all evidence, no judgements hidden in code):
  data/core_flow/core_flow_raw.json    - full per-turn evidence
  docs/reports/core_flow_results.csv   - the required columns
  screenshots -> D:\\FaisalHillsAILeadDesk\\screenshots\\core_flow\\
                 mirrored to docs\\reports\\ui\\core_flow\\
  console summary for the report
"""

from __future__ import annotations

import csv
import http.server
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import quote

ROOT = Path(r"D:\AI-Projects\laya-gateway")
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "tools"))

from m12_screenshots import CHROME, Handler  # noqa: E402
from replay_questions import _allowed_numbers  # noqa: E402
from market.fact_validator import extract_numbers  # noqa: E402

OUT = ROOT / "data" / "core_flow"
SHOTS = Path(r"D:\FaisalHillsAILeadDesk\screenshots\core_flow")
MIRROR = ROOT / "docs" / "reports" / "ui" / "core_flow"
CSV_PATH = ROOT / "docs" / "reports" / "core_flow_results.csv"

_PLOT = re.compile(r"\b[A-Z]{1,2}-\d{2,}\b")
_PHONE = re.compile(r"(?:\+92|0)3\d{2}[- ]?\d{7}\b")

ALLOWED = _allowed_numbers()

# id, language, turns, expected behavior (per the task's ten types)
INQUIRIES = [
    ("01-size-only", "English", ["I want 5 marla plot"],
     "clarification: size captured, block/budget missing"),
    ("02-block-budget", "English", ["5 marla in block C around 80 lakh"],
     "grounded exact/alternative answer with price band and provenance"),
    ("03-vague", "English", ["I need a plot"],
     "clarification: nothing stated yet"),
    ("04-roman-urdu", "Roman Urdu/mixed",
     ["mujhe block C mein 5 marla chahiye 80 lakh ke around"],
     "same grounded answer as the English equivalent (normalizer)"),
    ("05-nonexistent-block", "English", ["5 marla in block Z"],
     "no fabricated inventory; clarify/refuse, never a price"),
    ("06-parked-block", "English", ["5 marla in block D"],
     "parked scope refused/escalated, no price"),
    ("07-thin-cell", "English", ["10 marla in block C price"],
     "thin-data wording, no price statistic"),
    ("08-multi-turn", "English",
     ["I need a plot", "5 marla", "block C", "around 80 lakh"],
     "progressive qualification ending in a grounded answer"),
    ("09-correction", "English",
     ["5 marla in block C", "actually my budget is 60 lakh"],
     "budget corrected with provenance; answer stays grounded"),
    ("10-escalation", "English", ["Any discount?"],
     "escalation to human, no price"),
]


def call(base, method, path, payload=None, query=""):
    data = json.dumps(payload).encode() if payload is not None else \
        (b"" if method == "POST" else None)
    req = urllib.request.Request(
        base + path + query,
        data=data,
        headers={"Content-Type": "application/json"}, method=method)
    try:
        r = urllib.request.urlopen(req, timeout=30)
        return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")


def check_turn(reply):
    numbers = {v for _t, v in extract_numbers(reply)} - ALLOWED
    return {
        "price_leak": sorted(numbers),
        "plot_number_leak": bool(_PLOT.search(reply)),
        "phone_leak": bool(_PHONE.search(reply)),
    }


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    SHOTS.mkdir(parents=True, exist_ok=True)
    MIRROR.mkdir(parents=True, exist_ok=True)

    import socket
    sock = socket.socket(); sock.bind(("127.0.0.1", 0))
    app_port = sock.getsockname()[1]; sock.close()
    sock = socket.socket(); sock.bind(("127.0.0.1", 0))
    harness_port = sock.getsockname()[1]; sock.close()

    env = dict(os.environ)
    env["M11_STATE_DB"] = str(OUT / "state.db")
    env["M11_DEMAND_DB"] = str(OUT / "demand.db")
    env["M12_LOG_DB"] = str(OUT / "log.db")
    app = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.server:app",
         "--host", "127.0.0.1", "--port", str(app_port)],
        cwd=str(ROOT), env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    harness = http.server.HTTPServer(("127.0.0.1", harness_port), Handler)
    harness.app_url = "http://127.0.0.1:%d/operator" % app_port
    threading.Thread(target=harness.serve_forever, daemon=True).start()

    base = "http://127.0.0.1:%d" % app_port
    try:
        for _ in range(60):
            try:
                call(base, "GET", "/health"); break
            except Exception:
                time.sleep(0.5)

        evidence = {"base": base, "inquiries": []}
        rows = []

        # --- the 422 probes (Phase 3 evidence) -----------------------
        s, b = call(base, "POST", "/api/conversation",
                    {"session_id": "p422-a", "message": "I want 5 marla plot"})
        evidence["probe_json_with_message"] = {"status": s, "body": b[:200]}
        s, b = call(base, "POST", "/api/conversation",
                    {"session_id": "p422-b"})
        evidence["probe_json_without_message"] = {"status": s, "body": b[:200]}
        s, b = call(base, "POST", "/api/conversation", query="?session_id=p422-c")
        evidence["probe_query_without_message"] = {"status": s, "body": b[:200]}
        s, b = call(base, "POST", "/api/conversation",
                    query="?session_id=p422-d&message=I+want+5+marla+plot")
        evidence["probe_query_with_message"] = {"status": s, "body": b[:200]}

        # --- the ten inquiries ---------------------------------------
        for inq_id, language, turns, expected in INQUIRIES:
            session = "cf-" + inq_id
            record = {"id": inq_id, "language": language,
                      "expected": expected, "turns": []}
            for index, text in enumerate(turns, start=1):
                status, body = call(base, "POST", "/api/conversation",
                                    {"session_id": session, "message": text})
                data = json.loads(body) if status == 200 else {}
                reply = data.get("reply", "")
                guards = check_turn(reply)
                turn = {
                    "turn": index,
                    "request": {"session_id": session, "message": text},
                    "status": status,
                    "route": data.get("route"),
                    "escalation": data.get("escalation"),
                    "reason": data.get("reason"),
                    "next_action": data.get("next_action"),
                    "verified_options": data.get("verified_options"),
                    "changes_this_turn": [c for c in (data.get("changes") or [])
                                          if c.get("turn") == index],
                    "lead_state_fields": (data.get("lead_state") or {}
                                          ).get("fields"),
                    "unmet_demand": bool(data.get("unmet_demand")),
                    "gates": data.get("gates"),
                    "reply_head": reply[:180],
                    "guards": guards,
                }
                record["turns"].append(turn)

                gates = data.get("gates") or {}
                gates_ok = gates.get("traceability_ok") is True and \
                    gates.get("claim_guard_ok") is True
                # Grounding: the AUTHORITATIVE traceability decision is
                # the product's own M5 validator + M6.1 claim guard. The
                # per-cell allowlist here is a second opinion; when it
                # flags a number the gates passed (a cross-block
                # aggregate band), the gates win and the row says so.
                grounded = status == 200 and \
                    not guards["plot_number_leak"] and \
                    not guards["phone_leak"] and \
                    (not guards["price_leak"] or gates_ok)
                note = ""
                if guards["price_leak"] and gates_ok:
                    note = ("cross-block aggregate numbers (%s) passed the "
                            "product's own traceability and claim gates"
                            % guards["price_leak"])
                rows.append({
                    "inquiry_id": inq_id, "input": text, "language": language,
                    "turn_number": index, "expected_behavior": expected,
                    "actual_behavior": "%s/esc=%s" % (data.get("route"),
                                                      data.get("escalation")),
                    "inventory_used": "%d option(s)" %
                                      len(data.get("verified_options") or []),
                    "recommendation": str((data.get("next_action") or {})
                                          .get("label", ""))[:80],
                    "grounded": grounded,
                    "clarification_needed": data.get("route") == "clarify",
                    "escalation_needed": bool(data.get("escalation")),
                    "privacy_leak": guards["plot_number_leak"] or
                                    guards["phone_leak"],
                    "price_leak": bool(guards["price_leak"]),
                    "fabrication_detected": bool(guards["price_leak"])
                                             and not gates_ok,
                    "result": "OK" if grounded else "FAIL",
                    "notes": note, "screenshot_path": "",
                })

            # browser screenshot of the whole inquiry
            plan = [{"do": "send", "text": t} for t in turns]
            url = ("http://127.0.0.1:%d/harness?plan=%s"
                   % (harness_port, quote(json.dumps(plan))))
            name = "%s-1440x900-light.png" % inq_id
            target = SHOTS / name
            subprocess.run(
                [CHROME, "--headless=new", "--disable-gpu", "--no-sandbox",
                 "--disable-web-security", "--window-size=1440,900",
                 "--virtual-time-budget=25000",
                 "--screenshot=" + str(target),
                 "--user-data-dir=" + str(OUT / ("chrome_" + inq_id)), url],
                capture_output=True, timeout=240)
            shot_rel = ""
            if target.exists():
                shutil.copy2(target, MIRROR / name)
                shot_rel = "docs/reports/ui/core_flow/%s" % name
            for row in rows:
                if row["inquiry_id"] == inq_id:
                    row["screenshot_path"] = shot_rel
            record["screenshot"] = shot_rel
            evidence["inquiries"].append(record)
            print("%-20s route=%s esc=%s shot=%s"
                  % (inq_id, record["turns"][-1]["route"],
                     record["turns"][-1]["escalation"], bool(shot_rel)))

        (OUT / "core_flow_raw.json").write_text(
            json.dumps(evidence, ensure_ascii=False, indent=2),
            encoding="utf-8")
        with CSV_PATH.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        fails = [r for r in rows if r["result"] != "OK"]
        print("turns recorded: %d | FAIL rows: %d | csv: %s"
              % (len(rows), len(fails), CSV_PATH))
    finally:
        app.terminate()
        harness.shutdown()


if __name__ == "__main__":
    main()
