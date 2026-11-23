"""M5 task 2 (D-32) - the surface guard and the audit trail.

Every test in this module was written to FAIL against the code as it
stood before the M5 task-2 changes, and to PASS after them. They are
regression tests for a control, not new features.

What is covered:

  A. the guard itself
       - a valid payload passes;
       - a tampered number is caught;
       - an unsupported derived figure is caught;
       - a thin cell permits no price at all;
       - the offending values are never echoed back;
       - the guard never calls a model and never writes.

  B. the guarded serving surfaces
       - `/api/lookup` - valid, tampered, insufficient data, out of scope;
       - `/api/market`  - valid, tampered;
       - `/api/questions` - valid, tampered;
       - `/api/message` - valid, tampered.

  C. the audit trail
       - the audit row records the FINAL validated reply, not the base
         hold wording;
       - it records the traceability outcome and the fact identifiers;
       - it adds no private data and no dealer raw text.

  D. uniform validation
       - every customer-facing reply is validated, not only the market
         one;
       - the closest-match count agrees with the normal lookup count.

Run with:  .venv\\Scripts\\python.exe -m pytest tests/test_m5_surface_guard.py -q
"""

import json
import os
import re
import sqlite3
import sys
import tempfile

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from app.pipeline import handle_message  # noqa: E402
from market import fact_guard, price_lookup  # noqa: E402
from market.fact_validator import extract_numbers  # noqa: E402


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _has_price_figure(text):
    for number in re.findall(r"\d+", text or ""):
        if int(number) >= 1000:
            return True
    return False


def _jsonable(value):
    return json.dumps(value, default=str)


# ---------------------------------------------------------------------------
# A. the guard itself
# ---------------------------------------------------------------------------


def test_guard_allows_a_valid_fact_set():
    result = price_lookup.lookup_price(block="C", size_marla=7)
    allowed = fact_guard.allowed_numbers_for(block="C", size_marla=7)

    report = fact_guard.guard_payload(result["facts"], allowed, label="facts")

    assert report["ok"] is True
    assert report["untraceable"] == []
    assert report["untraceable_count"] == 0


def test_guard_catches_a_tampered_median():
    """The control's core property: a figure that the master does not
    support is caught."""
    result = price_lookup.lookup_price(block="C", size_marla=7)
    allowed = fact_guard.allowed_numbers_for(block="C", size_marla=7)

    tampered = dict(result["facts"])
    tampered["price_median_pkr"] = 9999999

    report = fact_guard.guard_payload(tampered, allowed, label="facts")

    assert report["ok"] is False
    assert report["untraceable_count"] == 1


def test_guard_catches_an_unsupported_derived_figure():
    """A per-marla price is a DERIVED number. The master does not support
    it, so it must not be servable."""
    result = price_lookup.lookup_price(block="C", size_marla=7)
    allowed = fact_guard.allowed_numbers_for(block="C", size_marla=7)

    derived = dict(result["facts"])
    derived["price_per_marla_pkr"] = 1128571.43

    report = fact_guard.guard_payload(derived, allowed, label="facts")

    assert report["ok"] is False


def test_guard_permits_no_price_for_a_thin_cell():
    """A cell that is too thin to answer must not permit a price - not
    even the price the master actually holds for it."""
    result = price_lookup.lookup_price(block="B", size_marla=7)
    allowed = fact_guard.allowed_numbers_for(block="B", size_marla=7)

    # The master DOES hold a median for B/7; the guard must not permit it.
    master_median = 7750000.0
    assert master_median not in allowed

    # A payload carrying that median is blocked.
    tampered = dict(result["facts"])
    tampered["price_median_pkr"] = master_median
    report = fact_guard.guard_payload(tampered, allowed, label="facts")
    assert report["ok"] is False

    # And the real, price-free payload passes.
    report = fact_guard.guard_payload(result["facts"], allowed, label="facts")
    assert report["ok"] is True


def test_guard_never_echoes_the_offending_value():
    """A guard that re-publishes the number it just refused to serve
    defeats the control."""
    allowed = fact_guard.allowed_numbers_for(block="C", size_marla=7)
    report = fact_guard.guard_payload(
        {"price_median_pkr": 9999999}, allowed, label="facts"
    )

    assert report["ok"] is False
    blob = _jsonable(report)
    assert "9999999" not in blob
    assert "9999999" not in blob.replace(" ", "")
    assert report["untraceable"] == [{"redacted": True}]


