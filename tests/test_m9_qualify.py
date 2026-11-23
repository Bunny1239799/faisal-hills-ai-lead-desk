"""M9 - qualification and the next-best-action layer.

The milestone under test:

  * the dealer's stated requirements are EXTRACTED from their own words
    and are never guessed;
  * they are MERGED across the messages of one conversation, and never
    leak between conversations;
  * a model-proposed requirement is VALIDATED before it can influence
    anything, and can only ever be confirmed, never corrected;
  * qualification NARROWS the M8 verified option set and can never
    widen it;
  * the DECISION walks the ladder - exact match, verified alternatives,
    clarifying question, human escalation - and the policy always wins;
  * the reply that carries the decision still passes the M5 numeric
    validator and the M6.1 claim guard;
  * the M7 privacy boundary and the M5/M6.1/M7/M8 behaviour are intact.

The tests use the REAL approved master (the owner's data) so the
narrowing is measured against real prices, and FABRICATED dealer text
so no real chat is ever used (RULES_SHORT #6).
"""

from __future__ import annotations

import sqlite3

import pytest

from market import conversation as _conversation
from market import decision as _decision
from market import qualify as _qualify
from market import recommend as _recommend


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _rec(block="C", size=7, **kwargs):
    """The M8 recommendation for a request, with no listings."""
    return _recommend.build_recommendations(
        block=block, size_marla=size, include_listings=False, **kwargs)


def _cells(options):
    return sorted((o["block"], o["size_marla"]) for o in options)


def _reqs(**kwargs):
    base = {
        "budget_min_pkr": None,
        "budget_max_pkr": None,
        "purpose": None,
        "block": None,
        "size_marla": None,
        "timeline": None,
        "source": "none",
    }
    base.update(kwargs)
    return base


# ===========================================================================
# 1. The requirements the dealer actually stated
# ===========================================================================


