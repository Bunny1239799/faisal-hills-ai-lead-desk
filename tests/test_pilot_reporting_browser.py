"""Pilot reporting UI, tested in a real browser: the Reports page
(KPIs from real data, exports), the lead drawer's source control and
feedback form, and the source filters. Self-sufficient tests."""

from __future__ import annotations

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
            "b.click();}},120);return 1;}")
ARM_DRAWER = ("function(){var t=setInterval(function(){var b=document."
              "getElementById('lead-details-open');"
              "if(b&&!b.hidden){clearInterval(t);b.click();}},120);return 1;}")
ARM_REPORTS = ("function(){var t=setInterval(function(){var b=document."
               "querySelector(\".nav-item[data-view='reports']\");"
               "if(b){clearInterval(t);b.click();}},120);return 1;}")


@pytest.fixture(scope="module")
def desk(tmp_path_factory):
    with Desk(tmp_path_factory.mktemp("pfrui")) as d:
        yield d


def test_the_reports_page_shows_real_kpis(desk):
    report = desk.run(
        [{"do": "send", "text": t} for t in QUALIFY_TURNS] +
        [{"do": "wait", "ms": 1200},
         {"do": "eval", "script": ARM_REPORTS},
         {"do": "wait", "ms": 2500},
         {"do": "eval", "script":
          "function(){var w=document.getElementById('reports-wrap');"
          "return w?w.innerText.slice(0,400):'none';}"}])
    assert report["errors"] == []
    text = " ".join(str(report["evalResult"]).split())
    assert "leads" in text and "AI drafts" in text
    assert "privacy leaks" in text and "price leaks" in text
    assert "by source" in text


def test_the_drawer_sets_a_source_and_saves_feedback(desk):
    report = desk.run(
        [{"do": "send", "text": t} for t in QUALIFY_TURNS] +
        [{"do": "wait", "ms": 1200},
         {"do": "eval", "script": ARM_RAIL},
         {"do": "wait", "ms": 2200},
         {"do": "eval", "script": ARM_DRAWER},
         {"do": "wait", "ms": 2000},
         # set the source via the drawer's source select
         {"do": "eval", "script":
          "function(){var s=document.querySelectorAll("
          "'#drawer-body select')[0];"
          "if(s){s.value='WEBSITE';}"
          "var b=[].slice.call(document.querySelectorAll("
          "'#drawer-body button')).filter(function(x){"
          "return x.textContent==='Set source';})[0];"
          "if(b)b.click();return 'set';}"},
         {"do": "wait", "ms": 1600},
         # save default-structure feedback
         {"do": "eval", "script":
          "function(){var b=[].slice.call(document.querySelectorAll("
          "'#drawer-body button')).filter(function(x){"
          "return x.textContent==='Save feedback';})[0];"
          "if(b)b.click();return 'saved';}"},
         {"do": "wait", "ms": 1800},
         {"do": "eval", "script":
          "function(){var b=document.getElementById('drawer-body');"
          "return b?b.innerText:'';}"}])
    assert report["errors"] == []
    text = " ".join(str(report["evalResult"]).split()).lower()
    # the timeline journals the source change (stronger than the button
    # label, which the feedback form can scroll out of view)
    assert "source: operator_desk -> website" in text
    assert "feedback recorded" in text
    assert "useful" in text            # the feedback history rendered


def test_the_report_reflects_the_source_change_and_feedback(desk):
    report = desk.run(
        [{"do": "eval", "script": ARM_REPORTS},
         {"do": "wait", "ms": 2500},
         {"do": "eval", "script":
          "function(){var w=document.getElementById('reports-wrap');"
          "return w?w.innerText.slice(0,600):'none';}"}])
    assert report["errors"] == []
    text = " ".join(str(report["evalResult"]).split())
    assert "WEBSITE 1" in text                 # the by-source count
    assert "useful" in text.lower()            # the feedback quality


def test_export_endpoints_serve_markdown_and_csv(desk):
    report = desk.run([
        {"do": "eval", "script":
         "function(){window.__e=[];"
         "fetch('/api/weekly-report/markdown').then(function(r){"
         "return r.text();}).then(function(t){window.__e.push('md:'+t.length);});"
         "fetch('/api/weekly-report/csv').then(function(r){"
         "return r.text();}).then(function(t){window.__e.push('csv:'+t.length);});"
         "return 'go';}"},
        {"do": "wait", "ms": 2000},
        {"do": "eval", "script":
         "function(){return (window.__e||[]).join(' | ')||'none';}"},
    ])
    assert report["errors"] == []
    result = str(report["evalResult"])
    assert "md:" in result and "csv:" in result


def test_mobile_390_reports_view_has_no_overflow(desk):
    desk.frame = (390, 844)
    report = desk.run(
        [{"do": "eval", "script": ARM_REPORTS},
         {"do": "wait", "ms": 2500}])
    desk.frame = None
    assert report["errors"] == []
    assert report["overflow"]["scrollWidth"] <= \
        report["overflow"]["clientWidth"]
