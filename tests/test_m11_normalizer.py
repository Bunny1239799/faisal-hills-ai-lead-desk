"""M11.2 - the input normalizer.

The normalizer is the small, tested layer in front of the existing
extractors. The rules under test:

* every form it rewrites is a form the extractor already understands
  somewhere else in the product;
* a form it does **not** know is left **exactly** as it is - it never
  invents a size, a block or a budget;
* it never **loses** a requirement the original text already carried;
* it is **idempotent** - normalizing a normalized message changes nothing;
* the dimension table is **DEC-10's** and nothing else (DEC-11's
  unconfirmed 30x50 = 6 marla is not mapped).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from market.normalize import DEC10_DIMENSIONS, normalize_message
from market.qualify import extract_requirements


def _requirements(text):
    """The requirements of a text, without the bookkeeping key."""
    found = extract_requirements(text)
    return {k: v for k, v in found.items() if k != "source"}


class TestAmounts:
    @pytest.mark.parametrize("text,expected", [
        ("80 lakh", 8000000),
        ("80 lac", 8000000),
        ("1 crore", 10000000),
        ("1.5 crore", 15000000),
        ("1 cr", 10000000),
        ("12 million", 12000000),
    ])
    def test_the_amounts_the_extractor_already_reads_are_left_alone(
            self, text, expected):
        result = normalize_message(text)
        assert result.text == text
        assert result.changed is False
        assert _requirements(result.text)["budget_min_pkr"] == expected

    def test_the_one_amount_the_extractor_misses_is_rewritten(self):
        result = normalize_message("budget 8 mn")
        assert result.text == "budget 8 million"
        assert _requirements(result.text)["budget_min_pkr"] == 8000000

    def test_a_bare_m_is_left_to_the_settled_m9_rule(self):
        """A bare "8M" is a SIZE under the M9 decision (D-51).

        The normalizer does not overturn a settled rule of the
        qualification layer, and it does not invent a money reading.
        """
        result = normalize_message("8M")
        assert result.text == "8M"
        assert _requirements(result.text)["size_marla"] == 8.0

    def test_money_in_a_money_context_is_still_a_money_context(self):
        result = normalize_message("my budget is 8M")
        assert result.text == "my budget is 8M"
        assert _requirements(result.text)["budget_min_pkr"] == 8000000


class TestMarlaSpellings:
    @pytest.mark.parametrize("text", [
        "5 marla", "5 marlas", "5marla", "5-marla", "5 marle", "5 marlay",
        "5 marley", "5 marala",
    ])
    def test_every_marla_spelling_reads_as_the_same_size(self, text):
        result = normalize_message(text)
        assert _requirements(result.text)["size_marla"] == 5.0

    def test_a_hyphenated_marla_is_rewritten(self):
        assert normalize_message("5-marla").text == "5 marla"

    def test_a_misspelled_marla_is_rewritten(self):
        assert normalize_message("5 marle").text == "5 marla"
        assert normalize_message("5 marala").text == "5 marla"

    def test_marlas_becomes_marla(self):
        assert normalize_message("5 marlas").text == "5 marla"


class TestDimensionNames:
    """DEC-10's table, and only DEC-10's table."""

    @pytest.mark.parametrize("text,expected", [
        ("25x50", 5.0),
        ("30x60", 7.0),
        ("35 x 70", 10.0),
        ("40x80", 14.0),
        ("50x90", 20.0),
        ("75x120", 40.0),
    ])
    def test_an_approved_dimension_reads_as_its_marla_size(self, text,
                                                          expected):
        result = normalize_message(text)
        assert _requirements(result.text)["size_marla"] == expected

    def test_the_unconfirmed_dimension_is_left_alone(self):
        """DEC-11: 30x50 = 6 marla is UNCONFIRMED, so it is not mapped."""
        assert (30, 50) not in DEC10_DIMENSIONS
        result = normalize_message("30x50")
        assert result.text == "30x50"
        assert _requirements(result.text).get("size_marla") is None

    def test_an_unknown_dimension_is_left_alone(self):
        result = normalize_message("20x30")
        assert result.text == "20x30"
        assert _requirements(result.text).get("size_marla") is None

    def test_a_dimension_in_a_sentence_is_rewritten(self):
        result = normalize_message("I want a 30x60 plot in Block C")
        assert result.text == "I want a 7 marla plot in Block C"
        found = _requirements(result.text)
        assert found["size_marla"] == 7.0
        assert found["block"] == "C"


class TestBlockNames:
    @pytest.mark.parametrize("text,expected", [
        ("block c", "C"),
        ("c block", "C"),
        ("fhc", "C"),
        ("block a mein", "A"),
    ])
    def test_the_block_aliases_read_as_the_same_block(self, text, expected):
        result = normalize_message(text)
        assert _requirements(result.text)["block"] == expected

    def test_fhc_is_rewritten_to_the_canonical_block(self):
        assert normalize_message("FHC").text == "block c"

    def test_a_parked_block_is_not_rewritten(self):
        """The scope rule must see a parked block exactly as it was typed."""
        for text in ("fhd", "fhe", "block d", "executive block"):
            assert normalize_message(text).text == text


class TestRomanUrdu:
    def test_a_roman_urdu_sentence_reads_the_same_requirements(self):
        found = _requirements(normalize_message(
            "5 marla block c mein chahiye, budget 80 lakh").text)
        assert found["size_marla"] == 5.0
        assert found["block"] == "C"
        assert found["budget_min_pkr"] == 8000000

    def test_a_month_in_the_singular_reads_as_a_timeline(self):
        found = _requirements(normalize_message("3 month mein").text)
        assert found["timeline"] == "three_months"

    def test_a_plural_month_is_left_alone(self):
        assert normalize_message("3 months").text == "3 months"

    def test_urdu_digits_are_converted_by_the_repositorys_own_function(self):
        result = normalize_message("۵ مارلا")
        assert result.changed is True
        assert "۵" not in result.text


class TestTheGuarantees:
    CORPUS = [
        "I need a plot",
        "5 marla in Block C",
        "80 lakh",
        "1 crore",
        "30x60 plot",
        "5-marla",
        "budget 8 mn",
        "my budget is 12 million",
        "for investment",
        "within three months",
        "5 marla Block C budget 80 lakh for investment",
        "FHC 5 marla",
        "30x50 plot",
        "sasta 5 marla block c",
        "20% off a 7 marla plot in Block C",
        "hello",
        "",
    ]

    def test_the_normalizer_is_idempotent(self):
        for text in self.CORPUS:
            once = normalize_message(text).text
            twice = normalize_message(once).text
            assert twice == once, text

    def test_the_normalizer_never_loses_a_requirement(self):
        for text in self.CORPUS:
            before = _requirements(text)
            after = _requirements(normalize_message(text).text)
            for key, value in before.items():
                if value is None:
                    continue
                assert after.get(key) == value, (text, key, before, after)

    def test_the_normalizer_never_changes_a_requirement_it_did_not_widen(self):
        """A requirement that was already read must read the SAME."""
        for text in self.CORPUS:
            before = _requirements(text)
            after = _requirements(normalize_message(text).text)
            for key, value in before.items():
                if value is None:
                    continue
                assert after.get(key) == value, (text, key)

    def test_the_normalizer_never_invents_a_requirement(self):
        """A message it does not understand yields no requirement."""
        for text in ("30x50 plot", "20x30 plot", "hello", ""):
            after = _requirements(normalize_message(text).text)
            assert all(value is None for value in after.values()), text

    def test_an_empty_message_is_handled(self):
        result = normalize_message("")
        assert result.text == ""
        assert result.changed is False
        result = normalize_message(None)
        assert result.text == ""

    def test_the_changes_are_reported(self):
        result = normalize_message("30x60 plot")
        assert result.changed is True
        assert result.changes[0]["kind"] == "dimension"
        assert "30x60" in result.changes[0]["before"]
