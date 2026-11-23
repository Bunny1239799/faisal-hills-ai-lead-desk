"""M8 - the recommendation layer: ranked VERIFIED alternatives.

M8 moves the product from "here is what the data says" to "here is what
you can actually choose", and it is the first layer that can *propose
something to a dealer*.

The properties this module proves:

  1. every recommendation is a cell the approved master actually
     covers - no invented block, no invented size;
  2. only cells that clear the **same** evidence threshold the lookup
     uses are recommended - a thin cell is reported as a gap, never
     offered as an option;
  3. the ranking is deterministic and explainable - the same request
     always produces the same order, and each option carries the reason
     it was proposed;
  4. a **parked block is refused before any row is counted** - the
     scope rule is the lookup's rule;
  5. the recommendation layer never leaks dealer content - it reads the
     whitelisted evidence rows, never the raw master rows;
  6. a recommendation never claims availability - the master is a
     partial snapshot of asking prices, not a live feed;
  7. the M6.1 claim guard permits a reply to name a verified
     alternative, and still refuses a cell the application did not
     verify;
  8. the next-best-action ladder is strict: exact match -> verified
     alternatives -> clarifying question -> human escalation, and a
     speculative option is never produced.

Run with:  python -m pytest tests/test_m8_recommend.py -q
"""

import json
import os
import sys

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from app import customer_model  # noqa: E402
from app.pipeline import handle_message  # noqa: E402
from market import price_lookup  # noqa: E402
from market import recommend  # noqa: E402
from market import reply_guard  # noqa: E402
from market.fh_query import load_inventory  # noqa: E402

# The three thin cells, measured against the approved master.
THIN = [("A", 14), ("B", 7), ("C", 10)]

# The cells that clear the 3-listing threshold.
ANSWERABLE = [
    ("A", 5), ("A", 7), ("A", 10), ("A", 20), ("A", 40),
    ("B", 5), ("B", 10), ("B", 14), ("B", 20),
    ("C", 5), ("C", 7), ("C", 20),
]


def _master_cells():
    """Every (block, size) cell the approved master holds, in scope."""
    cells = set()
    for row in load_inventory(price_lookup.MASTER_PATH
                              if hasattr(price_lookup, "MASTER_PATH")
                              else None) or []:
        block = price_lookup.canonical_block(row.get("block"))
        size = row.get("size_marla")
        if block and size is not None:
            cells.add((block, float(size)))
    return cells


# ---------------------------------------------------------------------------
# (1) every recommendation is a cell the master covers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("block,size_marla", THIN)
def test_m8_every_recommended_cell_is_covered_by_the_master(block, size_marla):
    """A recommendation may only name a cell the master holds."""
    result = recommend.build_recommendations(
        block=block, size_marla=size_marla, include_listings=False)

    for option in result["options"]:
        size = option["size_marla"]
        assert option["block"] in ("A", "B", "C"), option
        # The cell must exist in the scoped inventory.
        inventory = price_lookup._active_scope_inventory(["A", "B", "C"])
        found = any(
            price_lookup.canonical_block(row.get("block")) == option["block"]
            and abs(float(row.get("size_marla") or -1) - size) <= 0.001
            for row in inventory
        )
        assert found, ("the recommendation names a cell the master does not "
                       "hold: %s/%s" % (option["block"], size))


@pytest.mark.parametrize("block,size_marla", THIN)
def test_m8_a_recommendation_never_names_a_parked_block(block, size_marla):
    """The scope rule is the lookup's rule."""
    result = recommend.build_recommendations(
        block=block, size_marla=size_marla, include_listings=False)

    for option in result["options"]:
        assert option["block"] not in ("D", "E"), option


def test_m8_a_parked_block_is_refused_before_any_row_is_counted():
    """A parked block is a refusal, not an empty recommendation."""
    for block in ("D", "E", "Z"):
        with pytest.raises(recommend.RecommendationError):
            recommend.build_recommendations(block=block, size_marla=10)


# ---------------------------------------------------------------------------
# (2) only cells that clear the threshold are recommended
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("block,size_marla", THIN)
def test_m8_a_thin_cell_is_never_offered_as_an_option(block, size_marla):
    """The cell that failed the threshold must not be proposed."""
    result = recommend.build_recommendations(
        block=block, size_marla=size_marla, include_listings=False)

    for option in result["options"]:
        listings = int(option["summary"].get("matched_plots") or 0)
        assert listings >= 3, (
            "a cell below the evidence threshold was offered as an option: "
            "%s/%s (%s listings)"
            % (option["block"], option["size_marla"], listings)
        )


