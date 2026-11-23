"""Lead-drawer close-fix screenshots: the moments the bug report names,
in a real browser against an isolated server.

Usage:
    .venv\\Scripts\\python.exe tools\\lead_drawer_fix_screenshots.py before
    .venv\\Scripts\\python.exe tools\\lead_drawer_fix_screenshots.py after

The mode only names the output files; what differs between the two runs
is the CSS in app/static/operator.css (the [hidden] rule), toggled by
hand between the runs. Output: D:\\FaisalHillsAILeadDesk\\screenshots\\
lead_drawer_fix\\<mode>\\, mirrored into docs\\reports\\ui\\lead_drawer_fix\\.
"""

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
from pathlib import Path
from urllib.parse import quote

ROOT = Path(r"D:\AI-Projects\laya-gateway")
sys.path.insert(0, str(ROOT / "tests"))

from m12_screenshots import CHROME, Handler, crop  # noqa: E402

MODE = sys.argv[1] if len(sys.argv) > 1 else "after"
OUT = Path(r"D:\FaisalHillsAILeadDesk\screenshots\lead_drawer_fix") / MODE
MIRROR = ROOT / "docs" / "reports" / "ui" / "lead_drawer_fix" / MODE
SCRATCH = Path(r"D:\FaisalHillsAILeadDesk\test-artifacts\ldfix_shots")

TURNS = ["I need a plot", "5 marla", "block C", "around 80 lakh"]
ARM_RAIL = ("function(){var t=setInterval(function(){var b=document."
            "querySelector('#rail-list .rail-button');if(b){clearInterval(t);"
            "b.click();}},120);return 1;}")
ARM_DRAWER = ("function(){var t=setInterval(function(){var b=document."
              "getElementById('lead-details-open');"
              "if(b&&!b.hidden){clearInterval(t);b.click();}},120);return 1;}")
CLICK_X = ("function(){document.getElementById('drawer-close')"
           ".click();return 1;}")
LIGHT = ("function(){if(document.documentElement.getAttribute('data-theme')"
         "!=='light')document.getElementById('theme-toggle').click();return 1;}")

OPEN_DRAWER = ([{"do": "send", "text": t} for t in TURNS] +
               [{"do": "wait", "ms": 1200}, {"do": "eval", "script": ARM_RAIL},
                {"do": "wait", "ms": 2000}, {"do": "eval", "script": ARM_DRAWER},
                {"do": "wait", "ms": 2200}])

# name, width, height, plan, theme-eval
SHOTS = [
    ("initial-load", 1440, 900, [{"do": "wait", "ms": 900}], None),
    ("after-x", 1440, 900, OPEN_DRAWER + [{"do": "eval", "script": CLICK_X},
                                          {"do": "wait", "ms": 800}], None),
    ("after-x", 1024, 768, OPEN_DRAWER + [{"do": "eval", "script": CLICK_X},
                                          {"do": "wait", "ms": 800}], None),
    ("after-x", 390, 844, OPEN_DRAWER + [{"do": "eval", "script": CLICK_X},
                                         {"do": "wait", "ms": 800}], None),
    ("after-x", 1440, 900, OPEN_DRAWER + [{"do": "eval", "script": CLICK_X},
                                          {"do": "wait", "ms": 800}], LIGHT),
    ("reopened", 1440, 900, OPEN_DRAWER + [{"do": "eval", "script": CLICK_X},
                                           {"do": "wait", "ms": 800},
                                           {"do": "eval", "script": ARM_DRAWER},
                                           {"do": "wait", "ms": 2200}], None),
]


def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]
    s.close(); return p


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    MIRROR.mkdir(parents=True, exist_ok=True)
    SCRATCH.mkdir(parents=True, exist_ok=True)
    app_port, harness_port = free_port(), free_port()

    env = dict(os.environ)
    env["M11_STATE_DB"] = str(SCRATCH / "state.db")
    env["M11_DEMAND_DB"] = str(SCRATCH / "demand.db")
    env["M12_LOG_DB"] = str(SCRATCH / "log.db")
    env["LEAD_PIPELINE_DB"] = str(SCRATCH / "pipeline.db")
    env["PILOT_FEEDBACK_DB"] = str(SCRATCH / "feedback.db")
    app = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.server:app",
         "--host", "127.0.0.1", "--port", str(app_port)],
        cwd=str(ROOT), env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    harness = http.server.HTTPServer(("127.0.0.1", harness_port), Handler)
    harness.app_url = "http://127.0.0.1:%d/operator" % app_port
    threading.Thread(target=harness.serve_forever, daemon=True).start()

    try:
        for _ in range(60):
            try:
                urllib.request.urlopen(
                    "http://127.0.0.1:%d/health" % app_port, timeout=2).read()
                break
            except Exception:
                time.sleep(0.5)

        for name, width, height, plan, theme in SHOTS:
            full_plan = ([{"do": "eval", "script": theme}] if theme else []) \
                + plan
            frame, window = "", (width, height)
            if width < 500:
                frame = "&frame=%dx%d" % (width, height)
                window = (500, height)
            url = ("http://127.0.0.1:%d/harness?plan=%s%s"
                   % (harness_port, quote(json.dumps(full_plan)), frame))
            target = OUT / ("%s-%s-%dx%d%s.png"
                            % (name, MODE, width, height,
                               "-light" if theme else ""))
            cmd = [CHROME, "--headless=new", "--disable-gpu", "--no-sandbox",
                   "--disable-web-security",
                   "--window-size=%d,%d" % window,
                   "--virtual-time-budget=26000",
                   "--screenshot=" + str(target),
                   "--user-data-dir=" + str(
                       SCRATCH / ("p_" + MODE + name + str(width))),
                   url]
            if theme:
                cmd.insert(3, "--blink-settings=preferredColorScheme=0")
            subprocess.run(cmd, capture_output=True, timeout=240)
            if width < 500 and target.exists():
                crop(target, width, height)
            if target.exists():
                shutil.copy2(target, MIRROR / target.name)
            print("%-16s -> %s %d" % (target.name, target.exists(),
                                      target.stat().st_size
                                      if target.exists() else 0))
    finally:
        app.terminate()
        harness.shutdown()


if __name__ == "__main__":
    main()
