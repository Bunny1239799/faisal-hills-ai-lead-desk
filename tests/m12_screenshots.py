"""M12.1 - capture the operator desk states as PNGs into docs\\reports\\ui.

Run with the project venv:

    .venv\\Scripts\\python.exe tests\\m12_screenshots.py

Chrome cannot make a window narrower than 500 dip, so the mobile shots
are taken with a 390x844 **frame** inside the page and the PNG is
cropped to that frame. The crop uses Pillow from the **system** Python
(it is not a project dependency and nothing is added to the project).
"""

from __future__ import annotations

import http.server
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path
from urllib.parse import quote

ROOT = Path(r"D:\AI-Projects\laya-gateway")
OUT = Path(r"D:\FaisalHillsAILeadDesk\screenshots")
MIRROR = ROOT / "docs" / "reports" / "ui" / "m12_1_final"
SCRATCH = Path(r"D:\FaisalHillsAILeadDesk\test-artifacts\screenshots")
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"

sys.path.insert(0, str(ROOT / "tests"))
from m12_browser import HARNESS_HTML, _free_port  # noqa: E402

WIDTHS = [(1440, 900), (1024, 768), (390, 844)]

STATES = {
    "empty": [],
    "clarify": [{"do": "send", "text": "I need a plot"}],
    "exact": [{"do": "send", "text": "5 marla in block C"}],
    "thin": [{"do": "send", "text": "10 marla C block price"}],
    "escalated": [{"do": "send", "text": "Any discount?"}],
    "taken-over": [{"do": "send", "text": "Any discount?"},
                   {"do": "click", "selector": "#take-over", "wait": 800}],
}


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        body = HARNESS_HTML.replace("__APPURL__", self.server.app_url).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def _python_with_pillow():
    """A Python that has Pillow. Pillow is not a project dependency."""
    candidates = [sys.executable,
                  r"C:\Users\mhanz\AppData\Local\Python\pythoncore-3.14-64\python.exe",
                  "python"]
    for candidate in candidates:
        try:
            probe = subprocess.run([candidate, "-c", "import PIL"],
                                   capture_output=True, timeout=60)
        except Exception:
            continue
        if probe.returncode == 0:
            return candidate
    raise RuntimeError("no Python with Pillow was found for the mobile crop")


def crop(path, width, height):
    """Crop the PNG to the frame. Pillow comes from the system Python."""
    code = (
        "from PIL import Image;import sys;"
        "p=sys.argv[1];w=int(sys.argv[2]);h=int(sys.argv[3]);"
        "im=Image.open(p);im.crop((0,0,w,h)).save(p)"
    )
    subprocess.run([_python_with_pillow(), "-c", code, str(path), str(width),
                    str(height)], check=True)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    # M12.2: the rail now loads the persisted conversations, so the
    # scratch stores are cleared to keep the "empty" shot honest.
    for stale in ("shot_state.db", "shot_demand.db", "shot_m12log.db",
                  "shot_pipeline.db"):
        try:
            (SCRATCH / stale).unlink()
        except FileNotFoundError:
            pass
    app_port = _free_port()
    harness_port = _free_port()
    env = dict(os.environ)
    env["M11_STATE_DB"] = str(SCRATCH / "shot_state.db")
    env["M11_DEMAND_DB"] = str(SCRATCH / "shot_demand.db")
    env["M12_LOG_DB"] = str(SCRATCH / "shot_m12log.db")
    env["LEAD_PIPELINE_DB"] = str(SCRATCH / "shot_pipeline.db")
    env["PILOT_FEEDBACK_DB"] = str(SCRATCH / "shot_feedback.db")
    app = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.server:app", "--host", "127.0.0.1",
         "--port", str(app_port)], cwd=str(ROOT), env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    harness = http.server.HTTPServer(("127.0.0.1", harness_port), Handler)
    harness.app_url = "http://127.0.0.1:%d/operator" % app_port
    threading.Thread(target=harness.serve_forever, daemon=True).start()
    deadline = time.time() + 60
    while time.time() < deadline:
        try:
            urllib.request.urlopen("http://127.0.0.1:%d/health" % app_port,
                                   timeout=2).read()
            break
        except Exception:
            time.sleep(0.5)
    try:
        for state, plan in STATES.items():
            for width, height in WIDTHS:
                themes = ["light"]
                if state == "exact" and width == 1440:
                    themes.append("dark")
                for theme in themes:
                    name = "%s-%dx%d-%s.png" % (state, width, height, theme)
                    target = OUT / name
                    frame = ""
                    window = (width, height)
                    if width < 500:
                        # Chrome cannot go below 500 dip: render the desk in
                        # a frame of the real width and crop the PNG.
                        frame = "&frame=%dx%d" % (width, height)
                        window = (500, height)
                    url = ("http://127.0.0.1:%d/harness?plan=%s%s"
                           % (harness_port, quote(json.dumps(plan)), frame))
                    cmd = [CHROME, "--headless=new", "--disable-gpu", "--no-sandbox",
                           "--disable-web-security",
                           "--window-size=%d,%d" % window,
                           "--virtual-time-budget=15000",
                           "--screenshot=" + str(target),
                           "--user-data-dir=" + str(SCRATCH / ("p" + name.replace(".", "_"))),
                           url]
                    if theme == "dark":
                        cmd.insert(3, "--blink-settings=preferredColorScheme=0")
                    subprocess.run(cmd, capture_output=True, timeout=180)
                    if width < 500:
                        crop(target, width, height)
                    if target.exists():
                        MIRROR.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(target, MIRROR / name)
                    print(name, "->", target.exists(),
                          target.stat().st_size if target.exists() else 0)
    finally:
        app.terminate()
        harness.shutdown()


if __name__ == "__main__":
    main()
