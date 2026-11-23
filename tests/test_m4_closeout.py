"""M4 focused tests #2: the defects found while verifying M4.

Every test in this module was written to FAIL against the code as it
stood before the M4 closeout fixes, and to PASS after them. They are
regression tests, not new features.

Defects covered:

  F-1  the customer-facing path raised
       "TypeError: 'NoneType' object is not subscriptable" when the lookup
       declined to run (reply_mode "no_lookup"), e.g.
       "What is the price in Block C?"
  F-2  the extracted entities were never returned by the base pipeline, so
       the market layer lost every filter it could not re-derive from the
       raw text (for example "1 kanal" -> 20 marla)
  F-3  the entity extractor's boolean DEFAULT (is_corner=False) was
       applied as a real "exclude corner" filter. The approved master
       stores `corner` as null (340/374) or True - never False - so
       `corner=False` matched 0 rows and every ordinary price question
       became unanswerable
  F-4  the v1 scope was hard-coded in three places, so changing
       `config/policies.json` did not change what the customer-facing path
       did
  F-6  the configured block codes were not canonicalised the same way as
       the requested block, so "EXECUTIVE" in the config never matched
       "Executive" in a question
  F-10 the policy gate cached the scope, so a relocated/stale scope kept
       being enforced
  F-11 an M4 test hard-coded the owner's absolute master path, so the
       suite failed on CI and on every other machine
  F-14 `python -m market.price_lookup --block C --size-marla 7` ignored
       its arguments and printed the 20-question report instead

Run with:  python -m pytest tests/test_m4_closeout.py -q
"""

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.pipeline import handle_message
from market import price_lookup


def _has_price_figure(text):
    for number in re.findall(r"\d+", text or ""):
        if int(number) >= 1000:
            return True
    return False


# --- F-1: a lookup that declines to run must not crash ------------------

@pytest.mark.parametrize(
    "message",
    [
        "What is the price in Block C?",
        "What is the price of a plot?",
        "What is the price of a 999 marla plot in Block C?",
    ],
)
def test_no_lookup_reply_does_not_crash(message):
    """A question the lookup cannot answer must still get a reply, not a 500.

    The contract is deliberately narrow: the customer gets a reply, the
    reply carries no price figure, and no facts are attached. Whether the
    lookup declined ("no_lookup") or ran and found too little data
    ("insufficient_data") is an internal distinction - both must reach the
    customer as a reply with no number.
    """
    result = handle_message(message)

    assert "draft_reply" in result
    assert result["draft_reply"]
    # The reply must never carry a price figure.
    assert not _has_price_figure(result["draft_reply"])
    # And it must not claim one either.
    assert "PKR" not in result["draft_reply"]


def test_kanal_question_is_answered_not_crashed():
    """'1 kanal' is 20 marla (DEC-10). With the F-2 fix the extracted size
    reaches the lookup, so the question is answered with a real price
    rather than crashing on a missing filter.
    """
    result = handle_message("What is the price of a 1 kanal plot in Block C?")

    assert result.get("market_answerable") is True
    assert result["facts_used"][0]["matched_plots"] == 4
    assert _has_price_figure(result["draft_reply"])


def test_block_without_a_size_is_not_a_crash():
    """'What is the price in Block C?' names a block but no size. The
    lookup declines to run (no_lookup) and the customer still gets a
    reply with no price.
    """
    result = handle_message("What is the price in Block C?")

    assert result.get("market_facts") is not None
    assert result.get("market_answerable") is False
    assert result["facts_used"] == []
    assert result["n"] == 0
    assert result["level"] == "insufficient"
    assert not _has_price_figure(result["draft_reply"])


# --- F-2: an extracted size filter must survive --------------------------

def test_kanal_size_filter_is_not_lost():
    """'1 kanal' is 20 marla (DEC-10) and must reach the lookup."""
    result = handle_message("What is the price of a 1 kanal plot in Block C?")

    assert result.get("market_answerable") is True

    facts = result["facts_used"][0]
    assert facts["matched_plots"] == 4
    assert facts["price_median_pkr"] == 16500000


# --- F-3: a boolean DEFAULT is not a filter ------------------------------

