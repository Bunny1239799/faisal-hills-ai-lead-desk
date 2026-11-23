"""M4 focused tests: the property lookup, the policy configuration and the
hand-checked question set.

These are the M4 acceptance checks from FH-02 section 6:

  (a) price_lookup returns count/min/median/max/date/coverage for a
      block+size filter;
  (b) a thin-data or out-of-scope question never produces a price - it
      takes the "not enough data" / human path with no number;
  (c) the hand-checked question set matches the approved master;
  (d) the approved master is read-only and byte-identical afterwards.

Run with:  python -m pytest tests/test_m4_price_lookup.py -q
"""

import hashlib
import json
import re
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from market import price_lookup
from market.fh_query import MASTER_PATH


APPROVED_MASTER = Path(r"D:\AI-Projects\real-estate-agent\approved_data\master_inventory.jsonl")
PRIMARY_MASTER = Path(r"D:\FaisalHills_Master_Data\07_MASTER\master_inventory.jsonl")


def _has_price_figure(text):
    """True when the text contains a number that looks like a price."""
    for number in re.findall(r"\d+", text or ""):
        if int(number) >= 1000:
            return True
    return False


# --- (a) the lookup returns the full fact set -------------------------

def test_lookup_returns_count_min_median_max_date_and_coverage():
    result = price_lookup.lookup_price(block="C", size_marla=7)

    assert result["answerable"] is True

    facts = result["facts"]
    assert facts["matched_plots"] == 21
    assert facts["observation_count"] == 43
    assert facts["price_min_pkr"] == 6000000
    assert facts["price_median_pkr"] == 7900000
    assert facts["price_max_pkr"] == 11500000
    assert facts["latest_date"] is not None
    assert facts["coverage_level"] == "partial"
    assert facts["trust_status"] == "partial_dataset"

    # The summary and the facts agree.
    assert result["summary"]["matched_plots"] == facts["matched_plots"]
    assert result["summary"]["price_median_pkr"] == facts["price_median_pkr"]


def test_lookup_reports_asking_price_not_sold_price():
    facts = price_lookup.lookup_price(block="A", size_marla=5)["facts"]

    assert facts["price_basis"] == "dealer_asking_price"
    assert facts["is_sold_price"] is False
    assert "asking prices" in (
        price_lookup.lookup_price(block="A", size_marla=5)["reply"]
    )


def test_lookup_never_claims_sender_information():
    facts = price_lookup.lookup_price(block="C", size_marla=5)["facts"]

    assert facts["sender_count_available"] is False
    assert "sender" not in facts
    assert "raw_text" not in facts


def test_lookup_never_calls_an_llm():
    """The lookup module must not import or reference any model client."""
    source = (PROJECT_ROOT / "market" / "price_lookup.py").read_text(encoding="utf-8")

    for forbidden in ("ollama", "openai", "anthropic", "gemini", "llama", "requests.post"):
        assert forbidden not in source.lower(), forbidden


# --- (b) thin data and out-of-scope never produce a price -------------

def test_thin_data_returns_no_price_in_the_reply():
    result = price_lookup.lookup_price(block="B", size_marla=7)

    assert result["answerable"] is False
    assert result["reply_mode"] == "insufficient_data"
    assert result["human_action"] == "confirm_with_team"
    assert "at least 3" in result["reason"]
    assert not _has_price_figure(result["reply"])


@pytest.mark.parametrize("block", ["D", "E", "Z", "X", "Y", "Executive", "FHD", "FHE"])
def test_out_of_scope_block_never_returns_a_price(block):
    result = price_lookup.lookup_price(block=block, size_marla=5)

    assert result["answerable"] is False
    assert result["reply_mode"] == "out_of_scope"
    assert result["facts"] is None
    assert result["summary"]["matched_plots"] == 0
    assert not _has_price_figure(result["reply"])


def test_block_less_question_is_restricted_to_the_active_scope():
    """A question naming no block must not be answered from a parked block."""
    result = price_lookup.lookup_price(size_marla=5)

    # Active scope only: A(21) + B(29) + C(47) = 97. Executive(5) and
    # other(8) must not be counted.
    assert result["facts"]["matched_plots"] == 97
    assert result["answerable"] is True


def test_no_filters_returns_no_lookup():
    result = price_lookup.lookup_price()

    assert result["answerable"] is False
    assert result["reply_mode"] == "no_lookup"
    assert result["facts"] is None
    assert not _has_price_figure(result["reply"])


# --- (c) the hand-checked question set --------------------------------