def test_guard_never_calls_a_model_and_never_writes():
    """The guard is stdlib-only and side-effect free (RULES_SHORT #1, #5)."""
    source = open(
        os.path.join(PROJECT_ROOT, "market", "fact_guard.py"), encoding="utf-8"
    ).read()

    for forbidden in ("requests", "httpx", "urllib", "openai", "anthropic",
                      "llama", "ollama", "laya", "subprocess"):
        assert forbidden not in source.lower(), (
            "fact_guard.py references %r" % forbidden
        )

    for forbidden in ("INSERT ", "UPDATE ", "DELETE ", "commit("):
        assert forbidden not in source, (
            "fact_guard.py writes to the database (%r)" % forbidden
        )


def test_the_guard_does_not_modify_the_approved_master():
    import hashlib

    master = price_lookup.MASTER_PATH
    if not os.path.exists(master):
        pytest.skip("approved master is not present at its configured path")

    def digest():
        h = hashlib.sha256()
        with open(master, "rb") as handle:
            for chunk in iter(lambda: handle.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()

    before = digest()
    for block, size in (("A", 5), ("B", 7), ("C", 7), ("C", 20)):
        allowed = fact_guard.allowed_numbers_for(block=block, size_marla=size)
        fact_guard.guard_payload({"x": 1}, allowed)
    assert digest() == before


# ---------------------------------------------------------------------------
# B. the guarded serving surfaces
# ---------------------------------------------------------------------------


def test_api_lookup_serves_a_valid_answer_with_a_guard_report():
    import app.server as server

    payload = server.lookup_endpoint(block="C", size_marla=7)

    assert payload["answerable"] is True
    assert payload["summary"]["price_median_pkr"] == 7900000
    assert payload["guard"]["ok"] is True
    assert payload["guard"]["action"] == "allowed"
    assert payload["guard"]["untraceable_count"] == 0


def test_api_lookup_blocks_a_tampered_fact_set():
    """The endpoint must withhold a fact set the master does not support.

    The tampering is done by patching the lookup, which is exactly the
    failure mode the control exists for: a lookup that returns a wrong
    number must not be able to serve it.
    """
    import app.server as server

    original = price_lookup.lookup_price

    def tampered_lookup(*args, **kwargs):
        result = original(*args, **kwargs)
        facts = result.get("facts")
        if isinstance(facts, dict) and facts.get("price_median_pkr"):
            facts = dict(facts)
            facts["price_median_pkr"] = 9999999
            result = dict(result)
            result["facts"] = facts
        return result

    price_lookup.lookup_price = tampered_lookup
    try:
        payload = server.lookup_endpoint(block="C", size_marla=7)
    finally:
        price_lookup.lookup_price = original

    assert payload["answerable"] is False
    assert payload["reply_mode"] == "blocked_unverified_numbers"
    assert payload["facts"] is None
    assert payload["summary"] is None
    assert payload["guard"]["ok"] is False
    assert payload["guard"]["untraceable_count"] >= 1
    # The refused number is nowhere in the response.
    assert "9999999" not in _jsonable(payload)


def test_api_lookup_carries_no_price_for_insufficient_data():
    import app.server as server

    payload = server.lookup_endpoint(block="B", size_marla=7)

    assert payload["answerable"] is False
    facts = payload["facts"] or {}
    for key in ("price_min_pkr", "price_median_pkr", "price_max_pkr"):
        assert facts.get(key) is None
    assert not _has_price_figure(payload.get("reply") or "")
    assert payload["guard"]["ok"] is True


def test_api_lookup_serves_no_price_for_a_parked_block():
    import app.server as server

    payload = server.lookup_endpoint(block="E", size_marla=10)

    assert payload["answerable"] is False
    assert payload["facts"] is None
    assert not _has_price_figure(_jsonable(payload))
    assert payload["guard"]["ok"] is True


def test_api_market_serves_a_valid_table_with_guarded_rows():
    import app.server as server

    payload = server.get_market_stats()

    assert payload["active_blocks"] == ["A", "B", "C"]
    assert len(payload["results"]) > 0
    assert payload["guard"]["ok"] is True
    for row in payload["results"]:
        assert row["guard"]["ok"] is True
        assert row["guard"]["action"] == "allowed"


def test_api_market_blocks_a_tampered_row():
    """A market row whose figures do not match the master is served with
    its numbers removed."""
    import app.server as server

    original = price_lookup.lookup_price

    def tampered_lookup(*args, **kwargs):
        result = original(*args, **kwargs)
        facts = result.get("facts")
        if isinstance(facts, dict) and facts.get("price_median_pkr"):
            facts = dict(facts)
            facts["price_median_pkr"] = 9999999
            result = dict(result)
            result["facts"] = facts
        return result

    price_lookup.lookup_price = tampered_lookup
    try:
        payload = server.get_market_stats()
    finally:
        price_lookup.lookup_price = original

    blocked = [r for r in payload["results"] if r["guard"]["ok"] is False]
    assert blocked, "the tampered row was not blocked"
    for row in blocked:
        assert row["price_median_pkr"] is None
        assert row["matched_plots"] is None
        assert row["answerable_for_demo"] is False
    assert "9999999" not in _jsonable(payload)


def test_api_questions_serves_verified_expectations():
    import app.server as server

    payload = server.questions_endpoint()

    assert len(payload["questions"]) == 20
    assert payload["guard"]["ok"] is True
    for case in payload["questions"]:
        assert case["expectations_verified"] is True
        assert case["guard"]["ok"] is True


def test_api_questions_blocks_a_wrong_expectation():
    """A hand-recorded expectation the master does not support must not
    be served as if it were the master's answer."""
    import app.server as server

    original = price_lookup.load_questions

    def tampered_questions(path=None):
        config = original(path)
        config = json.loads(_jsonable(config))
        for case in config["questions"]:
            if case.get("id") == 11:
                case["expect_median_pkr"] = 12345678
        return config

    price_lookup.load_questions = tampered_questions
    try:
        payload = server.questions_endpoint()
    finally:
        price_lookup.load_questions = original

    assert payload["guard"]["ok"] is False
    blocked = [c for c in payload["questions"] if c["guard"]["ok"] is False]
    assert blocked
    for case in blocked:
        assert case["expect_median_pkr"] is None
        assert case["expectations_verified"] is False
    assert "12345678" not in _jsonable(payload)


def test_api_message_guards_the_served_fact_set():
    import app.server as server

    payload = server.handle_message_endpoint(
        "What is the price of a 7 marla plot in Block C?"
    )

    assert payload["guard"]["ok"] is True
    assert payload["traceability_ok"] is True
    facts = (payload.get("market_facts") or {}).get("facts") or {}
    assert facts["price_median_pkr"] == 7900000


def test_api_message_detaches_a_tampered_fact_set():
    """The customer-facing surface must not serve a fact set the master
    does not support, and must escalate instead.

    The tampered figure here is one that does NOT appear in the reply
    (``distinct_source_chats``), so the pipeline's own reply validation
    cannot see it. Only the server's fact-set guard can - which is
    exactly the hole D-32 was about.
    """
    import app.server as server

    original = price_lookup.lookup_price

    def tampered_lookup(*args, **kwargs):
        result = original(*args, **kwargs)
        facts = result.get("facts")
        if isinstance(facts, dict) and facts.get("price_median_pkr"):
            facts = dict(facts)
            facts["distinct_source_chats"] = 99
            result = dict(result)
            result["facts"] = facts
        return result

    price_lookup.lookup_price = tampered_lookup
    try:
        payload = server.handle_message_endpoint(
            "What is the price of a 7 marla plot in Block C?"
        )
    finally:
        price_lookup.lookup_price = original

    assert payload["market_facts"] is None
    assert payload["facts_used"] == []
    assert payload["needs_human"] is True
    assert payload["decision"]["action"] == "escalate"
    assert "unverified_fact_set" in payload["decision"]["reasons"]
    assert payload["guard"]["ok"] is False
    assert "99" not in _jsonable(payload.get("market_facts"))


def test_api_message_blocks_a_tampered_median_before_it_can_be_served():
    """A tampered figure that DOES appear in the reply is caught by the
    pipeline's own validation first, so the reply never carries it."""
    import app.server as server

    original = price_lookup.lookup_price

    def tampered_lookup(*args, **kwargs):
        result = original(*args, **kwargs)
        facts = result.get("facts")
        if isinstance(facts, dict) and facts.get("price_median_pkr"):
            facts = dict(facts)
            facts["price_median_pkr"] = 9999999
            result = dict(result)
            result["facts"] = facts
        return result

    price_lookup.lookup_price = tampered_lookup
    try:
        payload = server.handle_message_endpoint(
            "What is the price of a 7 marla plot in Block C?"
        )
    finally:
        price_lookup.lookup_price = original

    assert payload["market_facts"] is None
    assert payload["facts_used"] == []
    assert payload["needs_human"] is True
    assert payload["decision"]["action"] == "escalate"
    assert "untraceable_number_in_draft" in payload["decision"]["reasons"]
    assert "9999999" not in _jsonable(payload)


# ---------------------------------------------------------------------------
# C. the audit trail
# ---------------------------------------------------------------------------


def _audit_rows(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        return [dict(row) for row in conn.execute(
            "SELECT * FROM audit_log ORDER BY audit_id"
        )]
    finally:
        conn.close()


@pytest.fixture()
def audit_db(monkeypatch, tmp_path):
    """Point the pipeline at a throwaway database and return its path."""
    import data.db as data_db

    target = str(tmp_path / "audit_test.db")
    conn = data_db.init_db(target)
    conn.close()

    monkeypatch.setenv("DB_PATH", target)
    return target


def test_the_audit_row_records_the_final_validated_reply(audit_db):
    """The gap: the base handler wrote the PRE-market hold wording, so the
    operator's record of what the system actually said was missing."""
    result = handle_message("What is the price of a 7 marla plot in Block C?")

    assert result.get("audit", {}).get("recorded") is True

    rows = _audit_rows(audit_db)
    assert len(rows) == 1
    row = rows[0]

    # The final reply, not the base hold wording.
    assert "PKR" in row["output_text"]
    assert "7,900,000" in row["output_text"]
    assert "We will get back to you shortly" not in row["output_text"]

    # The validation outcome and the fact identifiers.
    payload = json.loads(row["decision_payload"])
    assert payload["reply_validated"] is True
    assert payload["traceability_ok"] is True
    assert payload["traceability_blocked"] is False
    assert payload["reply_mode"] == "verified_market_facts"
    assert payload["market_filters"]["block"] == "C"
    assert payload["market_filters"]["size_marla"] == 7.0
    assert payload["facts_source"] == "FaisalHills verified partial master"

    fact_ids = json.loads(row["fact_ids_used"])
    assert any("price_median_pkr" in f for f in fact_ids)
    assert any("matched_plots" in f for f in fact_ids)

    # The base decision fields are preserved, not replaced.
    assert "action" in payload
    assert "reasons" in payload
    assert "needs_human" in payload


def test_the_audit_row_adds_no_private_data(audit_db):
    """The correction adds only what the application produced."""
    handle_message("What is the price of a 7 marla plot in Block C?")

    rows = _audit_rows(audit_db)
    blob = _jsonable(rows)

    assert "raw_text" not in blob
    assert "sender" not in blob.lower() or "sender_count_available" in blob
    assert "AB YOU Properties" not in blob
    assert "Chanar valley" not in blob
    # No phone-like number other than the prices themselves.
    for raw in re.findall(r"(?:\+?92|0)3\d{2}[\s-]?\d{7}", blob):
        pytest.fail("a phone-like number reached the audit trail: %r" % raw)


def test_the_audit_row_records_a_blocked_reply(audit_db):
    """A reply that was blocked must also be recorded - with the block."""
    import app.pipeline as pipeline

    original = pipeline._fact_validator.validate_reply

    def fake_validate(reply, facts=None, context=None):
        from market.fact_validator import TraceabilityResult

        return TraceabilityResult(
            ok=False,
            untraceable=[("9,999,999", 9999999.0)],
            numbers=[("9,999,999", 9999999.0)],
            allowed_count=3,
            reason="Number(s) in the reply do not trace to an approved fact.",
        )

    pipeline._fact_validator.validate_reply = fake_validate
    try:
        result = handle_message("What is the price of a 7 marla plot in Block C?")
    finally:
        pipeline._fact_validator.validate_reply = original

    assert result.get("traceability_blocked") is True

    rows = _audit_rows(audit_db)
    assert len(rows) == 1
    payload = json.loads(rows[0]["decision_payload"])
    assert payload["traceability_ok"] is False
    assert payload["traceability_blocked"] is True
    # The blocked reply (the hold wording) is what was recorded.
    assert "PKR" not in rows[0]["output_text"]


def test_the_audit_endpoint_guards_each_recorded_reply(audit_db):
    """`/api/audit` serves numbers in prose, so each recorded reply is
    checked against the approved master."""
    import app.server as server

    handle_message("What is the price of a 7 marla plot in Block C?")

    rows = server.get_audit()
    assert len(rows) == 1
    row = rows[0]
    assert row["verified"] is True
    assert row["guard"]["ok"] is True
    assert row["guard"]["numbers_found"] > 0


def test_a_record_that_cannot_be_checked_is_not_reported_as_verified(audit_db):
    """A record that predates the M5 audit record carries no filter, so
    it cannot be checked. "Not checkable" must never be presented as
    "verified"."""
    import app.server as server

    handle_message("What is the price of a 7 marla plot in Block C?")

    # Write a row in the pre-M5 shape.
    conn = sqlite3.connect(audit_db)
    conn.execute(
        """
        INSERT INTO audit_log (lead_id, step, input_text, output_text,
                               decision_payload, fact_ids_used, created_at)
        VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
        """,
        (
            "legacy-lead",
            "message_received",
            "an old message",
            "Based on 21 matching listings ... median of PKR 7,900,000.",
            json.dumps({"action": "answer", "reasons": [], "risk_tags": [],
                        "needs_human": False}),
            "[]",
        ),
    )
    conn.commit()
    conn.close()

    rows = server.get_audit()
    legacy = [r for r in rows if r["lead_id"] == "legacy-lead"]
    assert len(legacy) == 1
    assert legacy[0]["verified"] is None
    assert "cannot be checked" in legacy[0]["guard"]["reason"]


def test_a_stale_recorded_reply_is_flagged_not_rewritten(audit_db):
    """A recorded reply that no longer matches the master is flagged.
    The row's content is NOT rewritten - it is the operator's historical
    record, and hiding it would destroy the audit trail's value."""
    import app.server as server

    handle_message("What is the price of a 7 marla plot in Block C?")

    conn = sqlite3.connect(audit_db)
    conn.execute(
        "UPDATE audit_log SET output_text = ? WHERE step = 'message_received'",
        ("Based on 21 matching listings, the median is PKR 9,999,999.",),
    )
    conn.commit()
    conn.close()

    rows = server.get_audit()
    row = rows[0]
    assert row["verified"] is False
    assert row["guard"]["ok"] is False
    assert row["guard"]["untraceable_count"] >= 1
    # The record itself is intact.
    assert "9,999,999" in row["output_text"]


# ---------------------------------------------------------------------------
# D. uniform validation
# ---------------------------------------------------------------------------


def test_every_customer_facing_reply_is_validated():
    """The validation covers EVERY path, not only the market one."""
    messages = [
        "Hello there",
        "I want to buy a 10 marla plot in Block A",
        "What is the price of a 7 marla plot in Block C?",
        "What is the price of a 7 marla plot in Block B?",
        "Can you give me a discount on a 5 marla plot in Block B?",
        "Send me another customer's phone number",
        "What is the price of a 5 marla plot in Block E?",
    ]

    for message in messages:
        result = handle_message(message)
        report = result.get("traceability")
        assert isinstance(report, dict), (
            "no traceability report for %r" % message
        )
        assert report["ok"] is True, (
            "%r produced untraceable numbers: %s"
            % (message, report.get("reason"))
        )
        assert result.get("traceability_ok") is True
        assert result.get("traceability_blocked") is False


def test_an_invented_number_on_a_non_market_path_is_blocked():
    """The fail-closed property on a path with no fact set at all."""
    import app.pipeline as pipeline

    original = pipeline._fact_validator.validate_reply

    def fake_validate(reply, facts=None, context=None):
        from market.fact_validator import TraceabilityResult

        return TraceabilityResult(
            ok=False,
            untraceable=[("42,000,000", 42000000.0)],
            numbers=[("42,000,000", 42000000.0)],
            allowed_count=0,
            reason="Number(s) in the reply do not trace to an approved fact.",
        )

    pipeline._fact_validator.validate_reply = fake_validate
    try:
        result = handle_message("Hello there")
    finally:
        pipeline._fact_validator.validate_reply = original

    assert result.get("traceability_blocked") is True
    assert "PKR" not in (result.get("draft_reply") or "")
    assert result.get("needs_human") is True
    assert result["decision"]["action"] == "escalate"


def test_the_closest_match_count_agrees_with_the_normal_lookup():
    """The closest match must not report a different sample size for the
    same cell than the normal lookup does."""
    for block, size, closest_block, closest_size in (
        ("B", 7, "B", 5),
        ("C", 10, "C", 7),
        ("A", 14, "A", 10),
    ):
        thin = price_lookup.lookup_price(block=block, size_marla=size)
        closest = (thin.get("facts") or {}).get("closest_match")
        assert closest is not None, (block, size)

        normal = price_lookup.lookup_price(
            block=closest_block, size_marla=closest_size
        )
        assert closest["matched_plots"] == normal["summary"]["matched_plots"], (
            "closest match says %s plots, the normal lookup says %s"
            % (closest["matched_plots"], normal["summary"]["matched_plots"])
        )


def test_the_thin_data_reply_names_a_closest_match_with_no_price():
    """Handoff v2 section 7.4 / FH-02 R17."""
    result = price_lookup.lookup_price(block="B", size_marla=7)
    reply = result["reply"]

    closest = (result.get("facts") or {}).get("closest_match")
    assert closest is not None
    assert "closest match" in reply.lower()
    assert not _has_price_figure(reply)
    assert "PKR" not in reply


def test_the_thin_data_fact_set_carries_no_price_at_all():
    """The M5 (D-34) fix: a refused query must not leak a price through
    the fact set, the summary or the closest-match block."""
    result = price_lookup.lookup_price(block="B", size_marla=7)

    for container in (result["facts"], result["summary"]):
        for key in ("price_min_pkr", "price_median_pkr", "price_max_pkr"):
            assert container.get(key) is None, (key, container.get(key))

    closest = result["facts"].get("closest_match")
    for key in ("price_min_pkr", "price_median_pkr", "price_max_pkr"):
        assert key not in closest


def test_the_adapter_carries_no_price_for_a_thin_cell():
    """`app/market_adapter` is a PUBLIC function other code can call, and
    it used to return the median of a cell the product had refused to
    answer."""
    from app.market_adapter import get_verified_market_facts

    facts = get_verified_market_facts(block="B", size_marla=7)["facts"]

    assert facts["answerable_for_demo"] is False
    for key in ("price_min_pkr", "price_median_pkr", "price_max_pkr"):
        assert facts.get(key) is None, (key, facts.get(key))
    assert facts["reply_mode"] == "insufficient_data"
    # The closest match is shown instead of a number.
    assert facts.get("closest_match") is not None


def test_the_adapter_still_answers_an_answerable_cell():
    from app.market_adapter import get_verified_market_facts

    facts = get_verified_market_facts(block="C", size_marla=7)["facts"]

    assert facts["matched_plots"] == 21
    assert facts["price_median_pkr"] == 7900000
    assert facts["answerable_for_demo"] is True


def test_the_adapter_is_guarded_against_a_tampered_lookup():
    """The adapter must not hand a consumer a fact set the master does
    not support."""
    from app.market_adapter import get_verified_market_facts

    original = price_lookup.lookup_price

    def tampered_lookup(*args, **kwargs):
        result = original(*args, **kwargs)
        facts = result.get("facts")
        if isinstance(facts, dict) and facts.get("price_median_pkr"):
            facts = dict(facts)
            facts["price_median_pkr"] = 9999999
            result = dict(result)
            result["facts"] = facts
        return result

    price_lookup.lookup_price = tampered_lookup
    try:
        facts = get_verified_market_facts(block="C", size_marla=7)["facts"]
    finally:
        price_lookup.lookup_price = original

    assert facts["price_median_pkr"] is None
    assert facts["answerable_for_demo"] is False
    assert facts["guard"]["ok"] is False
    assert "9999999" not in _jsonable(facts)