@pytest.mark.parametrize("block,size_marla", THIN)
def test_m8_the_thin_cell_is_reported_as_a_gap(block, size_marla):
    """The gap is reported honestly, with no price."""
    result = recommend.build_recommendations(
        block=block, size_marla=size_marla, include_listings=False)

    thin = [c for c in result["thin_cells"]
            if c["block"] == block
            and abs(c["size_marla"] - size_marla) <= 0.001]
    assert thin, "the thin cell was not reported as a gap"
    assert thin[0]["listing_count"] < thin[0]["min_listings_for_answer"]
    # The gap carries no price.
    blob = json.dumps(thin, default=str)
    assert "price" not in blob.lower()


def test_m8_an_option_carries_a_price_because_it_clears_the_threshold():
    """An offered alternative is priced, because it is supported."""
    result = recommend.build_recommendations(
        block="C", size_marla=10, include_listings=False)

    assert result["options"], "no alternative was produced for a thin cell"
    for option in result["options"]:
        assert option["summary"]["price_median_pkr"] is not None
        assert option["summary"]["observation_count"] > 0


# ---------------------------------------------------------------------------
# (3) the ranking is deterministic and explainable
# ---------------------------------------------------------------------------


def test_m8_the_ranking_is_deterministic():
    """The same request always produces the same order."""
    first = recommend.build_recommendations(
        block="C", size_marla=10, include_listings=False)
    second = recommend.build_recommendations(
        block="C", size_marla=10, include_listings=False)

    assert ([(o["block"], o["size_marla"]) for o in first["options"]]
            == [(o["block"], o["size_marla"]) for o in second["options"]])


def test_m8_every_option_carries_a_reason():
    """A dealer can be told WHY a cell was proposed."""
    result = recommend.build_recommendations(
        block="C", size_marla=10, include_listings=False)

    for option in result["options"]:
        assert option["reason"], option
        assert isinstance(option["reason"], list)
        # The reason names the cell and its evidence.
        assert any(str(option["size_marla"]) in r
                   or "%g" % option["size_marla"] in r
                   for r in option["reason"]), option["reason"]


def test_m8_the_nearest_size_wins_over_a_distant_one():
    """The closest alternative is offered first."""
    result = recommend.build_recommendations(
        block="C", size_marla=10, include_listings=False)

    assert result["options"]
    scores = [o["score"] for o in result["options"]]
    assert scores == sorted(scores, reverse=True), scores


def test_m8_the_score_components_are_all_reported():
    """The ranking is explainable, not a black box."""
    result = recommend.build_recommendations(
        block="C", size_marla=10, include_listings=False)

    for option in result["options"]:
        components = option["score_components"]
        assert set(components) == {
            "size_fit", "block_fit", "evidence_fit", "recency_fit"}
        for value in components.values():
            assert 0.0 <= value <= 1.0


# ---------------------------------------------------------------------------
# (4) no dealer content leaves the layer
# ---------------------------------------------------------------------------


def test_m8_no_dealer_content_reaches_a_recommendation():
    """The layer reads the whitelisted evidence rows, not the raw rows."""
    rows = load_inventory()
    notes = {str(r.get("notes") or "").strip() for r in rows}
    notes = {n for n in notes if len(n) >= 12}
    dealers = set()
    for row in rows:
        value = row.get("source_chats")
        if isinstance(value, (list, tuple, set)):
            dealers.update(str(v).strip() for v in value if str(v).strip())
        elif value:
            dealers.add(str(value).strip())
    dealers = {d for d in dealers if len(d) >= 4}

    for block, size_marla in THIN:
        result = recommend.build_recommendations(
            block=block, size_marla=size_marla, include_listings=True)
        blob = json.dumps(result, default=str)
        for note in notes:
            assert note not in blob, note
        for dealer in dealers:
            assert dealer not in blob, dealer


def test_m8_the_listings_of_an_option_are_redacted():
    """The options carry M7's redacted evidence rows."""
    result = recommend.build_recommendations(
        block="C", size_marla=10, include_listings=True)

    for option in result["options"]:
        for listing in option.get("listings") or []:
            assert listing.get("plot_number") is None
            assert listing.get("plot_number_redacted") is True
            assert "notes" not in listing
            assert "source_chats" not in listing


