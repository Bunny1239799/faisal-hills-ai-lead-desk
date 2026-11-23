"""M11.1 - the lead-state schema: five fields, each with a provenance.

The rules under test:

* an **unknown** field stays explicitly unknown - it is never a guess;
* a stated field records the **turn** it came from;
* a **correction** replaces the old value, becomes ``corrected``, and is
  recorded in the change log;
* restating the same value is **not** a correction;
* the state round-trips through its store;
* a state that cannot be read is **all unknown** - the store fails closed.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from market import lead_state as _lead_state
from market.lead_state import (
    FIELDS,
    STATUS_CORRECTED,
    STATUS_STATED,
    STATUS_UNKNOWN,
    LeadState,
    LeadStateStore,
    state_from_requirements,
)
from market.qualify import extract_requirements


class TestTheSchema:
    def test_there_are_exactly_five_fields(self):
        assert FIELDS == ("size", "block", "budget", "purpose", "timeline")

    def test_an_empty_state_has_every_field_explicitly_unknown(self):
        state = LeadState.empty()
        for name in FIELDS:
            assert state.value(name) is None
            assert state.status(name) == STATUS_UNKNOWN
            assert state.source_turn(name) is None
        assert state.unknowns() == list(FIELDS)

    def test_the_state_is_a_plain_dict_when_served(self):
        served = LeadState.empty().to_dict()
        assert set(served) == {"fields", "turn", "changes"}
        for name in FIELDS:
            assert set(served["fields"][name]) == {
                "value", "status", "source_turn"}


class TestStating:
    def test_a_stated_field_becomes_stated_with_its_turn(self):
        state = LeadState.empty()
        state.apply("size", 7.0, turn=2)
        assert state.value("size") == 7.0
        assert state.status("size") == STATUS_STATED
        assert state.source_turn("size") == 2

    def test_stating_a_field_leaves_the_others_unknown(self):
        state = LeadState.empty()
        state.apply("block", "C", turn=1)
        assert state.unknowns() == ["size", "budget", "purpose", "timeline"]

    def test_a_turn_that_does_not_mention_a_field_does_not_withdraw_it(self):
        state = LeadState.empty()
        state.apply("block", "C", turn=1)
        state.apply("size", 5.0, turn=2)
        assert state.value("block") == "C"
        assert state.status("block") == STATUS_STATED

    def test_applying_none_changes_nothing(self):
        state = LeadState.empty()
        assert state.apply("size", None, turn=1) is False
        assert state.status("size") == STATUS_UNKNOWN


class TestCorrections:
    def test_a_correction_replaces_the_value_and_is_recorded(self):
        state = LeadState.empty()
        state.apply("budget", {"min_pkr": 8000000, "max_pkr": 8000000}, turn=4)
        assert state.apply(
            "budget", {"min_pkr": 12000000, "max_pkr": 12000000}, turn=6) is True

        assert state.value("budget") == {
            "min_pkr": 12000000, "max_pkr": 12000000}
        assert state.status("budget") == STATUS_CORRECTED
        assert state.source_turn("budget") == 6
        assert state.corrections() == ["budget"]

        assert len(state.changes) == 1
        change = state.changes[0]
        assert change["field"] == "budget"
        assert change["old"] == {"min_pkr": 8000000, "max_pkr": 8000000}
        assert change["new"] == {"min_pkr": 12000000, "max_pkr": 12000000}
        assert change["turn"] == 6

    def test_restating_the_same_value_is_not_a_correction(self):
        state = LeadState.empty()
        state.apply("size", 7.0, turn=1)
        assert state.apply("size", 7.0, turn=3) is False
        assert state.status("size") == STATUS_STATED
        assert state.source_turn("size") == 3
        assert state.changes == []

    def test_a_correction_followed_by_a_restatement_keeps_the_correction(self):
        state = LeadState.empty()
        state.apply("size", 5.0, turn=1)
        state.apply("size", 7.0, turn=2)
        state.apply("size", 7.0, turn=3)
        assert state.value("size") == 7.0
        assert state.status("size") == STATUS_STATED
        assert len(state.changes) == 1

    def test_a_correction_of_a_field_that_was_unknown_is_just_a_statement(self):
        state = LeadState.empty()
        assert state.apply("block", "C", turn=1) is False
        assert state.status("block") == STATUS_STATED
        assert state.changes == []


class TestFromRequirements:
    """The values come from the M9 extractor, never from this module."""

    def test_the_state_is_built_from_the_extractor(self):
        requirements = extract_requirements("I need a 7 marla plot in Block C")
        state = state_from_requirements(requirements, turn=1)
        assert state.value("size") == 7.0
        assert state.value("block") == "C"
        assert state.status("size") == STATUS_STATED
        assert state.source_turn("size") == 1
        assert state.value("budget") is None
        assert state.value("purpose") is None
        assert state.value("timeline") is None

    def test_a_budget_becomes_a_min_max_pair(self):
        requirements = extract_requirements("my budget is 8 million")
        state = state_from_requirements(requirements, turn=1)
        assert state.value("budget") == {
            "min_pkr": 8000000, "max_pkr": 8000000}

    def test_a_requirement_the_turn_did_not_state_is_kept(self):
        first = state_from_requirements(
            extract_requirements("5 marla in Block C"), turn=1)
        second = state_from_requirements(
            extract_requirements("my budget is 8 million"), previous=first,
            turn=2)
        assert second.value("size") == 5.0
        assert second.value("block") == "C"
        assert second.value("budget") == {
            "min_pkr": 8000000, "max_pkr": 8000000}
        assert second.source_turn("size") == 1
        assert second.source_turn("budget") == 2

    def test_a_correction_across_two_turns_is_recorded(self):
        first = state_from_requirements(
            extract_requirements("my budget is 8 million"), turn=1)
        second = state_from_requirements(
            extract_requirements("actually my budget is 12 million"),
            previous=first, turn=2)
        assert second.value("budget") == {
            "min_pkr": 12000000, "max_pkr": 12000000}
        assert second.status("budget") == STATUS_CORRECTED
        assert len(second.changes) == 1
        assert second.changes[0]["turn"] == 2

    def test_the_turn_number_advances_by_default(self):
        first = state_from_requirements(
            extract_requirements("5 marla"), turn=None)
        assert first.turn == 1
        second = state_from_requirements(
            extract_requirements("Block C"), previous=first, turn=None)
        assert second.turn == 2


class TestTheStore:
    def test_a_state_round_trips_through_the_store(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = LeadStateStore(os.path.join(tmp, "state.db"))
            state = LeadState.empty()
            state.apply("size", 7.0, turn=1)
            state.apply("budget", {"min_pkr": 8000000, "max_pkr": 8000000},
                        turn=2)
            state.apply("budget", {"min_pkr": 12000000, "max_pkr": 12000000},
                        turn=3)
            assert store.save("session-1", state) is True

            loaded = store.load("session-1")
            assert loaded.value("size") == 7.0
            assert loaded.value("budget") == {
                "min_pkr": 12000000, "max_pkr": 12000000}
            assert loaded.status("budget") == STATUS_CORRECTED
            assert loaded.source_turn("budget") == 3
            assert len(loaded.changes) == 1

    def test_an_unknown_session_is_all_unknown(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = LeadStateStore(os.path.join(tmp, "state.db"))
            state = store.load("never-seen")
            for name in FIELDS:
                assert state.value(name) is None
                assert state.status(name) == STATUS_UNKNOWN

    def test_an_unreadable_store_is_all_unknown(self):
        store = LeadStateStore(os.path.join("Z:\\no", "such", "dir", "s.db"))
        state = store.load("session-1")
        for name in FIELDS:
            assert state.status(name) == STATUS_UNKNOWN

    def test_a_corrupt_record_is_all_unknown(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "state.db")
            store = LeadStateStore(path)
            store.save("session-1", LeadState.empty())
            import sqlite3
            conn = sqlite3.connect(path)
            conn.execute(
                "UPDATE lead_state SET state_json = 'not json' "
                "WHERE session_id = 'session-1'")
            conn.commit()
            conn.close()

            state = store.load("session-1")
            for name in FIELDS:
                assert state.status(name) == STATUS_UNKNOWN

    def test_the_store_does_not_touch_the_owner_database(self):
        """The M11 store is a file of its own; the owner's DB is not used."""
        with tempfile.TemporaryDirectory() as tmp:
            store = LeadStateStore(os.path.join(tmp, "state.db"))
            store.save("session-1", LeadState.empty())
            assert os.path.isfile(store.path)
            assert "faisal_hills" not in os.path.basename(store.path)


class TestFailClosed:
    def test_a_state_that_cannot_be_read_is_all_unknown(self):
        state = LeadState.from_dict(None)
        for name in FIELDS:
            assert state.status(name) == STATUS_UNKNOWN
        state = LeadState.from_dict({"fields": "not a dict"})
        for name in FIELDS:
            assert state.status(name) == STATUS_UNKNOWN

    def test_a_value_without_a_status_is_unknown(self):
        state = LeadState.from_dict(
            {"fields": {"size": {"value": 7.0}}, "turn": 1})
        assert state.status("size") == STATUS_UNKNOWN
        assert state.value("size") is None
