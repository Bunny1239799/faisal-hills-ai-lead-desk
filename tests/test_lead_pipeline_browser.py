"""The lead pipeline UI, tested in a real browser: pipeline-aware rail
badges, the lead strip, the lead drawer with operator-approved stage
changes, the follow-ups queue with safe drafts and its record-only
actions. Every test is self-sufficient: it creates its own lead."""

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

QUALIFY_TURNS = ["I need a plot", "5 marla", "block C", "around 80 lakh"]

ARM_RAIL = ("function(){var t=setInterval(function(){var b=document."
            "querySelector('#rail-list .rail-button');if(b){clearInterval(t);"
            "b.click();}},120);return 'armed';}")
ARM_FOLLOWUPS = ("function(){var t=setInterval(function(){var b=document."
                 "querySelector(\".nav-item[data-view='followups']\");"
                 "if(b){clearInterval(t);b.click();}},120);return 'armed';}")
ARM_DRAWER = ("function(){var t=setInterval(function(){var b=document."
              "getElementById('lead-details-open');"
              "if(b&&!b.hidden){clearInterval(t);b.click();}},120);"
              "return 'armed';}")
CLICK_DRAWER_X = ("function(){var b=document.getElementById('drawer-close');"
                  "b.click();return 'x-clicked';}")
READ_QUEUE = ("function(){return document.getElementById('fq-wrap')"
              ".textContent.slice(0, 1400);}")

SWITCH_LIGHT = ("function(){if(document.documentElement.getAttribute("
                "'data-theme')!=='light')"
                "document.getElementById('theme-toggle').click();return 1;}")


def drawer_probe(label):
    """One probe: drawer visibility, the Send button's usability, the
    active lead id, the drawer title and a body snippet. Every probe
    accumulates in window.__drawerProbes; READ_PROBES returns them all
    (the harness keeps only the last eval result)."""
    return ("function(){var d=document.getElementById('lead-drawer');"
            "var send=document.getElementById('send-message');"
            "var r=d.getBoundingClientRect();var s=send.getBoundingClientRect();"
            "var cs=getComputedStyle(d);var hit=s.width>0?"
            "document.elementFromPoint(s.left+s.width/2,s.top+s.height/2):null;"
            "var o={label:'" + label + "',hidden:d.hidden,"
            "visible:r.width>0&&r.height>0&&cs.display!=='none',"
            "drawerW:Math.round(r.width),"
            "theme:document.documentElement.getAttribute('data-theme'),"
            "active:(window.operatorDesk&&window.operatorDesk.activeLeadId)||null,"
            "title:document.getElementById('drawer-title').textContent,"
            "body:document.getElementById('drawer-body').textContent"
            ".slice(0,200),"
            "sendVisible:s.width>0&&s.height>0,"
            "sendUsable:!!hit&&(hit===send||send.contains(hit))};"
            "(window.__drawerProbes=window.__drawerProbes||[]).push(o);"
            "return JSON.stringify(o);}")


READ_PROBES = "function(){return JSON.stringify(window.__drawerProbes||[]);}"


def probes_of(report):
    assert report["errors"] == []
    return {p["label"]: p
            for p in json.loads(str(report["evalResult"]))}


@pytest.fixture(scope="module")
def desk(tmp_path_factory):
    with Desk(tmp_path_factory.mktemp("lpui")) as d:
        yield d


def test_the_rail_shows_stage_temperature_and_score(desk):
    report = desk.run([{"do": "send", "text": t} for t in QUALIFY_TURNS] +
                      [{"do": "wait", "ms": 1200}])
    assert report["errors"] == []
    assert "/100" in report["rail"] and "NEW" in report["rail"]
    assert "Lead" in report["context"] and "/100" in report["context"]


def test_the_lead_drawer_approves_a_stage_change(desk):
    report = desk.run(
        [{"do": "send", "text": t} for t in QUALIFY_TURNS] +
        [{"do": "wait", "ms": 1200},
         {"do": "eval", "script": ARM_RAIL},
         {"do": "wait", "ms": 2500},
         {"do": "eval", "script":
          "function(){var t=setInterval(function(){var b=document."
          "getElementById('lead-details-open');"
          "if(b && !b.hidden){clearInterval(t);b.click();}},120);"
          "return 'armed';}"},
         {"do": "wait", "ms": 2200},
         {"do": "eval", "script":
          "function(){var s=document.querySelector('#drawer-body select[aria-label=\"New stage\"]');"
          "if(s){s.value='QUALIFIED';}"
          "var b=[].slice.call(document.querySelectorAll("
          "'#drawer-body button')).filter(function(x){"
          "return x.textContent==='Approve stage';})[0];"
          "if(b){b.click();return 'clicked';}return 'no-button';}"},
         {"do": "wait", "ms": 1800},
         {"do": "eval", "script":
          "function(){return document.getElementById('drawer-body')"
          ".textContent.slice(0, 300);}"}])
    assert report["errors"] == []
    text = " ".join(str(report["evalResult"]).split())
    assert "Stage: Qualified" in text