class TestM9RequirementExtraction:
    """What the dealer said is what the application records."""

    def test_a_budget_in_lakh_is_read_as_pkr(self):
        out = _qualify.extract_requirements("my budget is 60 lakh")
        assert out["budget_min_pkr"] == 6_000_000.0
        assert out["budget_max_pkr"] == 6_000_000.0

    def test_a_budget_in_crore_is_read_as_pkr(self):
        out = _qualify.extract_requirements("I can do 1.2 crore")
        assert out["budget_max_pkr"] == 12_000_000.0

    def test_a_budget_range_yields_both_bounds(self):
        out = _qualify.extract_requirements("between 50 and 60 lakh")
        assert out["budget_min_pkr"] == 5_000_000.0
        assert out["budget_max_pkr"] == 6_000_000.0

    def test_a_ceiling_is_a_ceiling_not_an_exact_budget(self):
        out = _qualify.extract_requirements("up to 8 million")
        assert out["budget_max_pkr"] == 8_000_000.0
        assert out["budget_min_pkr"] is None

    def test_a_floor_is_a_floor(self):
        out = _qualify.extract_requirements("at least 12 million")
        assert out["budget_min_pkr"] == 12_000_000.0
        assert out["budget_max_pkr"] is None

    def test_a_size_is_read_in_marla(self):
        out = _qualify.extract_requirements("I need a 7 marla plot")
        assert out["size_marla"] == 7.0

    def test_a_kanal_is_read_as_twenty_marla(self):
        out = _qualify.extract_requirements("I want 1 kanal in Block B")
        assert out["size_marla"] == 20.0
        assert out["block"] == "B"

    def test_a_block_is_canonicalised_through_the_lookup_alias_table(self):
        for text, expected in (
            ("5 marla in Block C", "C"),
            ("5 marla in block c", "C"),
            ("FHC 5 marla", "C"),
            ("I prefer Executive block", "E"),
            ("EXEC block", "E"),
        ):
            assert _qualify.extract_requirements(text)["block"] == expected, text

    def test_a_purpose_is_read(self):
        assert _qualify.extract_requirements(
            "for investment")["purpose"] == "investment"
        assert _qualify.extract_requirements(
            "for personal use")["purpose"] == "personal_use"

    def test_a_timeline_is_read(self):
        assert _qualify.extract_requirements(
            "I need it within three months")["timeline"] == "three_months"

    def test_nothing_stated_means_nothing_guessed(self):
        out = _qualify.extract_requirements("just looking around")
        assert out["budget_min_pkr"] is None
        assert out["budget_max_pkr"] is None
        assert out["purpose"] is None
        assert out["block"] is None
        assert out["size_marla"] is None
        assert out["timeline"] is None
        assert out["source"] == "none"

    def test_an_empty_message_states_nothing(self):
        out = _qualify.extract_requirements("")
        assert out["source"] == "none"

    def test_a_size_is_never_read_as_a_budget(self):
        # A "marla" is not a money unit.
        out = _qualify.extract_requirements("cheapest 10 marla available")
        assert out["size_marla"] == 10.0
        assert out["budget_min_pkr"] is None
        assert out["budget_max_pkr"] is None

    def test_a_money_unit_alone_is_a_budget(self):
        # D-50: "60 lakh" states a budget even without the word
        # "budget" in the sentence.
        out = _qualify.extract_requirements("60 lakh please")
        assert out["budget_max_pkr"] == 6_000_000.0

    def test_the_ambiguous_m_is_a_million_only_in_a_money_sentence(self):
        # D-51: "5 m budget" is five million; "5 m plot" is five marla.
        money = _qualify.extract_requirements("budget 5 m")
        assert money["budget_max_pkr"] == 5_000_000.0
        assert money["size_marla"] is None

        size = _qualify.extract_requirements("5 m plot in Block C")
        assert size["size_marla"] == 5.0
        assert size["budget_max_pkr"] is None

    def test_an_implausible_budget_is_dropped_not_guessed(self):
        # D-53: "6 PKR" is a misparse, not a budget.
        out = _qualify.extract_requirements("m budget 6")
        assert out["budget_min_pkr"] is None
        assert out["budget_max_pkr"] is None


# ===========================================================================
# 2. Requirements across messages
# ===========================================================================


