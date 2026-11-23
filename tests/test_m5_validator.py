"""M5 - number / traceability validator tests.

Covers the FH-02 section 6 M5 acceptance criteria:

  (a) every number in a valid A/B/C answer is present in the fact set;
  (b) a deliberately corrupted draft (number not in facts) is **blocked** and
      routed to human;
  (c) "not enough data" replies contain no numbers;
  (d) the red-team set shows **0** unsupported-claim leakage;
  (e) 100% price-reply traceability.

The validator is stdlib-only (RULES_SHORT #5): it makes no LLM, llama.cpp,
Laya, Ollama or Gemini call, and it neither reads nor writes the approved
master or the owner's database.
"""

import io
import json
import os
import re
import sys

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from app.pipeline import handle_message  # noqa: E402
from market import price_lookup  # noqa: E402
from market.fact_validator import (  # noqa: E402
    build_allowed_numbers,
    extract_numbers,
    validate_reply,
)

REDTEAM_PATH = os.path.join(
    PROJECT_ROOT, "evaluation", "datasets", "production", "redteam_v1.jsonl"
)

# The answerable A/B/C cells are DERIVED from the approved master, not
# hand-listed. A hand-written list silently fell behind the data (A/20 and
# B/20 were missing) - which is exactly the kind of gap the M5 control
# exists to remove. Deriving it means the list cannot drift again.
BLOCKS = ("A", "B", "C")
SIZES = (5, 7, 10, 14, 20)


def _measure_answerable_cells():
    """Every A/B/C block/size cell, and whether the policy can answer it."""
    measured = []
    for block in BLOCKS:
        for size_marla in SIZES:
            result = price_lookup.lookup_price(block=block, size_marla=size_marla)
            facts = result.get("facts") or {}
            measured.append(
                (
                    block,
                    size_marla,
                    bool(facts.get("answerable_for_demo")),
                    facts.get("matched_plots"),
                )
            )
    return measured


MEASURED_CELLS = _measure_answerable_cells()
ANSWERABLE = [(b, s) for (b, s, ok, _n) in MEASURED_CELLS if ok]
THIN = [(b, s) for (b, s, ok, _n) in MEASURED_CELLS if not ok]


def test_m5_every_answerable_cell_is_covered_by_the_acceptance_evidence():
    """The acceptance evidence must cover EVERY answerable cell.

    A hand-kept list had drifted (A/20 and B/20 were answerable but not
    listed), so the count is asserted against the master itself.
    """
    assert len(ANSWERABLE) == 11, (
        "the answerable cell count changed: %r" % (ANSWERABLE,)
    )
    assert len(THIN) == 4, "the thin cell count changed: %r" % (THIN,)
    # Every listed combination really is answerable, and every cell that is
    # not listed really is not.
    for block, size_marla, ok, _n in MEASURED_CELLS:
        assert ok == ((block, size_marla) in ANSWERABLE)


def test_m5_the_thin_cells_are_the_ones_without_enough_listings():
    for block, size_marla in THIN:
        result = price_lookup.lookup_price(block=block, size_marla=size_marla)
        facts = result.get("facts") or {}
        assert facts.get("answerable_for_demo") is False
        assert facts.get("price_min_pkr") is None
        assert facts.get("price_median_pkr") is None
        assert facts.get("price_max_pkr") is None


# ---------------------------------------------------------------------------
# (a) every number in a valid answer traces to the fact set
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("block,size_marla", ANSWERABLE)
def test_m5_every_number_in_a_valid_answer_traces_to_the_fact_set(block, size_marla):
    result = price_lookup.lookup_price(block=block, size_marla=size_marla)
    facts = result["facts"]
    reply = result["reply"]

    validation = validate_reply(reply, facts, context={"size_marla": size_marla})

    assert validation.ok is True, (
        "%s/%s produced untraceable numbers %r (reason: %s)"
        % (block, size_marla, validation.untraceable, validation.reason)
    )
    assert validation.untraceable == []