def test_the_follow_ups_queue_renders_with_safe_drafts(desk):
    report = desk.run(
        [{"do": "send", "text": t} for t in QUALIFY_TURNS] +
        [{"do": "wait", "ms": 1200},
         {"do": "eval", "script": ARM_FOLLOWUPS},
         {"do": "wait", "ms": 2500},
         {"do": "eval", "script": READ_QUEUE}])
    assert report["errors"] == []
    text = " ".join(str(report["evalResult"]).split())
    assert "Due today" in text and "Overdue" in text
    assert "Score" in text and "WARM" in text.upper()    # the lead card
    assert "human approval required" in text.lower()
    assert "nothing was sent" in text.lower()
    assert "No price or availability is confirmed" in text   # the draft


def test_follow_up_draft_actions_are_recorded_not_sent(desk):
    report = desk.run(
        [{"do": "send", "text": t} for t in QUALIFY_TURNS] +
        [{"do": "wait", "ms": 1200},
         {"do": "eval", "script": ARM_FOLLOWUPS},
         {"do": "wait", "ms": 2500},
         {"do": "eval", "script":
          "function(){var btn=[].slice.call(document.querySelectorAll("
          "'.fq-actions button')).filter(function(x){"
          "return x.textContent==='Approve';})[0];"
          "if(btn){btn.click();return 'clicked';}return 'no-button';}"},
         {"do": "wait", "ms": 1500},
         {"do": "eval", "script":
          "function(){var btn=[].slice.call(document.querySelectorAll("
          "'.fq-actions button')).filter(function(x){"
          "return x.textContent.indexOf('Approve')===0;})[0];"
          "return btn?btn.textContent:'none';}"}])
    assert report["errors"] == []
    assert "recorded" in str(report["evalResult"]).lower()


def test_escalation_moves_the_lead_and_shows_in_the_queue(desk):
    report = desk.run(
        [{"do": "send", "text": "Any discount?"},
         {"do": "wait", "ms": 800},
         {"do": "eval", "script": ARM_FOLLOWUPS},
         {"do": "wait", "ms": 2500},
         {"do": "eval", "script": READ_QUEUE}])
    assert report["errors"] == []
    text = " ".join(str(report["evalResult"]).split())
    assert "Escalated (" in text            # a populated escalated section
    assert "Human review required" in report["context"]


def test_mobile_390_still_has_no_horizontal_overflow(desk):
    desk.frame = (390, 844)
    report = desk.run(
        [{"do": "eval", "script": ARM_FOLLOWUPS},
         {"do": "wait", "ms": 2500}])
    desk.frame = None
    assert report["errors"] == []
    assert report["overflow"]["scrollWidth"] <= report["overflow"]["clientWidth"]


def test_the_lead_drawer_starts_closed_on_load(desk):
    report = desk.run(
        [{"do": "wait", "ms": 900},
         {"do": "eval", "script": drawer_probe("initial-load")}])
    assert report["errors"] == []
    state = json.loads(str(report["evalResult"]))
    assert state["hidden"] is True          # the HTML hidden attribute
    assert state["visible"] is False        # and it must actually hide


def test_clicking_x_closes_the_drawer_and_frees_the_desk(desk):
    report = desk.run(
        [{"do": "send", "text": t} for t in QUALIFY_TURNS] +
        [{"do": "wait", "ms": 1200},
         {"do": "eval", "script": ARM_RAIL},
         {"do": "wait", "ms": 2500},
         {"do": "eval", "script": ARM_DRAWER},
         {"do": "wait", "ms": 2200},
         {"do": "eval", "script": drawer_probe("open")},
         {"do": "eval", "script": CLICK_DRAWER_X},
         {"do": "wait", "ms": 700},
         {"do": "eval", "script": drawer_probe("closed")},
         {"do": "eval", "script": READ_PROBES}])
    states = probes_of(report)
    opened, closed = states["open"], states["closed"]
    assert opened["visible"] is True                    # it was open
    assert closed["hidden"] is True                     # X set the attribute
    assert closed["visible"] is False                   # and the panel went
    assert closed["drawerW"] == 0                       # no space is held
    assert closed["sendVisible"] is True                # composer is back
    assert closed["sendUsable"] is True                 # and clickable
    assert closed["active"] == opened["active"]         # the lead survives


