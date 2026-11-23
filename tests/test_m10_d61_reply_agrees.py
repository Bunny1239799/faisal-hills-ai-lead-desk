"""M9 D-61 / D-62 - the reply must AGREE with the decision.

These are REGRESSION tests for two defects found by measuring the live
pipeline rather than by reading it.

D-61  The reply quoted a cell the dealer's own budget had excluded.

      "What is the price of a 7 marla plot in Block C? My budget is 5
      million." produced a decision of ``offer_verified_alternatives``
      - the M9 layer had removed C/7 (it starts at 6,000,000) and kept
      C/5 - but the REPLY still quoted C/7's full price band. The
      decision and the reply disagreed, and the reply is the part the
      dealer reads.

      Neither final gate could see it: the numbers traced to the master
      (so the M5 validator passed) and the claims matched the evidence
      (so the M6.1 guard passed). A budget is not a fact, so only the
      application can see the conflict.

D-62  A clarifying question on an answerable cell was blocked by the
      M6.1 guard for "losing provenance", and the dealer got the
      generic hold wording instead of the question. A question carries
      no price, so it must not be judged as an ANSWERABLE reply.
"""

import os
import sys
import tempfile

PROJECT_ROOT = r"D:\AI-Projects\laya-gateway"
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

TMP = tempfile.mkdtemp(prefix="fh_m10_d61_")
os.environ["DB_PATH"] = os.path.join(TMP, "d61.db")

from market import decision as _decision  # noqa: E402
from market import qualify as _qualify  # noqa: E402

from app import pipeline as _pipeline  # noqa: E402
from data.db import init_db  # noqa: E402

_conn = init_db(os.environ["DB_PATH"])
_conn.close()


# The C/7 cell starts at PKR 6,000,000, so a 5,000,000 budget excludes
# it. C/5 starts at 3,950,000 and overlaps, so it is kept.
BUDGET_EXCLUDES_THE_CELL = (
    "What is the price of a 7 marla plot in Block C? My budget is 5 million."
)
BUDGET_EXCLUDES_EVERYTHING = (
    "What is the price of a 7 marla plot in Block C? My budget is 1 million."
)


class TestD61TheReplyAgreesWithTheDecision:
    """The reply must not quote a cell the dealer's requirement excluded."""

    def test_the_decision_excludes_the_cell_the_budget_rules_out(self):
        result = _pipeline.handle_message(BUDGET_EXCLUDES_THE_CELL)
        action = (result.get("next_best_action") or {}).get("action")
        assert action == _decision.ACTION_OFFER
        alternatives = result.get("verified_alternatives") or []
        named = [(a["block"], a["size_marla"]) for a in alternatives]
        assert ("C", 7.0) not in named, (
            "the excluded cell must not survive as an alternative")

    def test_the_reply_does_not_quote_the_excluded_cell(self):
        # The defect: the reply carried the excluded cell's price band.
        result = _pipeline.handle_message(BUDGET_EXCLUDES_THE_CELL)
        reply = result.get("draft_reply") or ""
        assert "6,000,000" not in reply, (
            "the reply must not quote the price of a cell the budget "
            "excluded")
        assert "11,500,000" not in reply
        assert "7,900,000" not in reply

    def test_the_reply_does_not_quote_the_excluded_cell_at_all(self):
        # Even without a price, the reply must not present the excluded
        # cell as an option.
        result = _pipeline.handle_message(BUDGET_EXCLUDES_THE_CELL)
        reply = result.get("draft_reply") or ""
        assert "7 marla plot in Block C" not in reply

    def test_the_excluded_cell_is_not_answerable(self):
        result = _pipeline.handle_message(BUDGET_EXCLUDES_THE_CELL)
        assert result.get("market_answerable") is False
        facts = (result.get("market_facts") or {}).get("facts") or {}
        assert facts.get("price_median_pkr") is None
        assert facts.get("price_min_pkr") is None
        assert facts.get("price_max_pkr") is None

    def test_the_reply_offers_the_alternative_the_decision_chose(self):
        result = _pipeline.handle_message(BUDGET_EXCLUDES_THE_CELL)
        reply = result.get("draft_reply") or ""
        assert "5 marla plot in Block C" in reply

    def test_both_final_gates_still_pass(self):
        # The fix must not have been bought by weakening a gate.
        result = _pipeline.handle_message(BUDGET_EXCLUDES_THE_CELL)
        assert result.get("traceability_ok") is True
        assert result.get("claim_guard_ok") is True
        assert result.get("traceability_blocked") is False
        assert result.get("claim_guard_blocked") is False

    def test_the_reply_is_not_a_stock_claim(self):
        result = _pipeline.handle_message(BUDGET_EXCLUDES_THE_CELL)
        reply = result.get("draft_reply") or ""
        assert "available" not in reply.lower()
        assert "in stock" not in reply.lower()

    def test_an_ordinary_question_is_unaffected(self):
        # The M4 behaviour must be byte-for-byte unchanged when the
        # dealer states nothing that conflicts.
        result = _pipeline.handle_message(
            "What is the price of a 7 marla plot in Block C?")
        assert result.get("market_answerable") is True
        reply = result.get("draft_reply") or ""
        assert "7,900,000" in reply
        assert (result.get("next_best_action") or {}).get("action") == \
            _decision.ACTION_QUOTE

    def test_a_budget_floor_also_withholds_the_excluded_cell(self):
        # The FLOOR case was missed by the first fix: the exact cell's
        # removal was compared by BLOCK alone, so the removal of C/5
        # stopped the removal of C/7 from being recorded. The cell was
        # excluded, but the reply went on quoting its price.
        result = _pipeline.handle_message(
            "What is the price of a 7 marla plot in Block C? "
            "I need at least 12 million.")
        reply = result.get("draft_reply") or ""
        assert "6,000,000" not in reply, (
            "the reply must not quote the price of a cell the floor "
            "excluded")
        assert "7,900,000" not in reply
        assert "11,500,000" not in reply
        assert result.get("market_answerable") is False

    def test_a_budget_floor_still_offers_the_alternative_it_kept(self):
        result = _pipeline.handle_message(
            "What is the price of a 7 marla plot in Block C? "
            "I need at least 12 million.")
        alternatives = result.get("verified_alternatives") or []
        named = [(a["block"], a["size_marla"]) for a in alternatives]
        assert ("A", 7.0) in named
        assert ("C", 7.0) not in named

    def test_a_budget_that_excludes_everything_asks_rather_than_quoting(self):
        result = _pipeline.handle_message(BUDGET_EXCLUDES_EVERYTHING)
        action = (result.get("next_best_action") or {}).get("action")
        assert action == _decision.ACTION_CLARIFY
        reply = result.get("draft_reply") or ""
        assert "7,900,000" not in reply
        assert "budget" in reply.lower()