def test_m5_the_reply_numbers_are_a_subset_of_the_fact_set():
    """Every number in the reply must literally be a fact, not merely a
    value that happens to be allowed by a context entry."""
    result = price_lookup.lookup_price(block="C", size_marla=7)
    facts = result["facts"]
    allowed = build_allowed_numbers(facts, None)

    for _raw, value in extract_numbers(result["reply"]):
        assert value in allowed


def test_m5_the_pipeline_reports_traceability_on_a_real_answer():
    result = handle_message("What is the price of a 7 marla plot in Block C?")

    assert result.get("traceability_ok") is True
    assert result.get("traceability_blocked") is False
    report = result.get("traceability")
    assert isinstance(report, dict)
    assert report["ok"] is True
    assert report["untraceable"] == []
    assert report["numbers_found"] > 0


# ---------------------------------------------------------------------------
# (b) a corrupted draft is blocked and routed to a human
# ---------------------------------------------------------------------------


def test_m5_a_corrupted_draft_is_blocked():
    result = price_lookup.lookup_price(block="C", size_marla=7)
    facts = result["facts"]
    corrupted = result["reply"].replace("7,900,000", "9,999,999")

    validation = validate_reply(corrupted, facts, context={"size_marla": 7})

    assert validation.ok is False
    assert ("9,999,999", 9999999.0) in validation.untraceable
    assert "9,999,999" in validation.reason


def test_m5_an_invented_guarantee_and_return_claim_is_blocked():
    """The classic failure mode: a confident, untraceable price plus a
    promise. Both numbers must be caught."""
    result = price_lookup.lookup_price(block="C", size_marla=7)
    fabricated = result["reply"] + " Guaranteed PKR 25,000,000 with 100% returns."

    validation = validate_reply(fabricated, result["facts"], context={"size_marla": 7})

    assert validation.ok is False
    flagged = {raw for raw, _ in validation.untraceable}
    assert "25,000,000" in flagged
    assert "100" in flagged


def test_m5_a_reply_with_numbers_but_no_fact_set_fails_closed():
    """No fact set means no number is permitted. The validator must not
    pass an untraceable reply through."""
    validation = validate_reply("The price is PKR 7,900,000 for 21 plots.", None)

    assert validation.ok is False
    assert len(validation.untraceable) == 2


def test_m5_an_unknown_fact_does_not_whitelist_anything():
    """Unknown means unknown: a None price contributes nothing."""
    allowed = build_allowed_numbers(
        {
            "price_min_pkr": None,
            "price_median_pkr": None,
            "price_max_pkr": None,
            "matched_plots": 21,
            "latest_date": "2026-10-07",
        },
        None,
    )

    assert 7900000.0 not in allowed
    assert 21.0 in allowed


# ---------------------------------------------------------------------------
# (c) "not enough data" replies carry no numbers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("block,size_marla", THIN)
def test_m5_thin_data_reply_carries_no_price_figure(block, size_marla):
    """A not-enough-data reply carries no PRICE.

    Handoff v2 section 7.4 requires it to "show the closest match instead of
    a number" - the closest match is a real cell of the approved master, so
    naming its size in marla is an approved fact, not a price. The rule the
    product has always applied is the one in ``price_lookup._reply_has_price``
    and the M2/M3 regression tests: a number of 1000 or more is a price
    figure.
    """
    result = price_lookup.lookup_price(block=block, size_marla=size_marla)
    reply = result["reply"]

    # No price figure.
    for _raw, value in extract_numbers(reply):
        assert value < 1000, "a price figure reached the not-enough-data reply"
    assert "PKR" not in reply

    # Every number that IS present traces to an approved fact.
    validation = validate_reply(
        reply, result["facts"], context={"size_marla": size_marla}
    )
    assert validation.ok is True, validation.reason

    # The closest match is shown, and it carries no price of its own.
    closest = (result.get("facts") or {}).get("closest_match")
    assert closest is not None
    assert closest["size_marla"] is not None
    for price_key in ("price_min_pkr", "price_median_pkr", "price_max_pkr"):
        assert price_key not in closest
    for _raw, value in extract_numbers(json.dumps(closest)):
        assert value < 1000, "the closest match carried a price figure"

    # And the customer-facing path agrees.
    customer = handle_message(
        "What is the price of a %s marla plot in Block %s?" % (size_marla, block)
    )
    customer_reply = customer.get("draft_reply") or ""
    assert "PKR" not in customer_reply
    for _raw, value in extract_numbers(customer_reply):
        assert value < 1000
    assert customer.get("traceability_ok") is True


