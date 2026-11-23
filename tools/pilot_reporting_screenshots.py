"""Pilot-reporting screenshots: the Reports page in both themes, the
lead drawer with source + feedback, mobile reports. Real Chrome, real
server, SYNTHETIC demo data (FH_MASTER_PATH -> demo inventory),
mirrored into the repo."""

from __future__ import annotations

import http.server
import json
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote

ROOT = Path(r"D:\AI-Projects\laya-gateway")
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

SCRATCH = Path(r"D:\FaisalHillsAILeadDesk\test-artifacts\pr_shots")
from m12_screenshots import CHROME, Handler, crop  # noqa: E402

OUT = Path(r"D:\FaisalHillsAILeadDesk\screenshots\pilot_reporting")
MIRROR = ROOT / "docs" / "reports" / "ui" / "pilot_reporting"

TURNS = ["5 marla in block C around 80 lakh"]
ARM_RAIL = ("function(){var t=setInterval(function(){var b=document."
            "querySelector('#rail-list .rail-button');if(b){clearInterval(t);"
            "b.click();}},120);return 1;}")
ARM_DRAWER = ("function(){var t=setInterval(function(){var b=document."
              "getElementById('lead-details-open');"
              "if(b&&!b.hidden){clearInterval(t);b.click();}},120);return 1;}")
ARM_REPORTS = ("function(){var t=setInterval(function(){var b=document."
               "querySelector(\".nav-item[data-view='reports']\");"
               "if(b){clearInterval(t);b.click();}},120);return 1;}")
LIGHT = ("function(){if(document.documentElement.getAttribute('data-theme')"
         "!=='light')document.getElementById('theme-toggle').click();return 1;}")


def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]
    s.close(); return p


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    MIRROR.mkdir(parents=True, exist_ok=True)
    SCRATCH.mkdir(parents=True, exist_ok=True)
    app_port, harness_port = free_port(), free_port()

    env = dict(os.environ)
    env["FH_MASTER_PATH"] = str(ROOT / "demo" / "sample_inventory.jsonl")
    env["M11_STATE_DB"] = str(SCRATCH / "state.db")
    env["M11_DEMAND_DB"] = str(SCRATCH / "demand.db")
    env["M12_LOG_DB"] = str(SCRATCH / "log.db")
    env["LEAD_PIPELINE_DB"] = str(SCRATCH / "pipeline.db")
    env["PILOT_FEEDBACK_DB"] = str(SCRATCH / "feedback.db")
    env["DB_PATH"] = str(SCRATCH / "faisal_demo.db")
    subprocess.run([sys.executable, "-c",
                    "import app.server as s; s.init_app_db()"],
                   cwd=str(ROOT), env=env, capture_output=True, timeout=120)
    app = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.server:app",
         "--host", "127.0.0.1", "--port", str(app_port)],
        cwd=str(ROOT), env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    harness = http.server.HTTPServer(("127.0.0.1", harness_port), Handler)
    harness.app_url = "http://127.0.0.1:%d/operator" % app_port
    threading.Thread(target=harness.serve_forever, daemon=True).start()

    base = "http://127.0.0.1:%d" % app_port

    def post(path, payload):
        req = urllib.request.Request(
            base + path, data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        urllib.request.urlopen(req, timeout=30).read()

    shots = [
        ("report-dark", 1440, 900, None),
        ("report-light", 1440, 900, LIGHT),
        ("drawer-feedback", 1440, 900, None),
        ("report-mobile", 390, 844, None),
    ]
    try:
        for _ in range(60):
            try:
                urllib.request.urlopen(base + "/health", timeout=2).read()
                break
            except Exception:
                time.sleep(0.5)

        # seed one demo lead with actions + feedback so the report shows
        # real (synthetic) numbers
        post("/api/conversation", {"session_id": "shot-demo",
                                   "message": "5 marla in block C around 80 lakh"})
        post("/api/conversation/shot-demo/draft-action", {"action": "sent"})
        post("/api/leads-pipeline/shot-demo/source", {"source": "WEBSITE"})
        post("/api/pilot-feedback/shot-demo", {
            "quality": "USEFUL", "grounding": "GROUNDED",
            "time_saved": "MEDIUM", "would_send": "YES", "issue": "NONE",
            "note": "Customer accepted the band."})
        post("/api/conversation", {"session_id": "shot-thin",
                                   "message": "10 marla in block C"})
        post("/api/leads-pipeline/shot-thin/source", {"source": "REFERRAL"})

        plans = {
            "report-dark": [{"do": "eval", "script": ARM_REPORTS},
                            {"do": "wait", "ms": 2600}],
            "report-light": [{"do": "eval", "script": ARM_REPORTS},
                             {"do": "wait", "ms": 2600}],
            "drawer-feedback": [{"do": "eval", "script": ARM_RAIL},
                                {"do": "wait", "ms": 2200},
                                {"do": "eval", "script": ARM_DRAWER},
                                {"do": "wait", "ms": 2200},
                                {"do": "eval", "script":
                                 "function(){var b=[].slice.call("
                                 "document.querySelectorAll("
                                 "'#drawer-body button')).filter(function(x){"
                                 "return x.textContent==='Save feedback';})[0];"
                                 "if(b)b.click();return 1;}"},
                                {"do": "wait", "ms": 1600}],
            "report-mobile": [{"do": "eval", "script": ARM_REPORTS},
                              {"do": "wait", "ms": 2600}],
        }
        for name, width, height, theme in shots:
            plan = ([{"do": "eval", "script": theme}] if theme else []) + \
                plans[name]
            frame, window = "", (width, height)
            if width < 500:
                frame = "&frame=%dx%d" % (width, height)
                window = (500, height)
            url = ("http://127.0.0.1:%d/harness?plan=%s%s"
                   % (harness_port, quote(json.dumps(plan)), frame))
            target = OUT / ("%s-%dx%d.png" % (name, width, height))
            cmd = [CHROME, "--headless=new", "--disable-gpu", "--no-sandbox",
                   "--disable-web-security",
                   "--window-size=%d,%d" % window,
                   "--virtual-time-budget=26000",
                   "--screenshot=" + str(target),
                   "--user-data-dir=" + str(SCRATCH / ("p_" + name)), url]
            if theme:
                cmd.insert(3, "--blink-settings=preferredColorScheme=0")
            subprocess.run(cmd, capture_output=True, timeout=240)
            if width < 500 and target.exists():
                crop(target, width, height)
            if target.exists():
                shutil.copy2(target, MIRROR / target.name)
            print("%-18s -> %s %d" % (name, target.exists(),
                                      target.stat().st_size
                                      if target.exists() else 0))
    finally:
        app.terminate()
        harness.shutdown()


if __name__ == "__main__":
    main()
