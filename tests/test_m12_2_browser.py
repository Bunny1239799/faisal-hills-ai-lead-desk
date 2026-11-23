"""M12.2 - persistence, tested in a real browser.

The conversations must survive a reload: the rail is loaded from the
backend, the thread is replayed from the record, and an operator action
on a restored draft is recorded on the server. Every assertion is about
what the backend returned - the page invents nothing.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(r"D:\AI-Projects\laya-gateway")
sys.path.insert(0, str(ROOT / "tests"))

from m12_browser import Desk, find_browser  # noqa: E402

pytestmark = pytest.mark.skipif(find_browser() is None,
                                reason="no headless browser is installed")

MESSAGE = "5 marla in block C"


@pytest.fixture(scope="module")
def desk(tmp_path_factory):
    with Desk(tmp_path_factory.mktemp("m122desk")) as d:
        yield d


def _session_id_of(report):
    for request in report["requests"]:
        if request["url"].endswith("/api/conversation") and \
                request["method"] == "POST" and request["body"]:
            payload = json.loads(request["body"])
            if payload.get("message") == MESSAGE:
                return payload["session_id"]
    return None


def test_the_conversation_survives_a_reload(desk):
    # page 1: a turn runs in a fresh page
    first = desk.run([{"do": "send", "text": MESSAGE},
                      {"do": "wait", "ms": 800}])
    assert first["errors"] == []
    assert "AI draft" in first["draftCard"]
    session_id = _session_id_of(first)
    assert session_id, "the page never posted the turn"

    # page 2: a brand-new browser load - the rail comes from the backend
    reload = desk.run([{"do": "wait", "ms": 1000}])
    assert reload["errors"] == []
    assert session_id in reload["rail"]
    assert MESSAGE in reload["rail"]
    # the activity panel is part of the desk
    assert "Operator activity" in reload["context"]


def test_the_thread_is_replayed_from_the_record(desk):
    report = desk.run([
        # the rail is filled by an async fetch, so the page settles first
        {"do": "wait", "ms": 1000},
        {"do": "click", "selector": "#rail-list .rail-button", "wait": 1500},
        {"do": "wait", "ms": 500},
    ])
    assert report["errors"] == []
    # the dealer's words and the application's draft both replay
    assert MESSAGE in report["conversation"]
    assert "AI draft" in report["conversation"]


def test_an_action_on_a_restored_draft_is_recorded_on_the_server(desk):
    report = desk.run([
        {"do": "wait", "ms": 1000},
        {"do": "click", "selector": "#rail-list .rail-button", "wait": 1500},
        {"do": "click", "selector": "#draft-reject", "wait": 1500},
        {"do": "wait", "ms": 800},
    ])
    assert report["errors"] == []

    # the activity view counts it, from the backend's own record
    assert "Rejected: 1" in report["context"]

    # the action was posted as a JSON body
    posted = [request for request in report["requests"]
              if request["url"].endswith("/draft-action")]
    assert posted, "the page never recorded the action"
    assert json.loads(posted[0]["body"])["action"] == "rejected"

    # and the in-page event list still carries it
    assert any(event["action"] == "rejected" for event in report["events"])


def test_the_activity_view_persists_across_page_loads(desk):
    report = desk.run([{"do": "wait", "ms": 1000}])
    assert report["errors"] == []
    assert "Rejected: 1" in report["context"]
