"""M12.1 - the browser harness for the operator desk.

Headless Chrome is already installed on this machine, so the desk is
tested **in a real browser**: the real page, the real server, the real
clicks. No browser is installed by this repository, and the tests are
skipped when no browser is found.

The harness opens the page in an iframe, drives it with a small plan,
and reports back what the page rendered:

* the conversation, the context panel and the rail, as text;
* every JavaScript error and every ``console.error``;
* the requests the page made (url, method, body);
* the in-page draft event list;
* whether the page overflows horizontally.

The project has no ``httpx``, so the API-level tests use the stdlib
ASGI caller in ``tests/asgi_client.py``; this module is only for the
browser.
"""

from __future__ import annotations

import http.server
import json
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

ROOT = Path(r"D:\AI-Projects\laya-gateway")

CHROME_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]

HARNESS_HTML = """<!DOCTYPE html><html><head><meta charset="utf-8"></head><body>
<iframe id="app" src="__APPURL__" style="position:fixed;inset:0;width:100%;height:100%;border:0"></iframe>
<script>
var params = new URLSearchParams(location.search);
var frame = params.get("frame");
if (frame) {
  var parts = frame.split("x");
  var frameNode = document.getElementById("app");
  frameNode.style.inset = "0 auto auto 0";
  frameNode.style.width = parts[0] + "px";
  frameNode.style.height = parts[1] + "px";
}
var plan = JSON.parse(params.get("plan") || "[]");
var iframe = document.getElementById("app");
var errors = [];

function textOf(node) {
  return node ? (node.innerText || node.textContent || "") : "";
}

function sleep(ms) {
  return new Promise(function (resolve) { setTimeout(resolve, ms); });
}

async function waitFor(predicate, timeout) {
  var limit = Date.now() + (timeout || 25000);
  while (Date.now() < limit) {
    try { if (predicate()) return true; } catch (e) { /* keep waiting */ }
    await sleep(50);
  }
  return false;
}

function win() { return iframe.contentWindow; }
function doc() { return iframe.contentDocument; }

async function runStep(step) {
  var d = doc();
  if (step.do === "send") {
    d.getElementById("composer-input").value = step.text;
    d.getElementById("send-message").click();
    await waitFor(function () { return !d.getElementById("send-message").disabled; },
                  step.timeout || 25000);
    await sleep(150);
  } else if (step.do === "key") {
    var target = d.querySelector(step.selector);
    target.focus();
    target.value = step.text || "";
    var event = new (win().KeyboardEvent)("keydown",
      {key: step.key, bubbles: true, cancelable: true});
    target.dispatchEvent(event);
    await waitFor(function () { return !d.getElementById("send-message").disabled; },
                  step.timeout || 25000);
    await sleep(150);
  } else if (step.do === "click") {
    d.querySelector(step.selector).click();
    await sleep(step.wait || 300);
  } else if (step.do === "wait") {
    await sleep(step.ms || 300);
  } else if (step.do === "patch-fetch") {
    var w = win();
    w.__origFetch = w.fetch;
    if (step.mode === "network") {
      w.fetch = function () { return Promise.reject(new TypeError("Failed to fetch")); };
    } else if (step.mode === "timeout") {
      w.fetch = function (url, opts) {
        return new Promise(function (resolve, reject) {
          var signal = opts && opts.signal;
          if (!signal) return;
          signal.addEventListener("abort", function () {
            var error = new Error("The operation was aborted");
            error.name = "AbortError";
            reject(error);
          });
        });
      };
    } else {
      w.fetch = function (url, opts) {
        return Promise.resolve(new Response("server exploded", {status: 500}));
      };
    }
  } else if (step.do === "restore-fetch") {
    win().fetch = win().__origFetch;
  } else if (step.do === "eval") {
    var w2 = win();
    w2.__evalResult = (new w2.Function("return (" + step.script + ")()"))();
    await sleep(80);
  }
}

async function run() {
  for (var i = 0; i < plan.length; i += 1) {
    try {
      await runStep(plan[i]);
    } catch (e) {
      errors.push("plan error: " + (e && e.message ? e.message : e));
    }
  }
  await sleep(600);
  report();
}

function report() {
  var d = doc();
  var w = win();
  var payload = {
    conversation: textOf(d.getElementById("messages")),
    context: textOf(d.getElementById("context")),
    rail: textOf(d.getElementById("rail")),
    topbar: textOf(d.querySelector(".topbar")),
    composerLabel: textOf(d.getElementById("composer-label")),
    composerNote: textOf(d.getElementById("composer-note")),
    draftCard: textOf(d.querySelector(".draft-card")),
    banner: textOf(d.getElementById("server-banner")),
    bannerHidden: d.getElementById("server-banner").hidden,
    errors: errors,
    requests: w.__requests || [],
    jsonBodies: w.__jsonBodies || [],
    html: doc() ? doc().documentElement.outerHTML : "",
    events: (w.operatorDesk && w.operatorDesk.events) || [],
    operatorDesk: !!w.operatorDesk,
    evalResult: w.__evalResult === undefined ? null : w.__evalResult,
    overflow: {
      scrollWidth: d.documentElement.scrollWidth,
      clientWidth: d.documentElement.clientWidth,
      bodyScrollWidth: d.body.scrollWidth
    }
  };
  fetch("/__collect__", {method: "POST",
                         headers: {"Content-Type": "text/plain"},
                         body: JSON.stringify(payload)});
}

iframe.addEventListener("load", function () {
  var w = win();
  w.__requests = [];
  w.__jsonBodies = [];
  var originalFetch = w.fetch;
  w.fetch = function (url, opts) {
    try {
      w.__requests.push({url: String(url), method: (opts && opts.method) || "GET",
                         body: opts && opts.body ? String(opts.body) : null,
                         contentType: (opts && opts.headers &&
                                       opts.headers["Content-Type"]) || null});
    } catch (e) { /* the request is still made */ }
    var result = originalFetch.apply(w, arguments);
    try {
      result.then(function (response) {
        try {
          var type = response.headers.get("content-type") || "";
          if (type.indexOf("json") >= 0) {
            response.clone().text().then(function (text) {
              w.__jsonBodies.push({url: String(url), status: response.status,
                                   body: text});
            });
          }
        } catch (e) { /* the body is still returned to the page */ }
      });
    } catch (e) { /* the request is still made */ }
    return result;
  };
  w.addEventListener("error", function (event) {
    errors.push("error: " + (event.message || "unknown"));
  });
  w.addEventListener("unhandledrejection", function (event) {
    errors.push("unhandledrejection: " + event.reason);
  });
  var originalError = w.console.error;
  w.console.error = function () {
    errors.push("console.error: " +
      Array.prototype.join.call(arguments, " "));
    originalError.apply(w.console, arguments);
  };
  run();
});
</script></body></html>"""


