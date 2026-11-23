"""M12.1 - privacy scan of the operator desk.

The desk must never show a dealer's name, a phone number, a plot number
or any raw text. This test renders the real page in the real browser,
lets it talk to the real server, and then scans:

* the rendered HTML of the page;
* every JSON body the page consumed.

The forbidden tokens are read from the read-only master inventory, so
the scan uses the real dealer names and the real plot numbers rather
than made-up examples. Zero leaks are allowed.
"""

from __future__ import annotations

import ast
import csv
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(r"D:\AI-Projects\laya-gateway")
sys.path.insert(0, str(ROOT / "tests"))

from m12_browser import Desk, find_browser  # noqa: E402

pytestmark = pytest.mark.skipif(find_browser() is None,
                                reason="no headless browser is installed")

PHONE_PATTERNS = [
    re.compile(r"\+92[\s\-]?\d{10,12}"),
    re.compile(r"0\d{2,3}[\s\-]?\d{7,9}\b"),
    re.compile(r"\b\d{10,12}\b"),
    re.compile(r"\b03\d{2}[\s\-]?\d{7,8}\b"),
]

PLAN = [
    {"do": "send", "text": "5 marla in block C"},
    {"do": "send", "text": "around 80 lakh"},
    {"do": "send", "text": "for investment"},
    {"do": "send", "text": "Any discount?"},
    {"do": "wait", "ms": 800},
]


def forbidden_tokens():
    """Dealer names and plot numbers from the read-only master file."""
    names = set()
    plots = set()
    with open(ROOT / "market" / "master_inventory.csv", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            plot = (row.get("plot_number") or "").strip()
            if len(plot) >= 4:
                plots.add(plot)
            chats = (row.get("source_chats") or "").strip()
            if chats.startswith("["):
                try:
                    parsed = ast.literal_eval(chats)
                except Exception:
                    parsed = []
                for name in parsed:
                    name = str(name).strip()
                    if len(name) > 3:
                        names.add(name)
    return sorted(names), sorted(plots)


def test_no_phone_number_plot_number_or_dealer_name_reaches_the_page(tmp_path):
    names, plots = forbidden_tokens()
    assert names, "the master file has no dealer names to scan against"
    assert plots, "the master file has no plot numbers to scan against"

    with Desk(tmp_path) as desk:
        report = desk.run(PLAN)

    assert report["errors"] == []
    haystacks = [("rendered page", report["html"])]
    for item in report["jsonBodies"]:
        haystacks.append((item["url"], item["body"]))

    leaks = []
    for label, text in haystacks:
        for pattern in PHONE_PATTERNS:
            for match in pattern.findall(text):
                leaks.append("%s: phone pattern %r" % (label, match))
        for name in names:
            if name.lower() in text.lower():
                leaks.append("%s: dealer name %r" % (label, name))
        for plot in plots:
            if plot.isdigit():
                if re.search(r"\b%s\b" % re.escape(plot), text):
                    leaks.append("%s: plot number %r" % (label, plot))
            elif plot.lower() in text.lower():
                leaks.append("%s: plot number %r" % (label, plot))

    assert leaks == []