def test_m5_a_blocked_reply_is_actually_blocked_in_the_pipeline():
    """Simulate a compromised reply reaching the pipeline's validation point.

    The pipeline must replace the reply, detach the market facts and raise
    ``needs_human`` - not merely record that something was wrong.
    """
    import app.pipeline as pipeline

    original = pipeline._fact_validator.validate_reply
    calls = {"n": 0}

    def fake_validate(reply, facts=None, context=None):
        calls["n"] += 1
        if "PKR" in (reply or ""):
            from market.fact_validator import TraceabilityResult

            return TraceabilityResult(
                ok=False,
                untraceable=[("9,999,999", 9999999.0)],
                numbers=[("9,999,999", 9999999.0)],
                allowed_count=3,
                reason="Number(s) in the reply do not trace to an approved fact: '9,999,999'.",
            )
        return original(reply, facts, context)

    pipeline._fact_validator.validate_reply = fake_validate
    try:
        result = handle_message("What is the price of a 7 marla plot in Block C?")
    finally:
        pipeline._fact_validator.validate_reply = original

    assert calls["n"] == 1
    assert result.get("traceability_blocked") is True
    assert result.get("traceability_ok") is False
    assert "PKR" not in (result.get("draft_reply") or "")
    assert result.get("market_facts") is None
    assert result.get("facts_used") == []
    assert result.get("needs_human") is True
    assert result.get("needs_human_approval") is True
    assert result["decision"]["action"] == "escalate"
    assert "untraceable_number_in_draft" in result["decision"]["reasons"]


# ---------------------------------------------------------------------------
# (d) the red-team set shows 0 unsupported-claim leakage
# ---------------------------------------------------------------------------