def test_plain_price_question_is_not_filtered_by_the_extractor_default():
    """The extractor's is_corner=False must not become an 'exclude corner'
    filter. The master stores corner as null/True, never False, so that
    filter matched nothing and made every ordinary question unanswerable.
    """
    result = handle_message("What is the price of a 7 marla plot in Block C?")

    assert result.get("market_answerable") is True

    facts = result["facts_used"][0]
    assert facts["matched_plots"] == 21
    assert facts["observation_count"] == 43
    assert facts["price_median_pkr"] == 7900000


def test_explicit_corner_question_is_still_filtered():
    """A question that DOES ask for a corner plot must still be filtered."""
    result = handle_message("What is the price of a 7 marla corner plot in Block C?")

    assert result.get("market_answerable") is True

    facts = result["facts_used"][0]
    assert facts["matched_plots"] == 3
    assert facts["price_median_pkr"] == 9600000


# --- F-4 / F-6 / F-10: one authority for the scope ----------------------

def _relocate_config(tmp_path, active_blocks):
    """Copy config/ to a temp dir with a different active scope."""
    import shutil

    target = tmp_path / "config"
    shutil.copytree(PROJECT_ROOT / "config", target)

    policies_path = target / "policies.json"
    policies = json.loads(policies_path.read_text(encoding="utf-8"))
    policies["active_blocks"] = list(active_blocks)
    policies_path.write_text(json.dumps(policies, indent=2), encoding="utf-8")

    return policies_path


def test_configured_scope_is_the_single_authority(tmp_path, monkeypatch):
    """Changing config/policies.json must change what the customer-facing
    path does. Before the fix the scope was hard-coded in three places and
    the configuration was misleading.
    """
    from app import policy as policy_module

    policies_path = _relocate_config(tmp_path, ["A", "B", "C", "EXECUTIVE"])

    monkeypatch.setattr(price_lookup, "POLICIES_PATH", policies_path)
    monkeypatch.setattr(
        price_lookup, "QUESTIONS_PATH", policies_path.parent / "questions.json"
    )

    # The configured block is now in scope for the lookup...
    lookup = price_lookup.lookup_price(block="Executive", size_marla=5)
    assert lookup["answerable"] is True

    # ...for the policy gate...
    decision = policy_module.evaluate_policy(
        "What is the price of a 5 marla plot in the Executive Block?"
    )
    assert decision.action == "answer", decision.reasons

    # ...and for the customer-facing path end to end.
    result = handle_message("What is the price of a 5 marla plot in the Executive Block?")
    assert result.get("market_answerable") is True
    assert _has_price_figure(result["draft_reply"])


def test_default_scope_is_unchanged_when_config_is_not_relocated():
    """The shipped configuration must still scope the product to A, B, C."""
    from app import policy as policy_module

    assert price_lookup.load_policies()["active_blocks"] == ["A", "B", "C"]
    assert policy_module._load_active_block_codes() == {"A", "B", "C"}

    for block in ("D", "E", "Z", "X", "Y", "Executive"):
        decision = policy_module.evaluate_policy(
            "What is the price of a 7 marla plot in Block %s?" % block
        )
        assert decision.needs_human is True, block
        assert "out_of_scope" in decision.risk_tags, block


def test_policy_scope_is_not_cached(tmp_path, monkeypatch):
    """The gate must not keep enforcing a scope it read before the
    configuration was relocated.
    """
    from app import policy as policy_module

    policies_path = _relocate_config(tmp_path, ["A", "B", "C", "EXECUTIVE"])

    monkeypatch.setattr(price_lookup, "POLICIES_PATH", policies_path)
    monkeypatch.setattr(
        price_lookup, "QUESTIONS_PATH", policies_path.parent / "questions.json"
    )

    codes = policy_module._load_active_block_codes()
    assert "E" in codes, codes


# --- F-18 / D-02: no public function may bypass the scope ---------------

@pytest.mark.parametrize("block", ["D", "E", "Z", "X", "Y", "Executive", "FHE"])
def test_the_adapter_does_not_price_a_parked_block(block):
    """D-02: `get_verified_market_facts()` used to call the query engine
    directly, and the engine knows nothing about the v1 scope. It therefore
    priced a PARKED block - "Block E / 5 marla" came back with 5 plots and
    a median of PKR 8,850,000. No customer could reach it, but any future
    consumer of this public function would have inherited the hole.
    """
    from app.market_adapter import get_verified_market_facts

    facts = get_verified_market_facts(block=block, size_marla=5)["facts"]

    assert facts["matched_plots"] == 0
    assert facts["price_median_pkr"] is None
    assert facts["answerable_for_demo"] is False


