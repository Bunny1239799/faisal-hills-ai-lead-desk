"""The /api/system-status surface: infrastructure truth, nothing else.

The System status view (and this route) exists so the owner can see, on
one page, that the desk is alive: the server answers, the databases
open, the desk's own stores hold their rows, the inventory serving mode
is what it should be, and what the recorded test evidence says.

The promise this module keeps:

* every number the route serves is the desk's OWN infrastructure
  counter (row counts, uptime, the recorded test count) - never a
  market figure. The inventory MODE (master vs workspace) is served;
  the master's fingerprint, row count and date range are NOT - they
  stay on the guarded ``/api/inventory/current`` surface;
* no customer text and no private field can ride on this surface
  (no preview, no raw_text, no sender, no phone, no draft);
* the counts are TRUE counts, read from the very files the
  environment points at;
* the route never fabricates: when the test-evidence file is absent,
  the ``tests`` section is ``None`` and the page says so.

The route is registered in tests/test_m5_surface_completeness.py
("checked in tests/test_system_status.py - not left unchecked").
"""

from __future__ import annotations

import json
import os
import sqlite3

import pytest

from market.fact_validator import extract_numbers

FORBIDDEN_KEYS = (
    # market figures
    "price_pkr", "size_marla", "fingerprint", "row_count", "rows",
    "observations", "observation_from", "observation_to",
    # customer / private data
    "preview", "raw_text", "sender", "phone", "message", "draft_reply",
    "lead_brief", "requirements",
)

# the segments of the payload allowed to carry numbers at all: the
# desk's own counters and identifiers of the runtime. NOT allowed:
# inventory (mode/serving), guards (booleans), status ("ok").
NUMBER_ALLOWED_SEGMENTS = ("app", "runtime", "database", "stores", "tests")


@pytest.fixture
def app():
    import app.server as server
    return server.app


@pytest.fixture(autouse=True)
def _stores(tmp_path, monkeypatch):
    """The status route reads whatever files the environment names.

    Point every store at this test's own temporary files so the route
    never touches the project's demo databases.
    """
    monkeypatch.setenv("M11_STATE_DB", str(tmp_path / "state.db"))
    monkeypatch.setenv("M11_DEMAND_DB", str(tmp_path / "demand.db"))
    monkeypatch.setenv("M12_LOG_DB", str(tmp_path / "log.db"))
    monkeypatch.setenv("LEAD_PIPELINE_DB", str(tmp_path / "pipeline.db"))
    monkeypatch.setenv("PILOT_FEEDBACK_DB", str(tmp_path / "feedback.db"))


def _get_status(app):
    from asgi_client import call_asgi

    status, body = call_asgi(app, "GET", "/api/system-status")
    assert status == 200, body
    return json.loads(body)


def _keyed_numbers(value, path=""):
    """(path, number) pairs, mirroring the M5 surface check: direct
    int/float values AND numbers extracted out of strings."""
    out = []
    if isinstance(value, bool) or value is None:
        return out
    if isinstance(value, (int, float)):
        out.append((path, float(value)))
        return out
    if isinstance(value, str):
        for _raw, number in extract_numbers(value):
            out.append((path, float(number)))
        return out
    if isinstance(value, dict):
        for key, item in value.items():
            child = str(key) if not path else path + "." + str(key)
            out.extend(_keyed_numbers(item, child))
        return out
    if isinstance(value, (list, tuple)):
        for item in value:
            out.extend(_keyed_numbers(item, path))
        return out
    return out


# ---------------------------------------------------------------------------
# the surface names itself and answers
# ---------------------------------------------------------------------------
def test_the_surface_answers_and_names_itself(app):
    payload = _get_status(app)
    assert payload["status"] == "ok"
    assert payload["app"]["name"] == "Faisal Hills AI Lead Desk"
    assert isinstance(payload["app"]["version"], str) and payload["app"]["version"]
    assert payload["inventory"]["mode"] in ("master", "workspace")
    assert payload["inventory"]["serving"] is True