class TestM9RequirementMerging:
    """A requirement may arrive over several turns."""

    def test_a_later_statement_wins(self):
        merged = _qualify.merge_requirements(
            _reqs(size_marla=7.0),
            _reqs(size_marla=10.0),
        )
        assert merged["size_marla"] == 10.0

    def test_an_unrestated_requirement_is_kept(self):
        merged = _qualify.merge_requirements(
            _reqs(size_marla=7.0, block="C"),
            _reqs(budget_max_pkr=6_000_000.0),
        )
        assert merged["size_marla"] == 7.0
        assert merged["block"] == "C"
        assert merged["budget_max_pkr"] == 6_000_000.0

    def test_a_new_budget_replaces_the_old_budget_as_a_whole(self):
        # "60 lakh" then "up to 80 lakh" is ONE budget: up to 80.
        merged = _qualify.merge_requirements(
            _reqs(budget_min_pkr=6_000_000.0, budget_max_pkr=6_000_000.0),
            _reqs(budget_max_pkr=8_000_000.0),
        )
        assert merged["budget_min_pkr"] is None
        assert merged["budget_max_pkr"] == 8_000_000.0

    def test_requirements_spread_over_messages_are_merged(self):
        merged = _conversation.requirements_from_messages([
            "I need a plot in Block C",
            "around 10 marla",
            "budget is 60 lakh",
        ])
        assert merged["block"] == "C"
        assert merged["size_marla"] == 10.0
        assert merged["budget_max_pkr"] == 6_000_000.0
        assert merged["source"] == "stated"

    def test_nothing_stated_over_several_messages_stays_unknown(self):
        merged = _conversation.requirements_from_messages([
            "hello", "how are you", "just browsing",
        ])
        assert merged["source"] == "none"
        assert merged["budget_max_pkr"] is None

    def test_the_conversation_state_is_read_from_the_leads_own_messages(self):
        conn = sqlite3.connect(":memory:")
        conn.execute(
            "CREATE TABLE messages (id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "lead_id TEXT, message_text TEXT, message_timestamp TEXT)"
        )
        conn.execute("INSERT INTO messages (lead_id, message_text) VALUES (?, ?)",
                     ("lead-1", "I need a plot in Block C"))
        conn.execute("INSERT INTO messages (lead_id, message_text) VALUES (?, ?)",
                     ("lead-1", "around 10 marla"))
        conn.execute("INSERT INTO messages (lead_id, message_text) VALUES (?, ?)",
                     ("lead-2", "budget is 60 lakh"))
        conn.commit()

        lead_one = _conversation.conversation_requirements("lead-1", conn=conn)
        assert lead_one["block"] == "C"
        assert lead_one["size_marla"] == 10.0
        # The other lead's message must NOT leak into this one.
        assert lead_one["budget_max_pkr"] is None

        lead_two = _conversation.conversation_requirements("lead-2", conn=conn)
        assert lead_two["budget_max_pkr"] == 6_000_000.0
        assert lead_two["block"] is None
        conn.close()

    def test_an_unknown_lead_has_no_requirements(self):
        conn = sqlite3.connect(":memory:")
        conn.execute(
            "CREATE TABLE messages (id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "lead_id TEXT, message_text TEXT, message_timestamp TEXT)"
        )
        conn.commit()
        out = _conversation.conversation_requirements("nobody", conn=conn)
        assert out["source"] == "none"
        conn.close()

    def test_an_unreadable_database_means_no_requirements(self):
        # Fail-closed: an unknown state is never a guessed state.
        conn = sqlite3.connect(":memory:")
        out = _conversation.conversation_requirements("lead-1", conn=conn)
        assert out["source"] == "none"
        conn.close()


# ===========================================================================
# 3. A model may not become the authority
# ===========================================================================


class TestM9ModelRequirementGate:
    """A model-generated requirement is validated before it is used."""

    def test_a_model_cannot_invent_a_budget(self):
        out = _qualify.validate_requirement(
            {"budget_max_pkr": 9_000_000.0, "source": "model"},
            "5 marla in Block A",
        )
        assert out == {}

    def test_a_model_may_confirm_a_budget_the_dealer_stated(self):
        out = _qualify.validate_requirement(
            {"budget_max_pkr": 6_000_000.0, "source": "model"},
            "my budget is 60 lakh",
        )
        assert out["budget_max_pkr"] == 6_000_000.0

    def test_a_model_may_confirm_a_kanal_as_marla(self):
        out = _qualify.validate_requirement(
            {"size_marla": 20.0, "source": "model"},
            "I want 1 kanal in Block B",
        )
        assert out["size_marla"] == 20.0

    def test_a_model_cannot_invent_a_size(self):
        out = _qualify.validate_requirement(
            {"size_marla": 10.0, "source": "model"},
            "I need 5 marla in Block C",
        )
        assert out == {}

    def test_a_model_cannot_invent_a_block(self):
        out = _qualify.validate_requirement(
            {"block": "D", "source": "model"},
            "5 marla in Block A",
        )
        assert out == {}

    def test_a_model_cannot_switch_the_block_the_dealer_named(self):
        # D-55c: the letter "c" appears in "commercial", which used to
        # be enough to confirm a claim of Block C.
        out = _qualify.validate_requirement(
            {"block": "C", "source": "model"},
            "5 marla in Block A for commercial use",
        )
        assert out == {}

    def test_a_model_cannot_invent_a_purpose(self):
        out = _qualify.validate_requirement(
            {"purpose": "commercial", "source": "model"},
            "I need 5 marla for personal use",
        )
        assert out == {}

    def test_a_model_cannot_invent_a_timeline(self):
        out = _qualify.validate_requirement(
            {"timeline": "immediate", "source": "model"},
            "5 marla in Block A",
        )
        assert out == {}

    def test_a_model_cannot_add_an_unsupported_requirement_key(self):
        out = _qualify.validate_requirement(
            {"approved_master_hash": "abc", "source": "model"},
            "5 marla in Block A",
        )
        assert out == {}

    def test_a_model_cannot_propose_a_price(self):
        out = _qualify.validate_requirement(
            {"price_pkr": 7_500_000.0, "source": "model"},
            "5 marla in Block A",
        )
        assert out == {}

    def test_the_purposes_gate_does_not_crash(self):
        # D-55a: the old generator raised NameError on a purpose.
        out = _qualify.validate_requirement(
            {"purpose": "commercial", "source": "model"},
            "I need a commercial plot in Block C",
        )
        assert out["purpose"] == "commercial"

    def test_the_timeline_gate_does_not_crash(self):
        out = _qualify.validate_requirement(
            {"timeline": "immediate", "source": "model"},
            "I need it immediately in Block C",
        )
        assert out["timeline"] == "immediate"

    def test_an_implausible_model_budget_is_dropped(self):
        out = _qualify.validate_requirement(
            {"budget_max_pkr": 6.0, "source": "model"},
            "5 marla in Block A",
        )
        assert out == {}

    def test_the_applications_own_requirements_are_not_traceability_checked(self):
        # The application's extractor derived the value from the message
        # in the first place, so it is exempt.
        out = _qualify.validate_requirement(
            {"size_marla": 5.0, "source": "stated"},
            "5 marla in Block A",
        )
        assert out["size_marla"] == 5.0