# ---------------------------------------------------------------------------
# (5) a recommendation never claims availability
# ---------------------------------------------------------------------------


def test_m8_a_recommendation_never_claims_availability():
    """The master is a partial snapshot, not a live feed."""
    result = recommend.build_recommendations(
        block="C", size_marla=10, include_listings=False)

    assert result["availability_claimed"] is False
    assert result["is_sold_price"] is False
    assert "asking prices" in result["price_basis"]
    assert "verified partial master" in result["evidence_source"]


# ---------------------------------------------------------------------------
# (6) the claim guard permits a verified alternative and refuses the rest
# ---------------------------------------------------------------------------


def _facts_with_alternatives(alternatives):
    return {
        "facts_source": reply_guard.APPROVED_SOURCE,
        "answerable_for_demo": False,
        "reply_mode": "insufficient_data",
        "closest_match": {"block": "C", "size_marla": 7},
        "verified_alternatives": alternatives,
    }


def test_m8_the_claim_guard_permits_a_verified_alternative():
    """The guard knows which cells the application verified."""
    facts = _facts_with_alternatives([
        {"block": "B", "size_marla": 10, "verified": True},
    ])

    report = reply_guard.guard_reply(
        "I need to confirm with our team. The closest match is a 7 marla "
        "plot in Block C. A verified alternative is a 10 marla plot in "
        "Block B. A member of our team will review it.",
        facts,
        filters={"block": "C", "size_marla": 10},
        context={"size_marla": 10},
        action="escalate",
        reply_mode="insufficient_data",
    )
    assert report.ok, report.violations


def test_m8_the_claim_guard_still_refuses_an_unverified_cell():
    """Naming a cell the application did not verify is still refused."""
    facts = _facts_with_alternatives([
        {"block": "B", "size_marla": 10, "verified": True},
    ])

    report = reply_guard.guard_reply(
        "I need to confirm with our team. A 40 marla plot in Block A is "
        "available. A member of our team will review it.",
        facts,
        filters={"block": "C", "size_marla": 10},
        context={"size_marla": 10},
        action="escalate",
        reply_mode="insufficient_data",
    )
    assert not report.ok
    assert any(v["code"] == "unsupported_pair" for v in report.violations)


def test_m8_an_unverified_entry_in_the_fact_set_is_not_trusted():
    """Only an entry the application marked verified is permitted."""
    facts = _facts_with_alternatives([
        {"block": "A", "size_marla": 40},          # no verified marker
    ])

    report = reply_guard.guard_reply(
        "I need to confirm with our team. A 40 marla plot in Block A is "
        "available. A member of our team will review it.",
        facts,
        filters={"block": "C", "size_marla": 10},
        context={"size_marla": 10},
        action="escalate",
        reply_mode="insufficient_data",
    )
    assert not report.ok
    assert any(v["code"] == "unsupported_pair" for v in report.violations)


def test_m8_the_guard_does_not_cross_alternatives_into_phantom_pairs():
    """A list of alternatives is judged one option at a time.

    "a 14 marla plot in Block B, a 7 marla plot in Block A" claims
    (B, 14) and (A, 7). It does NOT claim (B, 7), so a reply that names
    only verified alternatives must not be blocked for a pair it never
    made.
    """
    facts = _facts_with_alternatives([
        {"block": "B", "size_marla": 14, "verified": True},
        {"block": "A", "size_marla": 7, "verified": True},
    ])

    report = reply_guard.guard_reply(
        "I need to confirm with our team. The verified alternatives are a "
        "14 marla plot in Block B and a 7 marla plot in Block A. A member "
        "of our team will review it.",
        facts,
        filters={"block": "C", "size_marla": 10},
        context={"size_marla": 10},
        action="escalate",
        reply_mode="insufficient_data",
    )
    assert report.ok, report.violations


