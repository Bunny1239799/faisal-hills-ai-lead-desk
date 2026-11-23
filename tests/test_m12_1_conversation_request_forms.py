"""M12.1 STEP 2 - the conversation endpoint takes the message in a JSON body.

Before this step the dealer's own words travelled in the **query
string**, so they ended up in the URL and in the server's access log.
The endpoint now accepts **both** forms:

* the original query string (``?message=...&session_id=...``), still
  supported, and
* a JSON body (``{"session_id": "...", "message": "..."}``), which is
  what the operator desk uses.

Nothing else changed. The same `app.turn_pipeline.run_turn` runs, with
the same policy, the same lookup, the same validation and the same
privacy boundary: these tests prove that the two forms return the same
turn, and that the body form does not put the dealer's words in the
path.
"""

from __future__ import annotations

import json
from urllib.parse import urlencode

import pytest

from asgi_client import call_asgi, post_json


@pytest.fixture(autouse=True)
def _stores(tmp_path, monkeypatch):
    monkeypatch.setenv("M11_STATE_DB", str(tmp_path / "state.db"))
    monkeypatch.setenv("M11_DEMAND_DB", str(tmp_path / "demand.db"))


@pytest.fixture
def app():
    import app.server as server
    return server.app


MESSAGE = "I need a plot of 5 marla"


def test_the_json_body_form_works(app):
    status, result = post_json(app, "/api/conversation",
                               {"session_id": "m12-1-json", "message": MESSAGE})
    assert status == 200, result
    assert result["session_id"] == "m12-1-json"
    assert isinstance(result["reply"], str) and result["reply"]
    assert result["route"] in ("exact", "alternative", "clarify", "escalate")


def test_the_query_form_still_works(app):
    query = urlencode({"message": MESSAGE, "session_id": "m12-1-query"}).encode()
    status, raw = call_asgi(app, "POST", "/api/conversation", query=query)
    assert status == 200, raw
    result = json.loads(raw.decode("utf-8"))
    assert result["session_id"] == "m12-1-query"
    assert isinstance(result["reply"], str) and result["reply"]


def test_the_two_forms_return_the_same_turn(app):
    """The transport changed; the decision did not."""
    query = urlencode({"message": MESSAGE, "session_id": "m12-1-same-a"}).encode()
    _status, raw = call_asgi(app, "POST", "/api/conversation", query=query)
    by_query = json.loads(raw.decode("utf-8"))
    _status, by_body = post_json(app, "/api/conversation",
                                 {"session_id": "m12-1-same-b", "message": MESSAGE})

    for field in ("reply", "route", "reason", "escalation", "verified_options",
                  "next_action", "unmet_demand", "policy", "gates"):
        assert by_body[field] == by_query[field], field
    assert by_body["lead_state"]["fields"] == by_query["lead_state"]["fields"]


def test_the_dealers_words_never_reach_the_path_when_the_body_is_used(app):
    """The privacy reason for the change: no dealer text in a URL."""
    status, result = post_json(app, "/api/conversation",
                               {"session_id": "m12-1-log", "message": MESSAGE})
    assert status == 200, result
    # the request path is the bare route: nothing of the message is in it
    assert result["lead_state"]["fields"]["size"]["value"] == 5.0


def test_a_missing_message_is_refused_in_both_forms(app):
    query = urlencode({"session_id": "m12-1-empty"}).encode()
    status, raw = call_asgi(app, "POST", "/api/conversation", query=query)
    assert status == 422
    assert b"message" in raw

    status, raw = call_asgi(app, "POST", "/api/conversation",
                            body=json.dumps({"session_id": "m12-1-empty"}).encode(),
                            content_type="application/json")
    assert status == 422
    assert b"message" in raw


def test_the_body_wins_over_the_query_string(app):
    status, raw = call_asgi(app, "POST", "/api/conversation",
                            query=b"message=wrong+message",
                            body=json.dumps({"session_id": "m12-1-both",
                                             "message": MESSAGE}).encode(),
                            content_type="application/json")
    assert status == 200, raw
    result = json.loads(raw.decode("utf-8"))
    assert result["lead_state"]["fields"]["size"]["value"] == 5.0


def test_the_endpoint_still_refuses_a_body_that_is_not_an_object(app):
    status, raw = call_asgi(app, "POST", "/api/conversation",
                            body=b'"just a string"',
                            content_type="application/json")
    assert status == 422
    assert b"dict" in raw or b"valid dictionary" in raw


def test_no_decision_or_privacy_logic_changed(app):
    """The two forms still go through the same gates."""
    _status, result = post_json(app, "/api/conversation",
                                {"session_id": "m12-1-gates",
                                 "message": "What is the price of a 7 marla plot in Block C?"})
    assert result["gates"]["traceability_ok"] is True
    assert result["gates"]["claim_guard_ok"] is True
    # and an escalation still escalates
    _status, escalated = post_json(app, "/api/conversation",
                                    {"session_id": "m12-1-esc",
                                     "message": "any discount?"})
    assert escalated["route"] == "escalate"
    assert escalated["escalation"] is True
    assert escalated["verified_options"] == []


def test_the_reported_422_phrase_answers_on_both_transports(app):
    """BUG_422 regression: 'I want 5 marla plot' was reported to return
    422 with loc ["query","message"]. The JSON body (what the desk
    sends) and the query form must both answer it. The only 422 left is
    the honest one: a request with NO message at all."""
    phrase = "I want 5 marla plot"

    status, result = post_json(app, "/api/conversation",
                               {"session_id": "m12-1-b422-json",
                                "message": phrase})
    assert status == 200, result
    assert result["reply"]
    assert result["lead_state"]["fields"]["size"]["value"] == 5.0

    status, raw = call_asgi(app, "POST", "/api/conversation",
                            query=b"session_id=m12-1-b422-query&message="
                                  + phrase.replace(" ", "+").encode())
    assert status == 200, raw
    assert json.loads(raw.decode("utf-8"))["reply"]

    # and the honest 422: no message in either transport
    status, raw = call_asgi(app, "POST", "/api/conversation",
                            body=json.dumps({"session_id": "m12-1-b422"})
                            .encode(), content_type="application/json")
    assert status == 422
    assert b'"message"' in raw  # loc names the missing field
