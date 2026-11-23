"""Premium UI screenshots - the app shell at desktop/tablet/mobile, in
both themes, plus the map view and a Coming Soon module. Real Chrome,
real server (isolated stores), output mirrored into the repo."""

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

OUT = Path(r"D:\FaisalHillsAILeadDesk\screenshots\premium")
MIRROR = ROOT / "docs" / "reports" / "ui" / "premium_product_ui"
SCRATCH = Path(r"D:\FaisalHillsAILeadDesk\test-artifacts\premium_shots")

NAV_MAP = ("function(){var b=document.querySelector("
           "\".nav-item[data-view='map']\");if(b)b.click();return true;}")
NAV_3D = ("function(){var b=document.querySelector("
          "\".nav-item[data-module='viz3d']\");if(b)b.click();return true;}")
THEME_LIGHT = ("function(){if(document.documentElement.getAttribute("
               "'data-theme')!=='light')"
               "document.getElementById('theme-toggle').click();return true;}")

SHOTS = [
    ("desk-dark", 1440, 900, [], None),
    ("desk-light", 1440, 900, [], THEME_LIGHT),
    ("desk-dark", 1024, 768, [], None),
    ("desk-dark", 390, 844, [], None),
    ("desk-populated-dark", 1440, 900,
     [{"do": "send", "text": "5 marla in block C around 80 lakh"}], None),
    ("desk-populated-light", 1440, 900,
     [{"do": "send", "text": "5 marla in block C around 80 lakh"}], THEME_LIGHT),
    ("map-dark", 1440, 900, [{"do": "eval", "script": NAV_MAP}], None),
    ("map-light", 1440, 900, [{"do": "eval", "script": NAV_MAP}], THEME_LIGHT),
    ("map-mobile", 390, 844, [{"do": "eval", "script": NAV_MAP}], None),
    ("module-3d-dark", 1440, 900, [{"do": "eval", "script": NAV_3D}], None),
    ("escalated-dark", 1440, 900,
     [{"do": "send", "text": "Any discount?"}], None),
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
            full_plan = []
            if theme:
                full_plan.append({"do": "eval", "script": theme})
            full_plan += plan
            if plan and plan[0].get("do") == "send":
                full_plan.append({"do": "wait", "ms": 700})
            full_plan.append({"do": "wait", "ms": 900})

            frame, window = "", (width, height)
            if width < 500:
                frame = "&frame=%dx%d" % (width, height)
                window = (500, height)
            url = ("http://127.0.0.1:%d/harness?plan=%s%s"
                   % (harness_port, quote(json.dumps(full_plan)), frame))
            target = OUT / ("%s-%dx%d.png" % (name, width, height))
            cmd = [CHROME, "--headless=new", "--disable-gpu", "--no-sandbox",
                   "--disable-web-security",
                   "--window-size=%d,%d" % window,
                   "--virtual-time-budget=22000",
                   "--screenshot=" + str(target),
                   "--user-data-dir=" + str(
                       SCRATCH / ("p_" + name + str(width))),
                   url]
            if name.endswith("light"):
                cmd.insert(3, "--blink-settings=preferredColorScheme=0")
            subprocess.run(cmd, capture_output=True, timeout=240)
            if width < 500 and target.exists():
                crop(target, width, height)
            if target.exists():
                shutil.copy2(target, MIRROR / target.name)
            print("%-24s -> %s %d" % (name, target.exists(),
                                      target.stat().st_size
                                      if target.exists() else 0))
    finally:
        app.terminate()
        harness.shutdown()


if __name__ == "__main__":
    main()
