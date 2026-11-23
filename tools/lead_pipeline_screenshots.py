"""Lead-pipeline screenshots: the pipeline-aware desk, the lead drawer,
and the follow-ups queue in both themes plus mobile. Real Chrome, real
server, output mirrored into the repo."""

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

OUT = Path(r"D:\FaisalHillsAILeadDesk\screenshots\lead_pipeline")
MIRROR = ROOT / "docs" / "reports" / "ui" / "lead_pipeline"
SCRATCH = Path(r"D:\FaisalHillsAILeadDesk\test-artifacts\lp_shots")

TURNS = ["I need a plot", "5 marla", "block C", "around 80 lakh"]
ARM_RAIL = ("function(){var t=setInterval(function(){var b=document."
            "querySelector('#rail-list .rail-button');if(b){clearInterval(t);"
            "b.click();}},120);return 1;}")
ARM_DRAWER = ("function(){var t=setInterval(function(){var b=document."
              "getElementById('lead-details-open');"
              "if(b&&!b.hidden){clearInterval(t);b.click();}},120);return 1;}")
ARM_FQ = ("function(){var t=setInterval(function(){var b=document."
          "querySelector(\".nav-item[data-view='followups']\");"
          "if(b){clearInterval(t);b.click();}},120);return 1;}")
LIGHT = ("function(){if(document.documentElement.getAttribute('data-theme')"
         "!=='light')document.getElementById('theme-toggle').click();return 1;}")

SHOTS = [
    ("desk-lead-badges", 1440, 900, [], None),
    ("drawer-open", 1440, 900, [], None),
    ("followups-dark", 1440, 900, [], None),
    ("followups-light", 1440, 900, [], LIGHT),
    ("followups-mobile", 390, 844, [], None),
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
    app = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.server:app",
         "--host", "127.0.0.1", "--port", str(app_port)],
        cwd=str(ROOT), env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    harness = http.server.HTTPServer(("127.0.0.1", harness_port), Handler)
    harness.app_url = "http://127.0.0.1:%d/operator" % app_port
    threading.Thread(target=harness.serve_forever, daemon=True).start()

    base_plans = {
        "desk-lead-badges": [{"do": "send", "text": t} for t in TURNS] +
            [{"do": "wait", "ms": 1500}],
        "drawer-open": [{"do": "send", "text": t} for t in TURNS] +
            [{"do": "wait", "ms": 1200}, {"do": "eval", "script": ARM_RAIL},
             {"do": "wait", "ms": 2000}, {"do": "eval", "script": ARM_DRAWER},
             {"do": "wait", "ms": 2200}],
        "followups-dark": [{"do": "send", "text": t} for t in TURNS] +
            [{"do": "wait", "ms": 1200}, {"do": "eval", "script": ARM_FQ},
             {"do": "wait", "ms": 2500},
             {"do": "eval", "script":
              "function(){[].slice.call(document.querySelectorAll('.fq-draft'))"
              ".forEach(function(d){d.open=true;});return 1;}"},
             {"do": "wait", "ms": 500}],
        "followups-light": [{"do": "send", "text": t} for t in TURNS] +
            [{"do": "wait", "ms": 1200}, {"do": "eval", "script": ARM_FQ},
             {"do": "wait", "ms": 2500},
             {"do": "eval", "script":
              "function(){[].slice.call(document.querySelectorAll('.fq-draft'))"
              ".forEach(function(d){d.open=true;});return 1;}"},
             {"do": "wait", "ms": 500}],
        "followups-mobile": [{"do": "eval", "script": ARM_FQ},
                             {"do": "wait", "ms": 2500}],
    }

    try:
        for _ in range(60):
            try:
                urllib.request.urlopen(
                    "http://127.0.0.1:%d/health" % app_port, timeout=2).read()
                break
            except Exception:
                time.sleep(0.5)

        for name, width, height, _extra, theme in SHOTS:
            plan = list(base_plans[name])
            if theme:
                plan = [{"do": "eval", "script": theme}] + plan
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
                   "--user-data-dir=" + str(SCRATCH / ("p_" + name)),
                   url]
            if theme:
                cmd.insert(3, "--blink-settings=preferredColorScheme=0")
            subprocess.run(cmd, capture_output=True, timeout=240)
            if width < 500 and target.exists():
                crop(target, width, height)
            if target.exists():
                shutil.copy2(target, MIRROR / target.name)
            print("%-22s -> %s %d" % (name, target.exists(),
                                      target.stat().st_size
                                      if target.exists() else 0))
    finally:
        app.terminate()
        harness.shutdown()


if __name__ == "__main__":
    main()
