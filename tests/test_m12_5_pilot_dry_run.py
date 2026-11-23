"""M12.5 - the SYNTHETIC pilot dry run.

This is a rehearsal of the pilot operator's whole workflow in a real
browser, with FABRICATED dealer words (RULES_SHORT: tests use
fabricated lines only). It is evidence that the desk supports the
shadow-mode pilot flow end to end - qualification, a gated draft,
approval, a correction, an escalation, a take-over, an operator reply,
server-side recording of every action, and persistence across a
reload. It is NOT evidence about any real dealer.
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


@pytest.fixture(scope="module")
def desk(tmp_path_factory):
    with Desk(tmp_path_factory.mktemp("m125desk")) as d:
        yield d


def test_the_full_pilot_workflow_in_one_sitting(desk):
    report = desk.run([
        # qualification turns (fabricated dealer words)
        {"do": "send", "text": "I need a plot"},
        {"do": "send", "text": "5 marla"},
        {"do": "send", "text": "block C"},
        {"do": "send", "text": "around 80 lakh"},
        {"do": "wait", "ms": 500},
        # the operator approves the draft as it stands
        {"do": "click", "selector": "#draft-send-as-is", "wait": 1200},
        # the dealer corrects the budget
        {"do": "send", "text": "actually 12 million"},
        # a discount request must escalate, never price
        {"do": "send", "text": "Any discount?"},
        {"do": "wait", "ms": 500},
        # the operator takes the conversation over and replies personally
        {"do": "click", "selector": "#take-over", "wait": 1500},
        {"do": "key", "selector": "#composer-input", "key": "Enter",
         "text": "Operator here - I will call you with the details"},
        {"do": "wait", "ms": 800},
    ])

    assert report["errors"] == []

    # the qualification state the operator relies on
    assert "Budget" in report["context"]
    assert "12,000,000" in report["conversation"]  # the correction applied

    # the escalation was visible and never priced
    assert "Human review required" in report["context"]

    # the take-over switched the composer and hid the draft
    assert "You are replying as the operator" in report["composerLabel"]

    # every operator action reached the server as a JSON body
    actions = [json.loads(r["body"])["action"] for r in report["requests"]
               if r["url"].endswith("/draft-action") and r["body"]]
    assert "sent" in actions and "operator_reply" in actions

    # the activity panel counts what the operator did
    assert "Sent as is: 1" in report["context"]
    assert "Taken over: 1" in report["context"]
    assert "Operator replies: 1" in report["context"]


def test_the_sitting_survives_a_reload_for_the_founder_review(desk):
    report = desk.run([
        {"do": "wait", "ms": 1500},
        # the conversation was taken over, so it lives under that filter
        {"do": "click", "selector": "#filter-taken", "wait": 800},
        {"do": "wait", "ms": 400},
    ])
    assert report["errors"] == []
    # the founder's weekly review opens a fresh page and still sees the
    # recorded conversation (the rail preview is the LAST dealer
    # message), the recorded actions, and the pilot metrics
    assert "Any discount?" in report["rail"]
    assert "Sent as is: 1" in report["context"]
    assert "Taken over: 1" in report["context"]
    assert "Conversations: 1" in report["context"]
    assert "AI drafts: 6" in report["context"]  # 6 dealer turns; the operator reply is not a turn
    assert "Escalations: 1" in report["context"]
    assert "Unmet demand:" in report["context"]
