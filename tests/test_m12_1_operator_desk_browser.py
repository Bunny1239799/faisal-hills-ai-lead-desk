"""M12.1 - the operator desk, tested in a real browser.

These are end-to-end checks of the real page against the real server
with the real headless Chrome that is already installed on this
machine. Nothing is installed, no model is called and no new route is
created. Every assertion is about what the **backend** returned, never
about a made-up reply.
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

FIVE_TURNS = ["I need a plot", "5 marla", "blk C", "around 80 lakh",
              "for investment"]


@pytest.fixture(scope="module")
def desk(tmp_path_factory):
    with Desk(tmp_path_factory.mktemp("m12desk")) as d:
        yield d


def send_plan(texts):
    return [{"do": "send", "text": t} for t in texts]


def test_page_loads_without_console_errors(desk):
    report = desk.run([{"do": "wait", "ms": 800}])
    assert report["errors"] == []
    assert report["operatorDesk"] is True
    # the empty state is honest
    assert "No conversations yet" in report["rail"]
    assert "Select a conversation to begin" in report["context"]
    assert "Shadow mode" in report["topbar"]


def test_empty_state_shows_the_three_example_chips(desk):
    report = desk.run([{"do": "eval",
                         "script": "function(){return document.querySelectorAll('[data-example]').length;}"}])
    assert report["evalResult"] == 3


def test_example_chip_sends_the_backend_answer(desk):
    report = desk.run([{"do": "click", "selector": "[data-example]", "wait": 3000},
                       {"do": "wait", "ms": 1500}])
    assert report["errors"] == []
    assert "AI draft" in report["draftCard"]
    # the reply is the backend wording, not a placeholder. M13: the
    # backend answer for "I need a plot" is the clarifying question -
    # the next most useful thing to ask when nothing is stated yet.
    assert "What is your budget for the plot?" in report["conversation"]
    # the dealer words are not in the URL. M12.2 added the persisted
    # conversation list, so the filter is the TURN endpoint exactly.
    for request in report["requests"]:
        if request["url"].endswith("/api/conversation"):
            assert "I+need+a+plot" not in request["url"]
            assert "message=" not in request["url"]
            assert request["contentType"] == "application/json"
            assert json.loads(request["body"])["message"] == "I need a plot"


def test_send_by_button_and_by_enter(desk):
    report = desk.run(
        [{"do": "send", "text": "5 marla"},
         {"do": "key", "selector": "#composer-input", "key": "Enter",
          "text": "blk C"}])
    assert report["errors"] == []
    assert "blk C" in report["conversation"]
    # two conversation posts, both as a JSON body
    posts = [r for r in report["requests"] if r["url"].endswith("/api/conversation")]
    assert len(posts) == 2
    assert all(p["contentType"] == "application/json" for p in posts)
    assert json.loads(posts[1]["body"])["message"] == "blk C"


def test_five_turn_flow_fills_the_requirements_table(desk):
    report = desk.run(send_plan(FIVE_TURNS))
    assert report["errors"] == []
    context = report["context"]
    assert "5 marla" in context
    assert "Block C" in context
    assert "PKR 8,000,000" in context
    assert "investment" in context
    assert "Not provided" in context
    assert "Alternatives" in report["rail"]
    assert "Lead 0001" in report["rail"]


def test_correction_updates_the_budget_and_marks_it_corrected(desk):
    report = desk.run(send_plan(FIVE_TURNS + ["actually 12 million"]))
    assert report["errors"] == []
    context = report["context"]
    assert "PKR 12,000,000" in context
    assert "Corrected" in context
    assert "Budget corrected to PKR 12,000,000" in report["conversation"]


def test_thin_data_uses_backend_wording_and_no_statistic(desk):
    report = desk.run(send_plan(["10 marla C block price"]))
    assert report["errors"] == []
    # the backend wording, shown as it was returned
    assert "closest match" in report["conversation"]
    # the page does not add a statistic of its own
    assert "PKR" not in report["context"]
    assert "median" not in report["conversation"].lower()


def test_escalation_shows_the_amber_banner(desk):
    report = desk.run(send_plan(["Any discount?"]) +
                      # M12.2: the rail persists every conversation, so the
                      # chip is asserted on the escalated ROW itself - that
                      # conversation must never be labelled a match.
                      [{"do": "wait", "ms": 500},
                       {"do": "eval", "script":
                        "function(){var rows=document.querySelectorAll("
                        "'#rail-list .rail-button');"
                        "for(var i=0;i<rows.length;i++){"
                        "if(rows[i].innerText.indexOf('Escalated')>=0)"
                        "return rows[i].innerText;}return '';}"}])
    assert report["errors"] == []
    assert "Human review required" in report["context"]
    assert "Escalated" in report["rail"]
    assert "Escalated" in report["evalResult"]
    assert "Match found" not in report["evalResult"]


def test_take_over_hides_the_draft_and_switches_the_composer(desk):
    report = desk.run(send_plan(["Any discount?"]) +
                      [{"do": "click", "selector": "#take-over", "wait": 2500},
                       {"do": "wait", "ms": 800}])
    assert report["errors"] == []
    assert report["draftCard"] == ""
    assert "You are replying as the operator" in report["composerLabel"]
    assert "Taken over" in report["rail"]


def test_reject_draft_marks_it_rejected(desk):
    report = desk.run(send_plan(["5 marla"]) +
                      [{"do": "click", "selector": "#draft-reject", "wait": 800}])
    assert report["errors"] == []
    assert "Rejected" in report["draftCard"]
    assert report["events"] and report["events"][-1]["action"] == "rejected"
    assert set(report["events"][-1]) == {"session", "draft_id", "action", "time"}


def test_save_edit_labels_the_draft_as_edited(desk):
    report = desk.run(send_plan(["5 marla"]) +
                      [{"do": "eval", "script":
                        "function(){var i=document.getElementById('composer-input');"
                        "i.value='Edited draft text';return true;}"},
                       {"do": "click", "selector": "#draft-save-edit", "wait": 800}])
    assert report["errors"] == []
    assert "Edited" in report["draftCard"]
    assert "Edited draft text" in report["draftCard"]
    assert report["events"][-1]["action"] == "edited"


def test_send_as_is_does_not_claim_a_delivery(desk):
    report = desk.run(send_plan(["5 marla"]) +
                      [{"do": "click", "selector": "#draft-send-as-is", "wait": 800}])
    assert report["errors"] == []
    assert "No message was delivered" in report["draftCard"]
    assert report["events"][-1]["action"] == "sent"


def test_api_failure_is_visible_and_offers_retry(desk):
    report = desk.run([{"do": "patch-fetch", "mode": "api"},
                       {"do": "send", "text": "5 marla"},
                       {"do": "restore-fetch"},
                       {"do": "wait", "ms": 500}])
    assert report["errors"] == []
    assert "Error" in report["conversation"]
    assert "Retry" in report["conversation"]


def test_server_unreachable_raises_the_banner(desk):
    report = desk.run([{"do": "patch-fetch", "mode": "network"},
                       {"do": "send", "text": "5 marla"},
                       {"do": "restore-fetch"},
                       {"do": "wait", "ms": 500}])
    assert report["errors"] == []
    assert report["bannerHidden"] is False
    assert "unreachable" in report["banner"].lower()


def test_timeout_is_visible(desk):
    report = desk.run([{"do": "patch-fetch", "mode": "timeout"},
                       {"do": "send", "text": "5 marla", "timeout": 30000},
                       {"do": "restore-fetch"},
                       {"do": "wait", "ms": 500}])
    assert report["errors"] == []
    assert "20 seconds" in report["conversation"]


def test_long_conversation_scrolls_without_horizontal_overflow(desk):
    plan = []
    for index in range(6):
        plan.append({"do": "send", "text": "I need a plot %d" % index})
    report = desk.run(plan)
    assert report["errors"] == []
    assert report["overflow"]["scrollWidth"] <= report["overflow"]["clientWidth"]


def test_no_horizontal_overflow_at_the_three_widths(desk):
    for width, height in ((1440, 900), (1024, 768), (390, 844)):
        with Desk(desk.tmp_path, width=width, height=height) as small:
            if width < 500:
                # Chrome cannot make a window narrower than 500 dip, so the
                # desk is rendered in a frame of the real width.
                small.frame = "%dx%d" % (width, height)
            report = small.run(send_plan(["5 marla"]))
            assert report["errors"] == []
            assert report["overflow"]["scrollWidth"] <= \
                report["overflow"]["clientWidth"]


def test_a_new_conversation_is_chipped_as_new(desk):
    report = desk.run([{"do": "click", "selector": "#new-conversation", "wait": 500}])
    assert report["errors"] == []
    assert "New" in report["rail"]
    # the new conversation has no requirements yet
    assert "Not provided" in report["context"]


def test_the_rail_shows_the_latest_message_preview(desk):
    report = desk.run(send_plan(["I need a plot"]))
    assert report["errors"] == []
    assert "Lead 0001" in report["rail"]
    assert "I need a plot" in report["rail"]


def test_the_panel_shows_the_backend_ladder_step(desk):
    report = desk.run(send_plan(["5 marla in block C"]))
    assert report["errors"] == []
    # the ladder step the backend returned (next_action.action)
    assert "Exact match" in report["context"]
