"""M11.4 / M11.5 - the conversation endpoint and the operator page.

The endpoint takes a session id and a message and returns the reply, the
lead state, the route, the reason, the escalation flag and, when the
application could not answer, an unmet-demand record that carries a
size, a block and a budget band and nothing else.

The operator page is one plain HTML page served by the same server. It
shows the conversation, the qualification state (with the unknown
fields visible), the verified options with the reason, the next action
and the take-over button. It is a **draft** surface: the application
drafts, the human sends.
"""

from __future__ import annotations

import re
import uuid

import pytest

import app.server as server
from market import fact_guard
from market.fact_validator import extract_numbers

_PLOT_NUMBER = re.compile(r"\b[A-Z]{1,2}-\d{2,}\b")


@pytest.fixture(autouse=True)
def _stores(tmp_path, monkeypatch):
    monkeypatch.setenv("M11_STATE_DB", str(tmp_path / "state.db"))
    monkeypatch.setenv("M11_DEMAND_DB", str(tmp_path / "demand.db"))


def _allowed_numbers():
    """Every number the approved master may serve, for any in-scope cell."""
    allowed = set()
    for block in ("A", "B", "C"):
        for size in (5, 7, 10, 14, 20, 40):
            allowed |= fact_guard.allowed_numbers_for(block=block,
                                                     size_marla=size)
    return allowed


def test_the_conversation_endpoint_returns_the_whole_turn():
    session_id = "ep-" + uuid.uuid4().hex[:8]
    result = server.conversation_endpoint(
        message="I want a 7 marla plot in Block C",
        session_id=session_id,
        username="tester",
    )

    assert result["session_id"] == session_id
    assert result["route"] in ("exact", "alternative", "clarify", "escalate")
    assert isinstance(result["reply"], str) and result["reply"]
    assert result["reason"]
    assert result["escalation"] is False

    state = result["lead_state"]["fields"]
    assert state["size"]["value"] == 7.0
    assert state["size"]["status"] == "stated"
    assert state["block"]["value"] == "C"
    assert state["budget"]["status"] == "unknown"
    assert state["budget"]["value"] is None


def test_the_conversation_endpoint_serves_only_traceable_facts():
    result = server.conversation_endpoint(
        message="What is the price of a 7 marla plot in Block C?",
        session_id="ep-" + uuid.uuid4().hex[:8],
        username="tester",
    )
    reply = result["reply"]
    assert not _PLOT_NUMBER.search(reply)
    untraceable = {value for _text, value in extract_numbers(reply)} \
        - _allowed_numbers()
    assert untraceable == set(), (
        "/api/conversation served an untraceable fact number: %r"
        % sorted(untraceable)
    )


def test_a_discount_request_escalates_and_names_no_option():
    result = server.conversation_endpoint(
        message="Can you give me 20% discount on a 5 marla plot in Block C?",
        session_id="ep-" + uuid.uuid4().hex[:8],
        username="tester",
    )
    assert result["route"] == "escalate"
    assert result["escalation"] is True
    assert result["verified_options"] == []


def test_the_state_endpoint_reads_the_conversation_without_a_new_turn():
    session_id = "ep-" + uuid.uuid4().hex[:8]
    server.conversation_endpoint(message="5 marla", session_id=session_id,
                                 username="tester")
    state = server.conversation_state_endpoint(session_id=session_id,
                                                username="tester")
    assert state["session_id"] == session_id
    assert state["lead_state"]["fields"]["size"]["value"] == 5.0
    assert "block" in state["unknowns"]


def test_the_take_over_endpoint_records_a_human_and_changes_nothing():
    session_id = "ep-" + uuid.uuid4().hex[:8]
    before = server.conversation_endpoint(message="5 marla",
                                          session_id=session_id,
                                          username="tester")
    taken = server.conversation_take_over_endpoint(session_id=session_id,
                                                    username="tester")
    assert taken["taken_over"] is True
    assert taken["taken_over_at"]

    after = server.conversation_state_endpoint(session_id=session_id,
                                               username="tester")
    assert after["taken_over_at"] == taken["taken_over_at"]
    assert after["lead_state"]["fields"] == \
        before["lead_state"]["fields"]


def test_the_unmet_demand_endpoint_carries_no_private_data():
    server.conversation_endpoint(
        message="I need a 14 marla plot in Block A",
        session_id="ep-" + uuid.uuid4().hex[:8],
        username="tester",
    )
    payload = server.unmet_demand_endpoint(limit=20, username="tester")
    assert payload["count"] >= 1
    for shape in payload["shapes"]:
        assert set(shape) <= {"size_marla", "block", "budget_band", "count"}
        assert not _PLOT_NUMBER.search(str(shape))


def test_the_operator_page_shows_the_three_panels_and_the_take_over():
    from fastapi.responses import HTMLResponse

    response = server.operator_page(username="tester")
    assert isinstance(response, HTMLResponse)
    html = response.body.decode("utf-8")
    for marker in ("Lead desk", "Requirements",
                   "Verified options", "Recommendation", "Take over"):
        assert marker in html, marker
    # the page talks to the endpoints the server already serves.
    # M12.1 moved the behaviour into app/static/operator.js, so the
    # endpoints are asserted in the script the page loads.
    from pathlib import Path
    script = (Path(server.__file__).parent / "static" /
              "operator.js").read_text(encoding="utf-8")
    assert "/api/conversation" in script
    assert "/api/unmet-demand" in script