def test_m8_the_guard_still_catches_a_phantom_pair_in_a_list():
    """The clause split must not weaken the check.

    A reply that names "a 10 marla plot in Block B and a 40 marla plot
    in Block A" claims (B, 10) and (A, 40). Only the first is
    verified, so the reply must be refused.
    """
    facts = _facts_with_alternatives([
        {"block": "B", "size_marla": 10, "verified": True},
    ])

    report = reply_guard.guard_reply(
        "I need to confirm with our team. The verified alternatives are a "
        "10 marla plot in Block B and a 40 marla plot in Block A. A member "
        "of our team will review it.",
        facts,
        filters={"block": "C", "size_marla": 10},
        context={"size_marla": 10},
        action="escalate",
        reply_mode="insufficient_data",
    )
    assert not report.ok
    assert any(v["code"] == "unsupported_pair" for v in report.violations)


# ---------------------------------------------------------------------------
# (7) the customer-facing path
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("block,size_marla", THIN)
def test_m8_the_customer_reply_names_the_verified_alternatives(
        block, size_marla):
    """The dealer is pointed at real cells, and the reply still validates."""
    result = handle_message(
        "What is the price of a %s marla plot in Block %s?"
        % (size_marla, block)
    )
    reply = result.get("draft_reply") or ""

    # The reply passes both final gates.
    assert result.get("traceability_ok") is True, result.get("traceability")
    assert result.get("claim_guard_ok") is True, result.get("claim_guard")

    # It names at least one alternative, and it keeps the hand-off.
    assert "verified alternative" in reply.lower() or "closest match" in reply.lower()
    assert "our team" in reply.lower()

    # And it carries no price - the requested cell is below threshold.
    assert "PKR" not in reply


def test_m8_the_customer_reply_for_an_answerable_cell_has_no_alternatives():
    """An exact match needs no alternatives - the dealer gets the price."""
    result = handle_message(
        "What is the price of a 7 marla plot in Block C?")
    reply = result.get("draft_reply") or ""

    assert result.get("verified_alternatives") == []
    assert "verified alternative" not in reply.lower()
    assert "PKR" in reply


def test_m8_the_alternatives_reach_the_reply_only_through_the_fact_set():
    """The port may word an alternative; it may never create one."""
    facts = {
        "facts_source": reply_guard.APPROVED_SOURCE,
        "answerable_for_demo": False,
        "reply_mode": "insufficient_data",
        "closest_match": {"block": "C", "size_marla": 7},
        "verified_alternatives": [
            {"block": "B", "size_marla": 10, "verified": True},
        ],
    }
    view = customer_model.build_model_facts(facts)
    assert view["verified_alternatives"] == [
        {"block": "B", "size_marla": 10}
    ]

    # An unverified entry never reaches the port.
    facts["verified_alternatives"] = [{"block": "A", "size_marla": 40}]
    view = customer_model.build_model_facts(facts)
    assert view["verified_alternatives"] == []


# ---------------------------------------------------------------------------
# (8) the next-best-action ladder
# ---------------------------------------------------------------------------


def test_m8_the_ladder_starts_at_the_exact_match():
    """An answerable request quotes the cell, not an alternative."""
    result = recommend.build_recommendations(
        block="C", size_marla=7, include_listings=False)

    assert result["answerable"] is True
    assert result["exact_match"] is not None
    assert result["next_best_action"]["action"] == "quote_exact_match"


def test_m8_the_ladder_offers_verified_alternatives_for_a_thin_cell():
    """A thin cell leads to a verified alternative, not a dead end."""
    result = recommend.build_recommendations(
        block="C", size_marla=10, include_listings=False)

    assert result["answerable"] is False
    assert result["next_best_action"]["action"] == "offer_verified_alternatives"
    assert result["next_best_action"]["requires_human_approval"] is True


def test_m8_the_ladder_asks_a_question_when_nothing_clears_the_threshold():
    """When there is no option, the action is a question, not a guess."""
    policies = dict(price_lookup.load_policies())
    # Raise the threshold so that no cell can clear it.
    policies["min_listings_for_answer"] = 10000

    result = recommend.build_recommendations(
        block="C", size_marla=10, include_listings=False, policies=policies)

    assert result["options"] == []
    assert result["next_best_action"]["action"] == "ask_clarifying_question"
    assert result["next_best_action"]["requires_human_approval"] is True


def test_m8_every_next_best_action_requires_human_approval():
    """The human hand-off is never dropped."""
    for block, size_marla in THIN + ANSWERABLE:
        result = recommend.build_recommendations(
            block=block, size_marla=size_marla, include_listings=False)
        assert result["next_best_action"]["requires_human_approval"] is True