def test_question_set_has_twenty_questions():
    config = price_lookup.load_questions()
    assert len(config["questions"]) == 20


def test_question_set_matches_the_approved_master():
    report = price_lookup.check_questions()

    assert report["failed"] == 0, report["failures"]
    assert report["passed"] == 20


def test_must_not_answer_cases_have_no_price_in_the_reply():
    config = price_lookup.load_questions()
    must_not = [q for q in config["questions"] if q.get("must_not_answer")]

    assert len(must_not) >= 5

    for question in must_not:
        filters = question["filters"]
        result = price_lookup.lookup_price(
            block=filters.get("block"),
            size_marla=filters.get("size_marla"),
            corner=filters.get("corner"),
            sun_facing=filters.get("sun_facing"),
            ndc_open=filters.get("ndc_open"),
        )
        assert result["answerable"] is False, question["question"]
        assert not _has_price_figure(result["reply"]), question["question"]


def test_must_answer_cases_have_a_price_and_a_median():
    config = price_lookup.load_questions()
    must_answer = [q for q in config["questions"] if q.get("must_answer")]

    assert len(must_answer) >= 10

    for question in must_answer:
        filters = question["filters"]
        result = price_lookup.lookup_price(
            block=filters.get("block"),
            size_marla=filters.get("size_marla"),
            corner=filters.get("corner"),
            sun_facing=filters.get("sun_facing"),
            ndc_open=filters.get("ndc_open"),
        )
        assert result["answerable"] is True, question["question"]
        assert result["facts"]["price_median_pkr"] is not None, question["question"]


# --- the policy configuration -----------------------------------------

def test_policies_config_is_read_and_drives_the_lookup():
    policies = price_lookup.load_policies()

    assert policies["active_blocks"] == ["A", "B", "C"]
    assert policies["min_listings_for_answer"] == 3
    assert policies["price_policy"]["is_sold_price"] is False
    assert policies["price_policy"]["show_sample_size"] is True
    assert policies["privacy_policy"]["allow_sender_names"] is False
    assert policies["privacy_policy"]["allow_phone_numbers"] is False
    assert policies["lookup_policy"]["llm_calculates_prices"] is False
    assert policies["lookup_policy"]["llm_invents_prices"] is False


def test_threshold_in_policy_config_is_honoured():
    policies = price_lookup.load_policies()
    strict = dict(policies)
    strict["min_listings_for_answer"] = 50

    result = price_lookup.lookup_price(block="C", size_marla=7, policies=strict)

    assert result["answerable"] is False
    assert "at least 50" in result["reason"]


def test_active_blocks_in_policy_config_are_honoured():
    policies = price_lookup.load_policies()
    narrow = dict(policies)
    narrow["active_blocks"] = ["C"]

    result = price_lookup.lookup_price(block="A", size_marla=5, policies=narrow)

    assert result["answerable"] is False
    assert result["reply_mode"] == "out_of_scope"


# --- (d) the master is read-only and unchanged ------------------------

def test_approved_master_is_not_modified_by_a_lookup():
    before = hashlib.sha256(APPROVED_MASTER.read_bytes()).hexdigest()

    price_lookup.lookup_price(block="C", size_marla=7)
    price_lookup.lookup_price(block="A", size_marla=5)
    price_lookup.check_questions()

    after = hashlib.sha256(APPROVED_MASTER.read_bytes()).hexdigest()

    assert after == before
    assert after == "b77b3cb574cc4e08b018fa4bd5a993b16925ca700bbd48231bd825ef8af5a17d"


def test_approved_master_copies_are_byte_identical():
    assert APPROVED_MASTER.read_bytes() == PRIMARY_MASTER.read_bytes()


def test_lookup_uses_the_approved_master_path():
    """The lookup must use the master it was configured with.

    The master may be relocated for testing through the optional
    `FH_MASTER_PATH` environment variable, and CI relocates it that way.
    Asserting the owner's absolute path would therefore fail on every
    machine except this one, so the CONTRACT is asserted instead: the
    lookup reads the master it was pointed at, and that master is the
    approved 374-plot inventory.
    """
    from market.fh_query import load_inventory

    assert Path(price_lookup.MASTER_PATH).is_file(), (
        "the configured master must exist: %s" % price_lookup.MASTER_PATH)

    rows = load_inventory(price_lookup.MASTER_PATH)

    assert len(rows) == 374
    assert all("raw_text" not in row for row in rows)
    assert all("sender" not in row for row in rows)
