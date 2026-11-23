"""M11.7 (adapted for M12.1) - the operator page must always get an answer.

The M11.7 bug was a mismatch between the page and the endpoint: the page
posted `message` and `session_id` as an
`application/x-www-form-urlencoded` **body** while the endpoint declared
them as **query** parameters, so FastAPI answered `422` and the page
drew an empty draft bubble and never said that anything had gone
wrong.

M12.1 changed the transport on purpose: the endpoint now also accepts a
JSON body, and the page uses the JSON body so a dealer's words never
appear in a URL or in an access log. The old query form still works.

This module keeps the M11.7 promise and is written against the page
that exists now:

* the request is read out of the page's own JavaScript, so the test
  fails the moment the page and the endpoint drift apart again;
* the reply the page would render is asserted;
* the page is proved to be never silent: every failure path is in the
  page;
* the five inputs from the M11.7 task are run end to end.

The request is sent through the ASGI application with a small stdlib
caller: `httpx` is not installed in this environment and no new
dependency may be added.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

ROOT = Path(r"D:\AI-Projects\laya-gateway")
PAGE = ROOT / "app" / "static" / "operator.html"
SCRIPT = ROOT / "app" / "static" / "operator.js"

# The five inputs from the task, each with a fresh session.
INPUTS = [
    "I need a plot",
    "need 5 marla plot",
    "5 marla",
    "I need 5 modula",
    "5 marla block C 80 lakh",
]


def page_source():
    return PAGE.read_text(encoding="utf-8")


def script_source():
    return SCRIPT.read_text(encoding="utf-8")


@pytest.fixture
def app():
    import app.server as server
    return server.app


@pytest.fixture(autouse=True)
def _stores(tmp_path, monkeypatch):
    monkeypatch.setenv("M11_STATE_DB", str(tmp_path / "state.db"))
    monkeypatch.setenv("M11_DEMAND_DB", str(tmp_path / "demand.db"))


# ---------------------------------------------------------------------------
# the page's own request, read out of the page
# ---------------------------------------------------------------------------
def test_the_page_posts_a_json_body_and_never_a_form():
    source = script_source()
    assert '"/api/conversation"' in source
    assert '"Content-Type": "application/json"' in source
    assert "JSON.stringify({ session_id: session.id, message: text })" in source
    # the form body that broke the page must not come back
    assert "application/x-www-form-urlencoded" not in source
    assert "URLSearchParams" not in source
    # the dealer's words must not be put in the URL
    assert "/api/conversation?" not in source


def test_the_endpoint_answers_the_json_form_and_the_query_form(app):
    from asgi_client import call_asgi, post_json

    status, result = post_json(app, "/api/conversation",
                               {"session_id": "m11-7-json", "message": "5 marla"})
    assert status == 200, result
    assert result["session_id"] == "m11-7-json"
    assert isinstance(result["reply"], str) and result["reply"]

    status, raw = call_asgi(app, "POST", "/api/conversation",
                            query=b"session_id=m11-7-query&message=5+marla")
    assert status == 200, raw
    query_result = json.loads(raw)
    assert query_result["session_id"] == "m11-7-query"
    assert isinstance(query_result["reply"], str) and query_result["reply"]


def test_the_page_gets_a_reply_for_the_message_the_owner_typed(app):
    from asgi_client import post_json

    status, result = post_json(app, "/api/conversation",
                                {"session_id": "m11-7-regression",
                                 "message": "I need a plot of 5 marla"})
    assert status == 200, result
    # this is the reply the page renders in the conversation area
    assert isinstance(result["reply"], str) and result["reply"]
    assert result["session_id"] == "m11-7-regression"
    assert result["route"] in ("exact", "alternative", "clarify", "escalate")


def test_the_failure_paths_are_in_the_page():
    """The page is never silent: a non-200 answer becomes a visible line."""
    source = script_source()
    assert "!response.ok" in source
    assert "The desk answered " in source
    assert "The desk sent no reply" in source
    assert "The server is unreachable" in source
    assert "did not answer within 20 seconds" in source
    # and the page offers a retry
    assert "Retry" in source


def test_a_missing_message_is_still_an_error(app):
    from asgi_client import call_asgi

    status, body = call_asgi(app, "POST", "/api/conversation",
                             query=b"session_id=m11-7-regression")
    assert status == 422, body
    assert b"message" in body


def test_every_input_gets_a_visible_reply(app):
    from asgi_client import post_json

    for index, text in enumerate(INPUTS):
        status, result = post_json(app, "/api/conversation",
                                   {"session_id": "m11-7-input-%d" % index,
                                    "message": text})
        assert status == 200, (text, status, result)
        reply = result.get("reply")
        assert isinstance(reply, str) and reply.strip(), (text, result)
        # and the operator is told what to do next
        assert result.get("next_action"), (text, result)


def test_the_page_carries_the_accessibility_and_state_wiring():
    html = page_source()
    assert 'aria-live="polite"' in html
    assert 'role="log"' in html
    assert 'aria-label="Show leads"' in html
    assert 'aria-label="Show context"' in html
    assert "No conversations yet" in html
    assert "data-example" in html
    # no external resource of any kind
    assert "http://" not in html.replace("http://www.w3.org", "")
    assert "cdn" not in html.lower()
    assert not re.search(r"<script[^>]+src=\"http", html)