# ===========================================================================
# 4. Qualification narrows and never widens
# ===========================================================================


class TestM9Narrowing:
    """Qualification is strictly narrowing-only."""

    def test_the_result_is_a_subset_of_the_input(self):
        rec = _rec(block="C", size=10)
        options = rec["options"]
        res = _qualify.apply_requirements(
            options, _reqs(budget_max_pkr=6_000_000.0))
        for option in res["options"]:
            assert option in options

    def test_narrowing_can_never_add_an_option(self):
        rec = _rec(block="C", size=10)
        options = rec["options"]
        before = len(options)
        res = _qualify.apply_requirements(
            options,
            _reqs(budget_max_pkr=6_000_000.0, block="A", size_marla=5.0,
                  purpose="investment", timeline="immediate"),
        )
        assert len(res["options"]) <= before

    def test_a_budget_ceiling_removes_the_options_above_it(self):
        rec = _rec(block="C", size=10)
        # C/7 has a 6,000,000 floor; B/10 starts at 9,300,000.
        res = _qualify.apply_requirements(
            rec["options"], _reqs(budget_max_pkr=8_000_000.0))
        kept = _cells(res["options"])
        assert ("B", 10.0) not in kept
        assert ("C", 7.0) in kept
        assert res["removed"]
        assert all(item["requirement"] == "budget"
                   for item in res["removed"])

    def test_a_budget_that_excludes_everything_returns_nothing(self):
        rec = _rec(block="C", size=10)
        res = _qualify.apply_requirements(
            rec["options"], _reqs(budget_max_pkr=1_000_000.0))
        assert res["options"] == []
        assert res["removed"]

    def test_a_preferred_block_re_ranks_rather_than_removes(self):
        rec = _rec(block="C", size=10)
        res = _qualify.apply_requirements(rec["options"], _reqs(block="B"))
        # Every option survives - a preference is not an exclusion.
        assert len(res["options"]) == len(rec["options"])
        assert res["options"][0]["block"] == "B"
        assert "block" in res["applied"]

    def test_a_preferred_size_re_ranks_rather_than_removes(self):
        rec = _rec(block="C", size=10)
        res = _qualify.apply_requirements(rec["options"], _reqs(size_marla=7.0))
        assert len(res["options"]) == len(rec["options"])
        assert res["options"][0]["size_marla"] == 7.0

    def test_a_budget_floor_removes_the_cells_below_it(self):
        # D-56: a floor is symmetric with a ceiling. "At least 12
        # million" must not be answered with a 6,000,000 cell.
        rec = _rec(block="C", size=10)
        res = _qualify.apply_requirements(
            rec["options"], _reqs(budget_min_pkr=12_000_000.0))
        kept = _cells(res["options"])
        # C/7 tops out at 11,500,000 - below the stated floor.
        assert ("C", 7.0) not in kept
        assert res["removed"]
        assert all(item["requirement"] == "budget"
                   for item in res["removed"])

    def test_a_budget_floor_that_narrows_nothing_is_recorded_as_unknown(self):
        rec = _rec(block="C", size=10)
        res = _qualify.apply_requirements(
            rec["options"], _reqs(budget_min_pkr=1_000_000.0))
        assert len(res["options"]) == len(rec["options"])
        assert "budget" in res["unknown"]

    def test_a_purpose_narrows_nothing_because_the_data_cannot_describe_it(self):
        # The approved master holds no category (374/374 null), so a
        # purpose must not remove a cell.
        rec = _rec(block="C", size=10)
        res = _qualify.apply_requirements(
            rec["options"], _reqs(purpose="commercial"))
        assert len(res["options"]) == len(rec["options"])
        assert "purpose" in res["unknown"]

    def test_a_timeline_is_recorded_as_unknown(self):
        rec = _rec(block="C", size=10)
        res = _qualify.apply_requirements(
            rec["options"], _reqs(timeline="immediate"))
        assert "timeline" in res["unknown"]

    def test_nothing_stated_keeps_every_option_in_the_same_order(self):
        rec = _rec(block="C", size=10)
        res = _qualify.apply_requirements(rec["options"], _reqs())
        assert _cells(res["options"]) == _cells(rec["options"])