def test_the_adapter_still_answers_an_in_scope_block():
    """The scope restriction must not have broken the adapter."""
    from app.market_adapter import get_verified_market_facts

    facts = get_verified_market_facts(block="C", size_marla=7)["facts"]

    assert facts["matched_plots"] == 21
    assert facts["price_median_pkr"] == 7900000


def test_the_adapter_excludes_parked_blocks_from_a_blockless_query():
    """A block-less adapter query must not include the parked blocks."""
    from app.market_adapter import get_verified_market_facts

    facts = get_verified_market_facts(size_marla=5)["facts"]

    # Active scope only: A(21) + B(29) + C(47) = 97.
    assert facts["matched_plots"] == 97


# --- F-11: the suite must not depend on the owner's absolute paths -------

def test_m4_tests_do_not_hardcode_the_owner_master_path():
    """A test that asserts the owner's absolute master path fails on CI and
    on every other machine, because CI relocates the master through
    FH_MASTER_PATH.
    """
    source = (PROJECT_ROOT / "tests" / "test_m4_price_lookup.py").read_text(
        encoding="utf-8"
    )

    offending = [
        line for line in source.splitlines()
        if "APPROVED_MASTER ==" in line and "D:" in line
    ]
    assert not offending, offending


def test_lookup_uses_the_master_it_was_configured_with():
    from market.fh_query import load_inventory

    assert Path(price_lookup.MASTER_PATH).is_file()
    assert len(load_inventory(price_lookup.MASTER_PATH)) == 374


# --- F-14: the module CLI must honour its arguments ---------------------

def test_module_cli_honours_block_and_size():
    """`python -m market.price_lookup --block C --size-marla 7` must do the
    lookup, not print the 20-question report.
    """
    proc = subprocess.run(
        [
            sys.executable, "-m", "market.price_lookup",
            "--block", "C", "--size-marla", "7",
        ],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
    )

    assert proc.returncode == 0, proc.stderr
    assert "matched_plots=21" in proc.stdout
    assert "price_median_pkr=7900000.0" in proc.stdout
    assert "QUESTIONS=" not in proc.stdout


def test_module_cli_check_questions_still_works():
    proc = subprocess.run(
        [sys.executable, "-m", "market.price_lookup", "--check-questions"],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
    )

    assert proc.returncode == 0, proc.stderr
    assert "QUESTIONS=20" in proc.stdout
    assert "FAILED=0" in proc.stdout


def test_module_cli_json_output_is_valid_json():
    proc = subprocess.run(
        [
            sys.executable, "-m", "market.price_lookup",
            "--block", "C", "--size-marla", "7", "--json",
        ],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
    )

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["answerable"] is True
    assert payload["summary"]["price_median_pkr"] == 7900000


# --- the wrapper at the handoff's path must agree with the module -------

def test_handoff_wrapper_agrees_with_the_module():
    """The thin wrapper and the implementation must not drift."""
    wrapper = Path(
        r"D:\AI-Projects\real-estate-agent\scripts\price_lookup.py"
    )
    if not wrapper.is_file():
        pytest.skip("the handoff's wrapper is not present on this machine")

    proc = subprocess.run(
        [
            sys.executable, str(wrapper),
            "--block", "C", "--size-marla", "7", "--json",
        ],
        capture_output=True,
        text=True,
    )

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["summary"]["price_median_pkr"] == 7900000


# --- the approved master is still read-only -----------------------------

def test_approved_master_is_unchanged_by_the_closeout_tests():
    master = Path(
        r"D:\AI-Projects\real-estate-agent\approved_data\master_inventory.jsonl"
    )
    if not master.is_file():
        pytest.skip("the approved master is not present on this machine")

    before = hashlib.sha256(master.read_bytes()).hexdigest()

    handle_message("What is the price of a 7 marla plot in Block C?")
    handle_message("What is the price in Block C?")
    price_lookup.check_questions()

    after = hashlib.sha256(master.read_bytes()).hexdigest()
    assert after == before
