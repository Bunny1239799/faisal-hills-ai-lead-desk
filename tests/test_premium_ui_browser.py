"""Premium product UI - the app shell, map, future modules, copy draft,
theme toggle and responsive behavior, tested in a real browser.

The shell wraps the existing desk WITHOUT replacing it: every desk
element the older suites assert is still present and still works (that
is covered by the existing batteries; here we prove the NEW shell).
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
    with Desk(tmp_path_factory.mktemp("premium")) as d:
        yield d


def test_the_shell_loads_with_sidebar_topbar_and_desk(desk):
    report = desk.run([{"do": "wait", "ms": 700}])
    assert report["errors"] == []
    assert "Faisal Hills" in report["rail"] or "Faisal Hills" in report["topbar"]
    assert "Leads / Operator Desk" in report["rail"] or \
        "Leads / Operator Desk" in report["html"]
    # the desk is still the active view and its honest empty state shows
    assert "No conversations yet" in report["rail"]
    assert "Shadow mode" in report["topbar"]
    # the environment chip states the server's truth about the file it
    # would actually serve (Stage 1 replaced the FH_MASTER_PATH-presence
    # badge with a data-derived chip)
    assert ("MASTER" in report["topbar"] or "INVENTORY" in report["topbar"])
    assert "rows" in report["topbar"]


def test_sidebar_navigation_and_coming_soon_modules(desk):
    report = desk.run([
        {"do": "eval", "script":
         "function(){var b=document.querySelector("
         "\".nav-item[data-module='viz3d']\");if(b)b.click();"
         "return {name:document.getElementById('module-name').textContent,"
         " badge:document.getElementById('module-badge').textContent,"
         " note:document.querySelector('.module-note').textContent,"
         " active:document.querySelector('.view.active').id};}"},
        {"do": "wait", "ms": 400},
    ])
    assert report["errors"] == []
    assert report["evalResult"]["active"] == "view-module"
    assert report["evalResult"]["name"] == "3D Visualization"
    assert report["evalResult"]["badge"] == "Coming Soon"
    assert "not active" in report["evalResult"]["note"]
    # every future module renders from the same honest template
    # (Follow-ups graduated to an ACTIVE view in the lead-pipeline
    # upgrade, and Inventory became a real page in Stage 1, so neither
    # is in the coming-soon list any more)
    counts = desk.run([
        {"do": "eval", "script":
         "function(){var names=[];['voice',"
         "'intel','settings'].forEach(function(k){var b=document.querySelector("
         "'.nav-item[data-module='+k+']');b.click();"
         "names.push(document.getElementById('module-name').textContent);});"
         "return names;}"},
    ])
    assert counts["errors"] == []
    assert counts["evalResult"] == ["Voice AI",
                                    "Sales Intelligence", "Settings"]


def test_the_map_view_renders_real_offline_tiles_and_disclaimers(desk):
    report = desk.run([
        {"do": "eval", "script":
         "function(){var b=document.querySelector(\".nav-item[data-view='map']\");"
         "if(b)b.click();return true;}"},
        {"do": "wait", "ms": 1500},
        {"do": "eval", "script":
         "function(){return {tiles:document.querySelectorAll("
         "'#map-canvas .leaflet-tile-loaded').length,"
         " disclaim:(document.querySelector('.map-disclaimer')||{})"
         ".textContent||''};}"},
        {"do": "click", "selector": ".map-filters [data-block='D']", "wait": 500},
    ])
    assert report["errors"] == []
    tiles = report["evalResult"]["tiles"]
    assert tiles and tiles >= 4, "the offline map rendered no tiles"
    flat = " ".join(report["evalResult"]["disclaim"].split())
    assert "orientation only" in flat
    assert "Plot-level GIS mapping is coming soon" in flat
    assert "OpenStreetMap contributors" in flat
    # a parked block is honest about its scope, never about availability
    assert "Parked scope" in report["html"]
    assert "Plot-level mapping coming soon" in report["html"]


def test_copy_draft_is_wired_and_never_silent(desk):
    report = desk.run([
        {"do": "send", "text": "5 marla in block C"},
        {"do": "wait", "ms": 500},
        {"do": "click", "selector": "#draft-copy", "wait": 1200},
        {"do": "wait", "ms": 400},
    ])
    assert report["errors"] == []
    # in the headless browser the OS clipboard is denied, so the VISIBLE
    # outcome is the honest refusal line; in a real headed browser the
    # success line appears. Either way the button is wired and never
    # silent - and no dealer received anything.
    outcome = report["conversation"]
    assert ("copied to the clipboard" in outcome
            or "clipboard refused the copy" in outcome)


def test_theme_toggle_switches_both_ways(desk):
    report = desk.run([
        {"do": "eval", "script":
         "function(){var t=document.getElementById('theme-toggle');"
         "t.click();var a=document.documentElement.getAttribute('data-theme');"
         "t.click();var b=document.documentElement.getAttribute('data-theme');"
         "return [a, b];}"},
    ])
    assert report["errors"] == []
    assert report["evalResult"] == ["light", "dark"]


def test_mobile_390_has_no_horizontal_overflow(desk):
    report = desk.run([
        {"do": "eval", "script":
         "function(){var b=document.querySelector(\".nav-item[data-view='map']\");"
         "if(b)b.click();return true;}"},
        {"do": "wait", "ms": 1200},
    ])
    assert report["errors"] == []
    assert report["overflow"]["scrollWidth"] <= report["overflow"]["clientWidth"]


def test_sending_still_works_through_the_shell(desk):
    report = desk.run([
        {"do": "send", "text": "Any discount?"},
        {"do": "wait", "ms": 500},
    ])
    assert report["errors"] == []
    assert "Human review required" in report["context"]
    # the state strip shows the visible escalation chip
    assert "Human review required" in report["html"]