# ===========================================================================
# 5. The decision ladder
# ===========================================================================


class TestM9DecisionLadder:
    """The product chooses the next best action from verified evidence."""

    def test_an_exact_verified_match_is_quoted(self):
        rec = _rec(block="C", size=7)
        assert rec["exact_match"] is not None
        out = _decision.decide(rec, _reqs(size_marla=7.0, block="C"))
        assert out["action"] == _decision.ACTION_QUOTE
        assert out["exact_match"] is not None
        assert out["options"]

    def test_an_exact_match_within_the_budget_is_quoted(self):
        rec = _rec(block="C", size=7)
        out = _decision.decide(rec, _reqs(budget_max_pkr=12_000_000.0))
        assert out["action"] == _decision.ACTION_QUOTE
        assert out["options"]

    def test_verified_alternatives_are_offered_when_the_exact_cell_is_thin(self):
        rec = _rec(block="C", size=10)
        assert rec["exact_match"] is None
        out = _decision.decide(rec, _reqs(size_marla=10.0, block="C"))
        assert out["action"] == _decision.ACTION_OFFER
        assert out["options"]

    def test_the_alternatives_are_ranked_against_the_stated_preferences(self):
        rec = _rec(block="C", size=10)
        out = _decision.decide(rec, _reqs(block="B"))
        assert out["options"][0]["block"] == "B"
        # And the whole set survives - a preference re-ranks.
        assert len(out["options"]) == len(rec["options"])

    def test_a_budget_that_excludes_everything_produces_a_clarifying_question(self):
        rec = _rec(block="C", size=10)
        out = _decision.decide(rec, _reqs(budget_max_pkr=1_000_000.0))
        assert out["action"] == _decision.ACTION_CLARIFY
        assert out["options"] == []
        assert out["clarifying_question"] is not None
        assert out["clarifying_question"]["requirement"] == "budget"

    def test_a_missing_budget_asks_rather_than_guessing(self):
        rec = _rec(block="C", size=10)
        out = _decision.decide(rec, _reqs(size_marla=10.0))
        assert out["requirements"]["budget_max_pkr"] is None
        assert out["requirements"]["budget_min_pkr"] is None
        # The question is available, and the requirements are not
        # filled in with a guess.
        question = _qualify.clarifying_question(
            out["requirements"], rec["options"])
        assert question is not None
        assert question["requirement"] == "budget"

    def test_conflicting_requirements_do_not_produce_a_silent_answer(self):
        # A budget that excludes everything AND a policy that needs a
        # human: the human wins.
        rec = _rec(block="C", size=10)
        out = _decision.decide(
            rec, _reqs(budget_max_pkr=1_000_000.0), needs_human=True)
        assert out["action"] == _decision.ACTION_ESCALATE
        assert out["options"] == []

    def test_a_policy_escalation_is_never_softened(self):
        rec = _rec(block="C", size=7)
        out = _decision.decide(rec, _reqs(), policy_action="escalate")
        assert out["action"] == _decision.ACTION_ESCALATE
        assert out["options"] == []
        assert out["exact_match"] is None

    def test_a_policy_refusal_is_never_softened(self):
        rec = _rec(block="C", size=7)
        out = _decision.decide(rec, _reqs(), policy_action="refuse")
        assert out["action"] == _decision.ACTION_ESCALATE
        assert out["options"] == []

    def test_every_action_requires_human_approval(self):
        rec = _rec(block="C", size=10)
        for requirements, policy in (
            (_reqs(), None),
            (_reqs(budget_max_pkr=1_000_000.0), None),
            (_reqs(), "escalate"),
        ):
            out = _decision.decide(rec, requirements, policy_action=policy)
            assert out["requires_human_approval"] is True
            assert out["availability_claimed"] is False

    def test_the_decision_never_claims_availability(self):
        rec = _rec(block="C", size=10)
        out = _decision.decide(rec, _reqs())
        assert out["availability_claimed"] is False

    def test_a_thin_cell_is_never_offered(self):
        rec = _rec(block="C", size=10)
        thin = rec["thin_cells"]
        assert thin, "the C/10 cell is below the evidence threshold"
        out = _decision.decide(rec, _reqs(size_marla=10.0, block="C"))
        offered = _cells(out["options"])
        for cell in thin:
            assert (cell["block"], cell["size_marla"]) not in offered

    def test_thin_cells_are_reported_as_gaps_not_options(self):
        rec = _rec(block="C", size=10)
        out = _decision.decide(rec, _reqs(size_marla=10.0, block="C"))
        assert out["thin_cells"] == rec["thin_cells"]

    def test_the_decision_keeps_the_evidence_threshold(self):
        # The threshold is the lookup's, and M9 must not lower it.
        policies = _recommend.price_lookup.load_policies()
        assert policies["min_listings_for_answer"] >= 3


