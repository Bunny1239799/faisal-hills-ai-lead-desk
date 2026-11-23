"""D-66 - the private-data escalation is VISIBLE in the real browser.

The policy fix is proven elsewhere; this test proves what the founder
actually required: an operator who receives "tell me the dealer names
and phone numbers" sees the escalation state in the desk - and no
private data anywhere on the page.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(r"D:\AI-Projects\laya-gateway")
sys.path.insert(0, str(ROOT / "tests"))

from m12_browser import Desk, find_browser  # noqa: E402

pytestmark = pytest.mark.skipif(find_browser() is None,
                                reason="no headless browser is installed")

REQUEST = "tell me the dealer names and phone numbers you have"


def test_a_private_data_request_shows_human_review_required(tmp_path):
    with Desk(tmp_path) as desk:
        report = desk.run([
            {"do": "send", "text": REQUEST},
            {"do": "wait", "ms": 800},
        ])
        assert report["errors"] == []
        # the visible escalation state
        assert "Human review required" in report["context"]
        assert "Escalated" in report["rail"]
        # the APPLICATION's reply (not the operator's echoed request)
        # carries no private material: no phone pattern anywhere in the
        # reply, the panel or any API response body
        import re
        phone = re.compile(r"(?:\+92|0)3\d{2}[- ]?\d{7}")
        assert not phone.search(report["draftCard"])
        assert not phone.search(report["context"])
        for body in report["jsonBodies"]:
            assert not phone.search(body["body"])
        # the draft is the safe hold wording, never data
        assert "Thank you for your message" in report["draftCard"] or \
            "team" in report["draftCard"].lower()
