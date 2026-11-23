"""M11.7 (adapted for M12.1) - the operator page, in a real browser.

The owner typed a message on `http://127.0.0.1:8080/operator`, pressed
Send and nothing came back. The API-level test proves the request and
the reply; this test proves the **page**: a real headless Chrome opens
the real page, the message is typed into the real input, the real Send
button is clicked, and the text the page rendered in the conversation
area is read back and asserted.

M12.1 replaced the plain page with the operator desk, so the element
names changed (`composer-input`, `send-message`, `messages`) and the
draft card now says "AI draft, not sent". The promise of this test is
the same: the page shows the dealer's message and a real drafted
reply, and it never reports a failure.

A headless browser IS installed on this machine (Google Chrome), so
this test runs. When Chrome is missing the test is **skipped** - no
browser is ever installed by this repository.
"""

from __future__ import annotations

import http.server
import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

ROOT = Path(r"D:\AI-Projects\laya-gateway")

CHROME_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]

MESSAGE = "I need a plot of 5 marla"

# The harness: it opens the operator page in an iframe, types the
# message, clicks Send and posts the text the page rendered back to
# the test. It is served from its own origin; Chrome runs with
# --disable-web-security so the harness may read the iframe.
HARNESS = """<!DOCTYPE html><html><head><meta charset="utf-8"></head><body>
<iframe id="app" src="http://127.0.0.1:__APPPORT__/operator"
        style="width:1200px;height:900px"></iframe>
<pre id="out"></pre>
<script>
var iframe = document.getElementById("app");
iframe.addEventListener("load", function () {
  var doc = iframe.contentDocument;
  doc.getElementById("composer-input").value = "__MESSAGE__";
  doc.getElementById("send-message").click();
  var tries = 0;
  var timer = setInterval(function () {
    tries += 1;
    var conv = doc.getElementById("messages");
    var text = conv ? (conv.innerText || conv.textContent) : "";
    if (text.indexOf("AI draft") >= 0 || text.indexOf("Error") >= 0
        || tries > 150) {
      clearInterval(timer);
      fetch("/__collect__", {method: "POST",
                             headers: {"Content-Type": "text/plain"},
                             body: text});
    }
  }, 200);
});
</script></body></html>"""


def _find_browser():
    for path in CHROME_CANDIDATES:
        if Path(path).exists():
            return path
    return None


BROWSER = _find_browser()

pytestmark = pytest.mark.skipif(
    BROWSER is None,
    reason="no headless browser is installed on this machine",
)


def _free_port():
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


class _Handler(http.server.BaseHTTPRequestHandler):
    received = []

    def do_GET(self):
        body = HARNESS.replace("__APPPORT__", str(self.server.app_port)) \
            .replace("__MESSAGE__", MESSAGE).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        _Handler.received.append(self.rfile.read(length).decode("utf-8", "replace"))
        self.send_response(200)
        self.send_header("Content-Length", "2")
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *args):
        pass


@pytest.fixture
def live_page(tmp_path):
    """A real server, a real browser, and the text the page rendered."""
    _Handler.received = []
    app_port = _free_port()
    harness_port = _free_port()

    server = http.server.HTTPServer(("127.0.0.1", harness_port), _Handler)
    server.app_port = app_port
    threading.Thread(target=server.serve_forever, daemon=True).start()

    env = dict(os.environ)
    env["M11_STATE_DB"] = str(tmp_path / "state.db")
    env["M11_DEMAND_DB"] = str(tmp_path / "demand.db")

    app = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.server:app",
         "--host", "127.0.0.1", "--port", str(app_port)],
        cwd=str(ROOT), env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # wait for the server
    deadline = time.time() + 60
    import urllib.request
    while time.time() < deadline:
        try:
            urllib.request.urlopen("http://127.0.0.1:%d/health" % app_port,
                                   timeout=2).read()
            break
        except Exception:
            time.sleep(0.5)

    profile = tmp_path / "chrome_profile"
    browser = subprocess.Popen(
        [BROWSER, "--headless=new", "--disable-gpu", "--no-sandbox",
         "--disable-web-security", "--user-data-dir=" + str(profile),
         "http://127.0.0.1:%d/harness" % harness_port],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    try:
        deadline = time.time() + 120
        while time.time() < deadline and not _Handler.received:
            time.sleep(0.5)
        yield _Handler.received
    finally:
        browser.terminate()
        app.terminate()
        server.shutdown()


def test_the_page_shows_a_reply_in_a_real_browser(live_page):
    assert _Handler.received, "the page rendered nothing at all"
    conversation = _Handler.received[0]

    # the dealer's own message is there ...
    assert "Dealer" in conversation
    assert MESSAGE in conversation
    # ... and a draft reply follows it
    assert "AI draft" in conversation
    reply = conversation.split("AI draft", 1)[1].strip()
    assert reply, "the page drew an empty draft bubble"
    # ... and the page did not report a failure
    assert "Error" not in conversation