# ===========================================================================
# 5b. Conflicting and ambiguous requirements
# ===========================================================================


class TestM9Conflicts:
    """A conflict is resolved by asking, never by guessing."""

    def test_a_conflicting_budget_removes_the_cell_it_conflicts_with(self):
        # "At least 12 million" conflicts with C/7, whose range tops
        # out at 11,500,000.
        rec = _rec(block="C", size=10)
        out = _decision.decide(
            rec, _reqs(budget_min_pkr=12_000_000.0))
        assert out["removed"]
        assert all(item["requirement"] == "budget"
                   for item in out["removed"])
        kept = _cells(out["options"])
        assert ("C", 7.0) not in kept

    def test_a_conflict_does_not_produce_a_silent_empty_answer(self):
        rec = _rec(block="C", size=10)
        out = _decision.decide(
            rec, _reqs(budget_min_pkr=12_000_000.0,
                       budget_max_pkr=20_000_000.0))
        # Either options remain, or the product asks - never an empty
        # answer with no explanation.
        assert out["options"] or out["clarifying_question"] is not None
        assert out["action"] in (
            _decision.ACTION_OFFER, _decision.ACTION_CLARIFY,
            _decision.ACTION_ESCALATE)

    def test_an_impossible_budget_asks_rather_than_answers(self):
        rec = _rec(block="C", size=10)
        out = _decision.decide(
            rec, _reqs(budget_max_pkr=1_000_000.0))
        assert out["action"] == _decision.ACTION_CLARIFY
        assert out["options"] == []
        assert out["clarifying_question"]["requirement"] == "budget"

    def test_an_inverted_budget_range_is_dropped_not_repaired(self):
        # The validator drops an unordered range rather than "fixing" it.
        validated = _qualify.validate_requirement({
            "budget_min_pkr": 20_000_000.0,
            "budget_max_pkr": 5_000_000.0,
        })
        assert "budget_min_pkr" not in validated
        assert "budget_max_pkr" not in validated

    def test_an_ambiguous_budget_that_matches_everything_keeps_everything(self):
        rec = _rec(block="C", size=10)
        out = _decision.decide(
            rec, _reqs(budget_min_pkr=1_000_000.0,
                       budget_max_pkr=30_000_000.0))
        assert len(out["options"]) == len(rec["options"])

    def test_a_stated_timeline_never_removes_an_option(self):
        # The master carries no timing attribute, so a timeline can
        # never narrow the verified set.
        rec = _rec(block="C", size=10)
        out = _decision.decide(rec, _reqs(timeline="immediate"))
        assert len(out["options"]) == len(rec["options"])

    def test_a_stated_purpose_never_removes_an_option(self):
        rec = _rec(block="C", size=10)
        out = _decision.decide(rec, _reqs(purpose="commercial"))
        assert len(out["options"]) == len(rec["options"])

    def test_the_policy_always_wins_over_the_market_layer(self):
        rec = _rec(block="C", size=7)
        for policy_action in ("escalate", "refuse"):
            out = _decision.decide(rec, _reqs(), policy_action=policy_action)
            assert out["action"] == _decision.ACTION_ESCALATE
            assert out["options"] == []
            assert out["exact_match"] is None