def find_browser():
    for path in CHROME_CANDIDATES:
        if Path(path).exists():
            return path
    return None


def _free_port():
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


class _Handler(http.server.BaseHTTPRequestHandler):
    received = []

    def do_GET(self):
        body = HARNESS_HTML.replace("__APPURL__", self.server.app_url).encode("utf-8")
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


class Desk:
    """A real server and a real browser, driving the real page."""

    def __init__(self, tmp_path, width=1440, height=900):
        self.tmp_path = Path(tmp_path)
        self.width = width
        self.height = height
        self.frame = None
        self.app_port = _free_port()
        self.harness_port = _free_port()
        self._app = None
        self._browser = None
        self._handler = _Handler
        self.console_output = ""

    def __enter__(self):
        _Handler.received = []
        self._handler = _Handler
        self._handler.received = []

        harness = http.server.HTTPServer(("127.0.0.1", self.harness_port), _Handler)
        harness.app_url = "http://127.0.0.1:%d/operator" % self.app_port
        threading.Thread(target=harness.serve_forever, daemon=True).start()
        self._harness = harness

        env = dict(os.environ)
        env["M11_STATE_DB"] = str(self.tmp_path / "state.db")
        env["M11_DEMAND_DB"] = str(self.tmp_path / "demand.db")
        env["M12_LOG_DB"] = str(self.tmp_path / "m12log.db")
        env["LEAD_PIPELINE_DB"] = str(self.tmp_path / "pipeline.db")
        env["PILOT_FEEDBACK_DB"] = str(self.tmp_path / "feedback.db")
        self._app = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "app.server:app",
             "--host", "127.0.0.1", "--port", str(self.app_port)],
            cwd=str(ROOT), env=env,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        deadline = time.time() + 60
        while time.time() < deadline:
            try:
                urllib.request.urlopen(
                    "http://127.0.0.1:%d/health" % self.app_port, timeout=2).read()
                break
            except Exception:
                time.sleep(0.5)

        browser = find_browser()
        if browser is None:
            raise RuntimeError("no headless browser is installed")
        self._browser = None
        return self

    def __exit__(self, *args):
        if self._browser is not None:
            self._browser.terminate()
            try:
                out, _err = self._browser.communicate(timeout=15)
                self.console_output = (out or b"").decode("utf-8", "replace") + \
                    (_err or b"").decode("utf-8", "replace")
            except Exception:
                self.console_output = ""
        if self._app is not None:
            self._app.terminate()
        self._harness.shutdown()
        return False

    def run(self, plan, timeout=180):
        """Run a plan in the browser and return the report."""
        _Handler.received = []
        browser = find_browser()
        if browser is None:
            raise RuntimeError("no headless browser is installed")
        self._browser = subprocess.Popen(
            [browser, "--headless=new", "--disable-gpu", "--no-sandbox",
             "--disable-web-security", "--enable-logging=stderr", "--v=0",
             "--window-size=%d,%d" % (self.width, self.height),
             "--user-data-dir=" + str(self.tmp_path / ("chrome" + str(time.time()))),
             "http://127.0.0.1:%d/harness?plan=%s%s" % (
                 self.harness_port, _encode_plan(plan),
                 ("&frame=%dx%d" % (self.width, self.height))
                 if self.frame else "")],
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        deadline = time.time() + timeout
        while time.time() < deadline and not _Handler.received:
            time.sleep(0.25)
        self._browser.terminate()
        try:
            out, err = self._browser.communicate(timeout=15)
            self.console_output = (out or b"").decode("utf-8", "replace") + \
                (err or b"").decode("utf-8", "replace")
        except Exception:
            self.console_output = ""
        if not _Handler.received:
            raise AssertionError("the page reported nothing back to the harness")
        return json.loads(_Handler.received[0])


def _encode_plan(plan):
    from urllib.parse import quote
    return quote(json.dumps(plan))