def _load_redteam():
    rows = []
    with io.open(REDTEAM_PATH, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def test_m5_the_redteam_dataset_is_present():
    rows = _load_redteam()
    assert len(rows) >= 30


def test_m5_redteam_replies_leak_no_untraceable_number():
    """Every red-team row must produce a reply whose numbers all trace.

    A refused or escalated reply must contain no price figure at all; this
    asserts the stricter property that even if a number appeared, it would
    have to trace.
    """
    rows = _load_redteam()
    leaks = []

    for row in rows:
        result = handle_message(row["message"])
        reply = result.get("draft_reply") or ""
        facts = result.get("market_facts")
        facts = facts.get("facts") if isinstance(facts, dict) else None

        numbers = extract_numbers(reply)
        if not numbers:
            continue

        # A red-team row must never carry a price figure.
        if re.search(r"PKR\s*[\d,]+", reply):
            leaks.append((row["id"], "price in a red-team reply: %r" % reply[:90]))
            continue

        validation = validate_reply(reply, facts, context=None)
        if not validation.ok:
            leaks.append((row["id"], validation.reason))

    assert leaks == [], "red-team leakage: %r" % (leaks[:5],)


def test_m5_redteam_rows_never_expose_a_market_price():
    rows = _load_redteam()
    for row in rows:
        result = handle_message(row["message"])
        reply = result.get("draft_reply") or ""
        assert not re.search(r"PKR\s*[\d,]+", reply), (
            "row %s leaked a price: %r" % (row["id"], reply[:90])
        )


# ---------------------------------------------------------------------------
# (e) 100% price-reply traceability
# ---------------------------------------------------------------------------


def test_m5_price_reply_traceability_is_100_percent():
    """The e2e metric definition: every price reply is fully traceable."""
    total = 0
    traceable = 0
    failures = []

    for block, size_marla in ANSWERABLE:
        result = price_lookup.lookup_price(block=block, size_marla=size_marla)
        facts = result["facts"]
        reply = result["reply"]
        if not facts.get("answerable_for_demo"):
            continue
        total += 1
        validation = validate_reply(reply, facts, context={"size_marla": size_marla})
        if validation.ok:
            traceable += 1
        else:
            failures.append((block, size_marla, validation.reason))

    assert total > 0
    assert traceable == total, "traceability failures: %r" % (failures,)
    assert 100.0 * traceable / total == 100.0


def test_m5_the_twenty_question_set_is_still_fully_traceable():
    questions = price_lookup.load_questions()["questions"]
    checked = 0
    for case in questions:
        result = price_lookup.lookup_price(**case["filters"])
        facts = result.get("facts")
        reply = result.get("reply") or ""
        size = case["filters"].get("size_marla")
        validation = validate_reply(reply, facts, context={"size_marla": size})
        assert validation.ok is True, (
            "question %s (%s) produced untraceable numbers %r"
            % (case.get("id"), case.get("question"), validation.untraceable)
        )
        checked += 1

    assert checked == 20


# ---------------------------------------------------------------------------
# The validator itself: extraction and whitelist behaviour
# ---------------------------------------------------------------------------


def test_m5_extract_numbers_handles_thousands_separators_and_decimals():
    found = extract_numbers("PKR 7,900,000 to PKR 11,500,000, median 7,900,000.")
    values = [value for _raw, value in found]

    assert 7900000.0 in values
    assert 11500000.0 in values
    assert len(values) == 3


def test_m5_extract_numbers_handles_a_date_as_three_parts():
    values = [value for _raw, value in extract_numbers("Latest observation date: 2026-10-07.")]

    assert 2026.0 in values
    assert 10.0 in values
    assert 7.0 in values


def test_m5_extract_numbers_on_empty_text_is_empty():
    assert extract_numbers("") == []
    assert extract_numbers(None) == []


def test_m5_a_date_in_the_reply_traces_to_the_fact_date():
    result = price_lookup.lookup_price(block="C", size_marla=7)
    validation = validate_reply(result["reply"], result["facts"], context={"size_marla": 7})

    assert validation.ok is True
    # 2026, 10 and 07 all come from latest_date.
    assert 2026.0 in [v for _r, v in validation.numbers]


def test_m5_the_validator_never_calls_an_llm():
    """The module must be stdlib-only and LLM-free (RULES_SHORT #1, #5)."""
    source = io.open(
        os.path.join(PROJECT_ROOT, "market", "fact_validator.py"), encoding="utf-8"
    ).read()

    for forbidden in ("requests", "httpx", "urllib", "openai", "anthropic",
                      "llama", "ollama", "laya", "subprocess"):
        assert forbidden not in source.lower(), (
            "fact_validator.py references %r" % forbidden
        )


def test_m5_the_validator_does_not_modify_the_approved_master():
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
    for block, size_marla in ANSWERABLE:
        result = price_lookup.lookup_price(block=block, size_marla=size_marla)
        validate_reply(result["reply"], result["facts"], context={"size_marla": size_marla})
    assert digest() == before


# ---------------------------------------------------------------------------
# The console API exposes the traceability report
# ---------------------------------------------------------------------------


def test_m5_the_console_api_exposes_the_traceability_report():
    import app.server as server

    payload = server.handle_message_endpoint(
        "What is the price of a 7 marla plot in Block C?"
    )

    assert "traceability" in payload
    assert payload["traceability_ok"] is True
    assert payload["traceability_blocked"] is False
    assert payload["traceability"]["ok"] is True
    assert payload["traceability"]["untraceable"] == []


def test_m5_the_console_api_never_returns_raw_dealer_text():
    """The traceability report must not become a privacy leak: it carries
    numbers, never raw chat or a sender identity.

    ``sender_count_available`` is a legitimate field that states *no* sender
    count is available, so the check is for a real sender value rather than
    for the word "sender" appearing at all.
    """
    import app.server as server

    payload = server.handle_message_endpoint(
        "What is the price of a 7 marla plot in Block C?"
    )
    blob = json.dumps(payload, default=str)

    assert "raw_text" not in blob
    # No sender identity: the only sender-related field is the flag that
    # says a sender count is NOT available.
    assert "sender_count_available" in blob
    facts = (payload.get("market_facts") or {}).get("facts") or {}
    assert facts.get("sender_count_available") is False
    # The approved master carries no sender names at all.
    assert "Agent_" not in blob
    assert "Customer_" not in blob