# ===========================================================================
# 6. The reply that carries the decision still passes the gates
# ===========================================================================

class TestM9ReplyGates:
    """The M5 numeric validator and the M6.1 claim guard still hold."""

    def test_a_qualified_alternative_passes_the_claim_guard(self):
        from market import reply_guard

        rec = _rec(block="C", size=10)
        out = _decision.decide(rec, _reqs(block="B"))
        alternatives = [
            {"block": o["block"], "size_marla": o["size_marla"],
             "verified": True}
            for o in out["options"]
        ]
        facts = {
            "facts_source": reply_guard.APPROVED_SOURCE,
            "answerable_for_demo": False,
            "verified_alternatives": alternatives,
        }
        reply = (
            "I need to confirm the current market information with our team "
            "before giving you a price. Other verified alternatives with more "
            "data are a 10 marla plot in Block B. Tell me your preferred "
            "size or block and I can narrow them down."
        )
        report = reply_guard.guard_reply(reply, facts=facts)
        assert report.ok, report.violations

    def test_a_clarifying_question_reply_passes_the_claim_guard(self):
        from market import reply_guard

        rec = _rec(block="C", size=10)
        out = _decision.decide(rec, _reqs(budget_max_pkr=1_000_000.0))
        reply = (
            "I need to confirm the current market information with our team "
            "before giving you a price. What is the highest budget you can "
            "work with? Human approval is required before sending."
        )
        report = reply_guard.guard_reply(
            reply,
            facts={"facts_source": reply_guard.APPROVED_SOURCE,
                   "answerable_for_demo": False},
        )
        assert report.ok, report.violations

    def test_a_clarifying_question_reply_passes_the_numeric_validator(self):
        from market import fact_validator

        reply = (
            "I need to confirm the current market information with our team "
            "before giving you a price. What is the highest budget you can "
            "work with? Human approval is required before sending."
        )
        report = fact_validator.validate_reply(reply, facts={})
        assert report.ok, report.violations

    def test_a_reply_cannot_name_an_option_the_application_did_not_verify(self):
        from market import reply_guard

        facts = {
            "facts_source": reply_guard.APPROVED_SOURCE,
            "answerable_for_demo": False,
            "verified_alternatives": [
                {"block": "B", "size_marla": 10.0, "verified": True},
            ],
        }
        reply = (
            "I need to confirm the current market information with our team "
            "before giving you a price. The closest match with more data is a "
            "10 marla plot in Block A."
        )
        report = reply_guard.guard_reply(reply, facts=facts)
        assert not report.ok
        assert any(v["code"] == "unsupported_pair"
                   for v in report.violations)

    def test_a_reply_cannot_claim_a_price_for_an_alternative(self):
        from market import fact_validator

        facts = {
            "facts_source": "FaisalHills verified partial master",
            "answerable_for_demo": False,
            "verified_alternatives": [
                {"block": "B", "size_marla": 10.0, "verified": True},
            ],
        }
        reply = (
            "A 10 marla plot in Block B is available for PKR 12,400,000."
        )
        report = fact_validator.validate_reply(reply, facts=facts)
        assert not report.ok


