"""D-65 - the discount request must ALWAYS escalate, in every wording.

The defect
----------
The policy gate escalated a message that contained the word "discount"
and **answered** the same request written the way a customer writes it:
"20% off", "knock 20 percent off", "rebate", "reduce the price",
"negotiable?". RULES_SHORT #3 requires a discount, a negotiation or a
commission discussion to always escalate.

The fix
-------
ONE shared discount-term list (`market/discount_terms.py`) is read by
BOTH the policy gate (`app/policy.py`, the request path) and the claim
guard (`market/reply_guard.py`, the reply path). These tests pin:

* every phrasing of the measurement script escalates;
* the benign phrasings do NOT escalate (no false positives);
* an escalated discount request carries NO price in the reply;
* the claim guard refuses a reply that CLAIMS a discount;
* the claim guard accepts a reply that REFUSES one;
* the two layers read the SAME list (they cannot drift).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.policy import evaluate_policy
from app.pipeline import handle_message
from market import discount_terms
from market.reply_guard import guard_reply


# The exact phrasings the Phase 2 measurement script used. Every one of
# them must escalate.
DISCOUNT_PHRASINGS = [
    "20% discount",
    "20% off",
    "knock 20 percent off",
    "give me a discount",
    "any discount?",
    "rebate",
    "price reduce",
    "reduce the price",
    "can you do better on price",
    "special rate for me",
    "kitna discount milega",
    "20 percent kam",
    "best price kya hai",
    "last price",
    "final rate",
    "negotiable?",
    "Give me 20% discount on a 7 marla plot in Block C.",
    "20% off a 7 marla plot in Block C?",
    "Can I get 5 lakh discount on cash payment?",
    "koi discount milega 5 marla block C ke liye?",
    "please reduce the rate for a 10 marla plot in Block B",
]

# The benign phrasings. These must NOT escalate.
BENIGN_PHRASINGS = [
    "what is the median price for 5 marla in Block C",
    "what is the price of a 7 marla plot in Block A",
    "how many 5 marla plots are in Block C",
    "I need a plot in Block B",
]

_PRICE_FIGURE = re.compile(r"\b\d{1,3}(?:,\d{3}){1,}\b")


class TestPolicyEscalatesEveryDiscountWording:
    """The request path: every discount wording reaches a human."""

    @pytest.mark.parametrize("message", DISCOUNT_PHRASINGS)
    def test_every_discount_wording_escalates(self, message):
        decision = evaluate_policy(message)
        assert decision.needs_human is True, message
        assert decision.action in ("escalate", "refuse"), message
        assert "discount" in decision.risk_tags, message

    @pytest.mark.parametrize("message", DISCOUNT_PHRASINGS)
    def test_every_discount_wording_escalates_through_the_real_pipeline(self, message):
        result = handle_message(message)
        assert result["decision"]["action"] in ("escalate", "refuse"), message
        assert result["needs_human"] is True, message

    @pytest.mark.parametrize("message", DISCOUNT_PHRASINGS)
    def test_no_discount_request_reaches_a_priced_reply(self, message):
        """An escalated discount request must carry no price at all."""
        result = handle_message(message)
        reply = result.get("draft_reply") or ""
        assert not _PRICE_FIGURE.search(reply), (message, reply)
        assert result.get("market_facts") is None, message


class TestNoFalsePositives:
    """The benign phrasings must stay answerable."""

    @pytest.mark.parametrize("message", BENIGN_PHRASINGS)
    def test_benign_phrasings_do_not_escalate(self, message):
        decision = evaluate_policy(message)
        assert decision.needs_human is False, message
        assert decision.action == "answer", message
        assert "discount" not in decision.risk_tags, message

    @pytest.mark.parametrize("message", BENIGN_PHRASINGS)
    def test_benign_phrasings_stay_answerable_through_the_real_pipeline(self, message):
        result = handle_message(message)
        assert result["decision"]["action"] == "answer", message
        assert result["needs_human"] is False, message

    def test_an_ordinary_price_question_is_not_a_discount_request(self):
        assert discount_terms.detect_discount_request(
            "What is the price of a 7 marla plot in Block A?") is None
        assert discount_terms.detect_discount_request(
            "What is the median price for 5 marla in Block C?") is None
        assert discount_terms.detect_discount_request(
            "How many 5 marla plots are in Block C?") is None
        assert discount_terms.detect_discount_request(
            "I need a plot in Block B") is None


class TestTheClaimGuardReadsTheSameList:
    """The reply path: a discount CLAIM is refused, a REFUSAL is not."""

    def test_a_reply_that_claims_a_discount_is_refused(self):
        report = guard_reply(
            "Sure, I can offer you 20% off the asking price.",
            facts=None,
            action="answer",
            reply_mode="verified_market_facts",
        )
        assert report.ok is False
        assert any(v["code"] == "discount_claim" for v in report.violations)

    def test_a_reply_that_offers_a_rebate_is_refused(self):
        report = guard_reply(
            "A rebate of 5 lakh can be arranged for you.",
            action="answer",
            reply_mode="verified_market_facts",
        )
        assert report.ok is False
        assert any(v["code"] == "discount_claim" for v in report.violations)

    def test_a_reply_that_refuses_a_discount_is_accepted(self):
        report = guard_reply(
            "We cannot offer a discount. Our team must approve any "
            "price change before it is sent.",
            action="escalate",
            reply_mode="no_lookup",
        )
        assert report.ok is True, report.violations

    def test_a_reply_that_says_no_discount_is_accepted(self):
        report = guard_reply(
            "No discount is available. The asking-price range is PKR "
            "6,000,000 to PKR 11,500,000. These are dealer asking prices, "
            "not confirmed sold prices. Human approval is required before "
            "sending.",
            facts={"facts_source": "FaisalHills verified partial master"},
            action="answer",
            reply_mode="verified_market_facts",
        )
        assert report.ok is True, report.violations

    def test_the_policy_and_the_guard_read_the_same_list(self):
        """They cannot drift: the guard's terms are the policy's terms."""
        for message in DISCOUNT_PHRASINGS:
            assert discount_terms.detect_discount_request(message), message
            # The same text, read as a reply, is a claim unless it refuses.
            assert discount_terms.detect_discount_claim(message), message


class TestTheSharedListItself:
    """The list is a list, it is in one place, and it is stdlib-only."""

    def test_the_list_is_not_empty_and_covers_the_measured_phrasings(self):
        assert len(discount_terms.DISCOUNT_TERMS) >= 20
        for message in DISCOUNT_PHRASINGS:
            assert discount_terms.discount_terms_in(message), message

    def test_the_list_does_not_catch_a_benign_price_question(self):
        for message in BENIGN_PHRASINGS:
            assert discount_terms.discount_terms_in(message) == [], message

    def test_the_module_is_read_only_and_model_free(self):
        source = (REPO_ROOT / "market" / "discount_terms.py").read_text(
            encoding="utf-8")
        assert "import requests" not in source
        assert "urllib" not in source
        assert "open(" not in source
        assert "sqlite" not in source.lower()