class TestD62AQuestionIsNotAnAnswer:
    """A clarifying question must be judged as a question."""

    def test_the_question_reaches_the_dealer(self):
        # The defect: the guard demanded the answerable provenance
        # markers and refused the question, so the dealer got the
        # generic hold wording instead.
        result = _pipeline.handle_message(BUDGET_EXCLUDES_EVERYTHING)
        reply = result.get("draft_reply") or ""
        assert "highest budget" in reply.lower()
        assert "A member of our team will review it" not in reply

    def test_the_guard_accepts_the_question(self):
        result = _pipeline.handle_message(BUDGET_EXCLUDES_EVERYTHING)
        assert result.get("claim_guard_ok") is True
        assert result.get("claim_guard_blocked") is False
        assert (result.get("claim_guard") or {}).get("state") == "insufficient"

    def test_the_validator_accepts_the_question(self):
        result = _pipeline.handle_message(BUDGET_EXCLUDES_EVERYTHING)
        assert result.get("traceability_ok") is True
        assert result.get("traceability_blocked") is False

    def test_the_question_carries_no_price(self):
        result = _pipeline.handle_message(BUDGET_EXCLUDES_EVERYTHING)
        reply = result.get("draft_reply") or ""
        assert "PKR" not in reply
        assert "median" not in reply.lower()

    def test_the_question_keeps_the_hand_off(self):
        result = _pipeline.handle_message(BUDGET_EXCLUDES_EVERYTHING)
        reply = result.get("draft_reply") or ""
        assert "Human approval is required" in reply

    def test_the_thin_cell_question_is_still_asked(self):
        # The working case must not regress.
        result = _pipeline.handle_message(
            "What is the rate of 10 marla in Block C? Budget 5 million.")
        action = (result.get("next_best_action") or {}).get("action")
        assert action == _decision.ACTION_CLARIFY
        reply = result.get("draft_reply") or ""
        assert "highest budget" in reply.lower()


class TestTheDecisionRecordsTheExclusion:
    """``exact_excluded`` is the flag the pipeline reads."""

    def test_the_decision_records_the_exclusion(self):
        requirements = _qualify.extract_requirements(BUDGET_EXCLUDES_THE_CELL)
        from market import recommend as _recommend
        recommendation = _recommend.build_recommendations(
            block="C", size_marla=7, limit=3, include_listings=False)
        out = _decision.decide(recommendation, requirements)
        assert out.get("exact_excluded") is True

    def test_a_budget_floor_records_the_exclusion(self):
        requirements = _qualify.extract_requirements(
            "I need at least 12 million")
        from market import recommend as _recommend
        recommendation = _recommend.build_recommendations(
            block="C", size_marla=7, limit=3, include_listings=False)
        out = _decision.decide(recommendation, requirements)
        assert out.get("exact_excluded") is True
        # The exact cell's removal must be RECORDED, not just detected.
        removed = out.get("removed") or []
        assert any(
            item.get("block") == "C"
            and item.get("size_marla") == 7.0
            for item in removed
        ), "the exact cell's removal must be recorded"

    def test_a_quotable_cell_is_not_excluded(self):
        requirements = _qualify.extract_requirements(
            "What is the price of a 7 marla plot in Block C?")
        from market import recommend as _recommend
        recommendation = _recommend.build_recommendations(
            block="C", size_marla=7, limit=3, include_listings=False)
        out = _decision.decide(recommendation, requirements)
        assert out.get("action") == _decision.ACTION_QUOTE
        assert out.get("exact_excluded") is False

    def test_every_decision_carries_the_flag(self):
        from market import recommend as _recommend
        recommendation = _recommend.build_recommendations(
            block="C", size_marla=7, limit=3, include_listings=False)
        for requirements in (
            _qualify.empty_requirements(),
            _qualify.empty_requirements(budget_max_pkr=5_000_000.0),
            _qualify.empty_requirements(budget_min_pkr=12_000_000.0),
            _qualify.empty_requirements(purpose="investment"),
        ):
            out = _decision.decide(recommendation, requirements)
            assert "exact_excluded" in out
            assert isinstance(out["exact_excluded"], bool)