# ===========================================================================
# 7. Privacy and scope
# ===========================================================================


class TestM9PrivacyAndScope:
    """The M7 boundary and the scope rule are intact."""

    def test_the_requirements_carry_no_dealer_content(self):
        out = _qualify.extract_requirements(
            "I am Ali from Lahore, my number is 03001234567, "
            "budget 60 lakh for Block C")
        allowed = {
            "budget_min_pkr", "budget_max_pkr", "purpose", "block",
            "size_marla", "timeline", "source",
        }
        assert set(out) <= allowed

    def test_the_extractor_reads_no_master_and_no_database(self):
        # The extractor is a rules extractor over the message text. It
        # must not open the master or the database, so it can never
        # surface a dealer note, a dealer name or a plot number.
        import market.qualify as q
        source = open(q.__file__, encoding="utf-8").read()
        assert "sqlite3" not in source
        assert "load_inventory" not in source
        assert "master_inventory" not in source

    def test_the_narrowing_reads_no_master_and_no_database(self):
        import market.qualify as q
        source = open(q.__file__, encoding="utf-8").read()
        assert "sqlite3.connect" not in source

    def test_the_decision_reads_no_master_and_no_database(self):
        import market.decision as d
        source = open(d.__file__, encoding="utf-8").read()
        assert "sqlite3.connect" not in source

    def test_a_parked_block_is_refused_before_anything_is_counted(self):
        with pytest.raises(_recommend.RecommendationError):
            _rec(block="E", size=7)

    def test_the_scope_is_still_blocks_a_b_c(self):
        from market import price_lookup
        policies = price_lookup.load_policies()
        assert sorted(policies["active_blocks"]) == ["A", "B", "C"]


# ===========================================================================
# 8. The M8 behaviour is untouched
# ===========================================================================


class TestM9M8Compatibility:
    """M9 must not change what M8 does."""

    def test_the_m8_recommendation_is_unchanged(self):
        rec = _rec(block="C", size=10)
        assert rec["exact_match"] is None
        assert len(rec["options"]) == 3
        assert rec["thin_cells"]
        assert rec["availability_claimed"] is False
        assert rec["next_best_action"]["action"] == "offer_verified_alternatives"

    def test_the_m8_action_set_is_unchanged(self):
        rec = _rec(block="C", size=7)
        assert rec["next_best_action"]["action"] == "quote_exact_match"

    def test_the_m8_options_still_carry_their_evidence(self):
        rec = _rec(block="C", size=10)
        for option in rec["options"]:
            summary = option["summary"]
            assert summary["matched_plots"] >= 3
            assert summary["price_median_pkr"] is not None
            assert option["reason"]