def test_the_guards_report_armed_modules(app):
    payload = _get_status(app)
    assert payload["guards"]["fact_guard"] is True
    assert payload["guards"]["evidence"] is True
    assert payload["guards"]["pipeline"] is True


# ---------------------------------------------------------------------------
# the numbers on this surface are infrastructure truth only
# ---------------------------------------------------------------------------
def test_every_number_is_infrastructure_truth(app):
    payload = _get_status(app)
    stray = []
    for path, number in _keyed_numbers(payload):
        segment = path.split(".")[0]
        if segment not in NUMBER_ALLOWED_SEGMENTS:
            stray.append((path, number))
    assert stray == [], (
        "a number appeared outside the infrastructure sections: %r" % stray[:10])


def test_the_inventory_section_serves_no_market_figure(app):
    payload = _get_status(app)
    # the inventory section is the mode and nothing else - the master's
    # figures stay on the guarded /api/inventory/current surface
    assert set(payload["inventory"].keys()) == {"mode", "serving"}
    assert _keyed_numbers(payload["inventory"]) == []


def test_no_customer_text_and_no_private_field(app):
    payload = _get_status(app)

    def walk(value):
        if isinstance(value, dict):
            for key, item in value.items():
                assert str(key).lower() not in FORBIDDEN_KEYS, key
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)
        elif isinstance(value, str):
            assert "PKR" not in value, value[:80]
            assert "marla" not in value.lower(), value[:80]

    walk(payload)


# ---------------------------------------------------------------------------
# the counts are true counts of the files the environment names
# ---------------------------------------------------------------------------
def test_store_counts_are_true_counts(app, tmp_path, monkeypatch):
    log_path = tmp_path / "counted_log.db"
    conn = sqlite3.connect(str(log_path))
    try:
        conn.execute("CREATE TABLE turns (id INTEGER PRIMARY KEY, text TEXT)")
        conn.execute("CREATE TABLE actions (id INTEGER PRIMARY KEY)")
        conn.executemany("INSERT INTO turns (text) VALUES (?)",
                         [("a",), ("b",), ("c",)])
        conn.execute("INSERT INTO actions (id) VALUES (1)")
        conn.commit()
    finally:
        conn.close()

    monkeypatch.setenv("M12_LOG_DB", str(log_path))
    payload = _get_status(app)
    assert payload["stores"]["conversation_log"] == {"turns": 3, "actions": 1}


def test_the_database_section_reports_the_real_demo_db(app):
    payload = _get_status(app)
    assert payload["database"]["reachable"] is True
    tables = payload["database"]["tables"]
    assert isinstance(tables, dict) and tables
    for name, count in tables.items():
        assert isinstance(count, int) and count >= 0, name


def test_the_tests_section_reflects_the_evidence_file(app, tmp_path, monkeypatch):
    evidence = tmp_path / "evidence.json"
    evidence.write_text(json.dumps({
        "tests_collected": 1234,
        "tests_failed": 0,
        "ran_at": "2026-11-21T18:00:00+00:00",
        "command": "python -m pytest -q",
    }), encoding="utf-8")
    monkeypatch.setenv("FH_STATUS_EVIDENCE", str(evidence))
    payload = _get_status(app)
    assert payload["tests"]["collected"] == 1234
    assert payload["tests"]["failed"] == 0
    assert payload["tests"]["ran_at"].startswith("2026-11-21")

    monkeypatch.setenv("FH_STATUS_EVIDENCE", str(tmp_path / "missing.json"))
    payload = _get_status(app)
    assert payload["tests"] is None


def test_a_broken_evidence_file_makes_no_claim(app, tmp_path, monkeypatch):
    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    monkeypatch.setenv("FH_STATUS_EVIDENCE", str(broken))
    payload = _get_status(app)
    assert payload["tests"] is None
    assert payload["status"] == "ok"