def test_reopening_the_same_lead_restores_the_drawer(desk):
    report = desk.run(
        [{"do": "send", "text": t} for t in QUALIFY_TURNS] +
        [{"do": "wait", "ms": 1200},
         {"do": "eval", "script": ARM_RAIL},
         {"do": "wait", "ms": 2500},
         {"do": "eval", "script": ARM_DRAWER},
         {"do": "wait", "ms": 2200},
         {"do": "eval", "script": drawer_probe("first-open")},
         {"do": "eval", "script": CLICK_DRAWER_X},
         {"do": "wait", "ms": 700},
         {"do": "eval", "script": drawer_probe("closed")},
         {"do": "eval", "script": ARM_DRAWER},
         {"do": "wait", "ms": 2200},
         {"do": "eval", "script": drawer_probe("reopened")},
         {"do": "eval", "script": READ_PROBES}])
    states = probes_of(report)
    first, closed, reopened = states["first-open"], states["closed"], \
        states["reopened"]
    assert first["visible"] is True
    assert closed["visible"] is False
    assert reopened["visible"] is True
    assert reopened["title"] == first["title"]
    assert "Stage:" in reopened["body"]                # pipeline re-rendered
    assert reopened["active"] == first["active"]
    # the desk conversation itself was never touched by the drawer
    assert "around 80 lakh" in report["conversation"]


def test_drawer_x_close_works_at_tablet_width(desk):
    desk.width, desk.height = 1024, 768
    report = desk.run(
        [{"do": "send", "text": t} for t in QUALIFY_TURNS] +
        [{"do": "wait", "ms": 1200},
         {"do": "eval", "script": ARM_RAIL},
         {"do": "wait", "ms": 2500},
         {"do": "eval", "script": ARM_DRAWER},
         {"do": "wait", "ms": 2200},
         {"do": "eval", "script": CLICK_DRAWER_X},
         {"do": "wait", "ms": 700},
         {"do": "eval", "script": drawer_probe("tablet-closed")},
         {"do": "eval", "script": READ_PROBES}])
    desk.width, desk.height = 1440, 900
    states = probes_of(report)
    state = states["tablet-closed"]
    assert state["hidden"] is True and state["visible"] is False
    assert state["sendVisible"] is True and state["sendUsable"] is True
    assert report["overflow"]["scrollWidth"] <= report["overflow"]["clientWidth"]


def test_drawer_x_close_works_on_mobile_390(desk):
    desk.frame = (390, 844)
    report = desk.run(
        [{"do": "send", "text": t} for t in QUALIFY_TURNS] +
        [{"do": "wait", "ms": 1200},
         {"do": "eval", "script": ARM_RAIL},
         {"do": "wait", "ms": 2500},
         {"do": "eval", "script": ARM_DRAWER},
         {"do": "wait", "ms": 2200},
         {"do": "eval", "script": CLICK_DRAWER_X},
         {"do": "wait", "ms": 700},
         {"do": "eval", "script": drawer_probe("mobile-closed")},
         {"do": "eval", "script": READ_PROBES}])
    desk.frame = None
    states = probes_of(report)
    state = states["mobile-closed"]
    assert state["hidden"] is True and state["visible"] is False
    assert state["sendVisible"] is True and state["sendUsable"] is True
    assert report["overflow"]["scrollWidth"] <= report["overflow"]["clientWidth"]


def test_drawer_x_close_works_in_light_theme(desk):
    report = desk.run(
        [{"do": "eval", "script": SWITCH_LIGHT}] +
        [{"do": "send", "text": t} for t in QUALIFY_TURNS] +
        [{"do": "wait", "ms": 1200},
         {"do": "eval", "script": ARM_RAIL},
         {"do": "wait", "ms": 2500},
         {"do": "eval", "script": ARM_DRAWER},
         {"do": "wait", "ms": 2200},
         {"do": "eval", "script": drawer_probe("light-open")},
         {"do": "eval", "script": CLICK_DRAWER_X},
         {"do": "wait", "ms": 700},
         {"do": "eval", "script": drawer_probe("light-closed")},
         {"do": "eval", "script": READ_PROBES}])
    states = probes_of(report)
    opened, closed = states["light-open"], states["light-closed"]
    assert opened["theme"] == "light"                   # the theme took
    assert opened["visible"] is True
    assert closed["theme"] == "light"
    assert closed["hidden"] is True and closed["visible"] is False
    assert closed["sendVisible"] is True and closed["sendUsable"] is True


def test_escape_key_closes_the_drawer(desk):
    report = desk.run(
        [{"do": "send", "text": t} for t in QUALIFY_TURNS] +
        [{"do": "wait", "ms": 1200},
         {"do": "eval", "script": ARM_RAIL},
         {"do": "wait", "ms": 2500},
         {"do": "eval", "script": ARM_DRAWER},
         {"do": "wait", "ms": 2200},
         {"do": "eval", "script": drawer_probe("esc-open")},
         {"do": "eval", "script":
          "function(){document.dispatchEvent(new KeyboardEvent("
          "'keydown',{key:'Escape',bubbles:true,cancelable:true}));"
          "return 'esc-sent';}"},
         {"do": "wait", "ms": 700},
         {"do": "eval", "script": drawer_probe("esc-closed")},
         {"do": "eval", "script": READ_PROBES}])
    states = probes_of(report)
    assert states["esc-open"]["visible"] is True
    assert states["esc-closed"]["hidden"] is True
    assert states["esc-closed"]["visible"] is False
