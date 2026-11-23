"""M5 - the D-32 completeness check, as a permanent test.

It walks every FastAPI route, calls each one, and checks the FACT
numbers in each response against the permitted set that belongs to that
surface. This is the check that proves D-32 is closed rather than
"mostly closed": every serving surface is accounted for, and the
accounting is explicit.

**What counts as a factual number.** A number is a FACT when it asserts
something about the market that the application owns. The following are
NOT facts and are excluded from the check - each exclusion is explicit,
not a blanket skip:

  * the guard report's own counters - they describe the check, not the
    market;
  * the `id` of a hand-checked case - a sequence number;
  * the `note` / `question` prose of a hand-checked case - the author's
    commentary, not an assertion the application makes;
  * the `filters` of a hand-checked case - the QUERY, whose numbers are
    the customer's own request;
  * the `size_marla` of a market row - the cell being described, i.e.
    the customer's own request;
  * a lead record's own fields - CUSTOMER data.

Everything else - every price, every sample size, every observation
count, every date, every coverage figure - IS a fact and IS checked.
"""

import json
import os
import sys

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from market import fact_guard  # noqa: E402
from market.fact_validator import extract_numbers  # noqa: E402

GUARD_KEYS = ("guard", "traceability")

NON_FACT_KEYS = (
    "id", "note", "question", "filters", "size_marla", "created_at",
    "updated_at", "last_message_time", "audit_id", "lead_id",
    # M8: the ranking score and its components are the application's own
    # derived ordering - a number in [0, 1] that says how well a cell
    # matched, not a market figure. It is skipped for the same reason
    # ``size_marla`` is: it is not a claim about the market. The price
    # and the counts of the same cell ARE checked.
    "score", "score_components",
)


def _numbers_in(value, skip=()):
    out = set()
    if isinstance(value, bool) or value is None:
        return out
    if isinstance(value, (int, float)):
        out.add(float(value))
        return out
    if isinstance(value, str):
        for _raw, number in extract_numbers(value):
            out.add(number)
        return out
    if isinstance(value, dict):
        for key, item in value.items():
            if key in skip:
                continue
            out |= _numbers_in(item, skip)
        return out
    if isinstance(value, (list, tuple)):
        for item in value:
            out |= _numbers_in(item, skip)
        return out
    return out


def _fact_numbers(payload):
    return _numbers_in(payload, GUARD_KEYS + NON_FACT_KEYS)


def _market_prices():
    prices = set()
    for block in ("A", "B", "C"):
        for size in (5, 7, 10, 14, 20, 40):
            cell = fact_guard.approved_cell(block=block, size_marla=size)
            for key in ("price_min_pkr", "price_median_pkr", "price_max_pkr"):
                if cell.get(key):
                    prices.add(float(cell[key]))
    return prices


# ---------------------------------------------------------------------------
# the market surfaces
# ---------------------------------------------------------------------------


def test_the_message_surface_serves_only_traceable_facts():
    import app.server as server

    payload = server.handle_message_endpoint(
        "What is the price of a 7 marla plot in Block C?"
    )
    filters = (payload.get("market_facts") or {}).get("filters") or {}
    allowed = fact_guard.allowed_numbers_for(
        block=filters.get("block"), size_marla=filters.get("size_marla")
    )

    untraceable = _fact_numbers(payload) - allowed

    assert untraceable == set(), (
        "/api/message served an untraceable fact number: %r" % sorted(untraceable)
    )
    assert _fact_numbers(payload), "the check proved nothing - no facts were found"


def test_the_evidence_surface_serves_only_traceable_facts():
    """M7: the evidence route serves the matching listings, so it is a
    guarded surface like every other numeric one.

    The permitted set is derived at the ROW level, because each listing
    carries its own price and date - but it is still re-derived from
    the read-only approved master, so a figure the master does not
    hold is still caught.
    """
    import app.server as server
    from market import evidence

    payload = server.evidence_endpoint(block="C", size_marla=7)

    rows = evidence.matching_rows(block="C", size_marla=7)
    allowed = fact_guard.allowed_numbers_for(
        block="C", size_marla=7, rows=rows
    )

    untraceable = _fact_numbers(payload) - allowed

    assert untraceable == set(), (
        "/api/evidence served an untraceable fact number: %r"
        % sorted(untraceable)
    )
    assert _fact_numbers(payload), "the check proved nothing"


def test_the_recommendations_surface_serves_only_traceable_facts():
    """M8: the recommendations route serves the ranked, verified
    alternatives, so it is a guarded surface like every other numeric
    one.

    Each option is a cell of its own, so the permitted set covers each
    option cell's approved facts as well as the row-level numbers of
    the listings it carries. The permitted values are re-derived from
    the read-only approved master, so a figure the master does not
    hold is still caught.
    """
    import app.server as server
    from market import evidence

    payload = server.recommendations_endpoint(block="C", size_marla=10)

    rows = []
    for option in payload.get("options") or []:
        rows.extend(evidence.matching_rows(
            block=option.get("block"),
            size_marla=option.get("size_marla"),
        ))

    allowed = fact_guard.allowed_numbers_for(
        block="C", size_marla=10, rows=rows
    )
    for option in payload.get("options") or []:
        allowed |= fact_guard.allowed_numbers_for(
            block=option.get("block"),
            size_marla=option.get("size_marla"),
        )

    untraceable = _fact_numbers(payload) - allowed

    assert untraceable == set(), (
        "/api/recommendations served an untraceable fact number: %r"
        % sorted(untraceable)
    )
    assert _fact_numbers(payload), "the check proved nothing"


def test_the_next_best_action_surface_serves_only_traceable_facts():
    """M9: the next-best-action route serves the decision, and the
    decision names only cells the application already verified.

    The permitted numbers are re-derived from the read-only approved
    master, for the requested cell and for every cell the decision
    names, so a figure the master does not hold is still caught.
    """
    import app.server as server
    from market import evidence

    payload = server.next_best_action_endpoint(block="C", size_marla=10)

    rows = []
    for option in payload.get("options") or []:
        rows.extend(evidence.matching_rows(
            block=option.get("block"),
            size_marla=option.get("size_marla"),
        ))

    allowed = fact_guard.allowed_numbers_for(
        block="C", size_marla=10, rows=rows
    )
    for option in payload.get("options") or []:
        allowed |= fact_guard.allowed_numbers_for(
            block=option.get("block"),
            size_marla=option.get("size_marla"),
        )

    untraceable = _fact_numbers(payload) - allowed

    assert untraceable == set(), (
        "/api/next-best-action served an untraceable fact number: %r"
        % sorted(untraceable)
    )
    assert _fact_numbers(payload), "the check proved nothing"


def test_the_lookup_surface_serves_only_traceable_facts():
    import app.server as server

    payload = server.lookup_endpoint(block="C", size_marla=7)
    allowed = fact_guard.allowed_numbers_for(block="C", size_marla=7)

    untraceable = _fact_numbers(payload) - allowed

    assert untraceable == set(), (
        "/api/lookup served an untraceable fact number: %r" % sorted(untraceable)
    )
    assert _fact_numbers(payload)


def test_the_market_surface_serves_only_traceable_facts():
    import app.server as server

    payload = server.get_market_stats()
    allowed = set()
    for block in payload["active_blocks"]:
        for size in (5, 7, 10, 14, 20, 40):
            allowed |= fact_guard.allowed_numbers_for(block=block, size_marla=size)

    untraceable = _fact_numbers(payload) - allowed

    assert untraceable == set(), (
        "/api/market served an untraceable fact number: %r" % sorted(untraceable)
    )
    assert _fact_numbers(payload)


def test_the_questions_surface_serves_only_traceable_facts():
    import app.server as server

    payload = server.questions_endpoint()
    allowed = set()
    for case in payload["questions"]:
        filters = case.get("filters") or {}
        allowed |= fact_guard.allowed_numbers_for(
            block=filters.get("block"),
            size_marla=filters.get("size_marla"),
            corner=filters.get("corner"),
            sun_facing=filters.get("sun_facing"),
            ndc_open=filters.get("ndc_open"),
        )

    untraceable = _fact_numbers(payload) - allowed

    assert untraceable == set(), (
        "/api/questions served an untraceable fact number: %r" % sorted(untraceable)
    )
    assert _fact_numbers(payload)


# ---------------------------------------------------------------------------
# the operator surfaces
# ---------------------------------------------------------------------------


def test_every_audited_record_either_verifies_or_is_marked_uncheckable():
    """A record must never be presented as verified when it could not be
    checked."""
    import app.server as server

    rows = server.get_audit()

    for row in rows:
        assert row.get("verified") in (True, False, None), row
        if row.get("verified") is False:
            assert row["guard"]["ok"] is False
        if row.get("verified") is None:
            assert "cannot be checked" in row["guard"]["reason"]


def test_no_lead_record_carries_a_market_price():
    """A lead record is CUSTOMER data. It must not carry a market price
    figure, because a lead row carries no market answer."""
    import app.server as server

    leads = server.get_leads()
    prices = _market_prices()

    leak = sorted(_numbers_in(leads) & prices)

    assert leak == [], "a lead record leaked a market price: %r" % leak


def test_a_single_lead_record_carries_no_market_price():
    import app.server as server

    leads = server.get_leads()
    if not leads:
        pytest.skip("no lead rows in the demo database")

    one = server.get_lead(leads[0]["lead_id"])
    prices = _market_prices()

    leak = sorted(_numbers_in(one) & prices)

    assert leak == [], "a lead record leaked a market price: %r" % leak


# ---------------------------------------------------------------------------
# the completeness claim itself
# ---------------------------------------------------------------------------


def test_every_serving_route_is_accounted_for():
    """Every route in the console either serves no fact number, or is
    covered by a check in this module.

    A new route that serves market facts and is not listed here would be
    an unguarded surface - so the list is asserted against the live
    route table.
    """
    import app.server as server

    checked = {
        "/api/message",
        "/api/lookup",
        "/api/market",
        "/api/questions",
        "/api/audit",
        "/api/leads",
        "/api/leads/{lead_id}",
        # M7: the evidence route serves the matching listings - real
        # market facts, so it is a guarded surface and is checked below
        # by `test_the_evidence_surface_serves_only_traceable_facts`.
        "/api/evidence",
        # M8: the recommendations route serves the ranked, verified
        # alternatives - real market facts, so it is a guarded surface
        # and is checked below by
        # `test_the_recommendations_surface_serves_only_traceable_facts`.
        "/api/recommendations",
        # M11: the conversation route serves the application's own
        # validated reply, so it is a guarded surface. It is checked
        # by `test_the_conversation_endpoint_serves_only_traceable_facts`
        # in tests/test_m11_operator_endpoints.py.
        "/api/conversation",
    }

    live = set()
    for route in server.app.routes:
        path = getattr(route, "path", None)
        if path and path.startswith("/api/"):
            live.add(path)

    # The lead mutation routes take a lead id and echo an operator's
    # edited text; they serve no market fact.
    mutations = {
        "/api/leads/{lead_id}/approve",
        "/api/leads/{lead_id}/reject",
        "/api/leads/{lead_id}/state",
        # M7: the review routes record an operator's decision and read
        # it back. They carry the evidence REFERENCES (opaque, digit-free
        # identifiers) and the reply text, never a market figure.
        "/api/leads/{lead_id}/review",
        "/api/leads/{lead_id}/reviews",
        # M9: the next-best-action route serves the DECISION - the
        # requirements the dealer stated, the verified cells those
        # requirements narrow to, and the action the application chose.
        # It serves no price of its own, so it belongs with the routes
        # that carry no market fact. It is still checked, by
        # `test_the_next_best_action_surface_serves_only_traceable_facts`
        # below - it is not left unchecked.
        "/api/next-best-action",
        # M11: the conversation state route reads the qualification
        # state, the take-over route records that a human took over,
        # and the unmet-demand route serves the demand SHAPES (a size,
        # a block and a budget band). None of them serves a market
        # figure, so they belong with the routes that carry no market
        # fact. They are still checked, in
        # tests/test_m11_operator_endpoints.py - not left unchecked.
        "/api/conversation/{session_id}",
        "/api/conversation/{session_id}/take-over",
        "/api/unmet-demand",
        # M12.2: the persistence routes. The list and the transcript
        # REPLAY records of turns that already ran - the transcript
        # serves the replies the pipeline already validated and already
        # served for those turns, and the list carries the dealer's own
        # words as a preview plus flags. The draft-action route records
        # an operator's decision and serves no fact at all. The
        # activity route serves counts, action names, session ids and
        # times - no market figure, no message text. They are checked
        # in tests/test_m12_2_persistence.py - not left unchecked.
        "/api/conversations",
        "/api/conversation/{session_id}/transcript",
        "/api/conversation/{session_id}/draft-action",
        "/api/operator-activity",
        # Lead pipeline (2026-10-24 upgrade): the pipeline list and
        # detail REPLAY recorded conversation state as lead views with
        # transparent arithmetic (stage, temperature, score, routing) -
        # they serve no new market figure. The stage / follow-up /
        # note routes record operator decisions only. The follow-ups
        # queue serves the same lead views plus a deterministic DRAFT
        # that quotes no price, availability or private data (checked
        # in tests/test_lead_pipeline.py). None is left unchecked.
        "/api/leads-pipeline",
        "/api/leads-pipeline/{lead_id}",
        "/api/leads-pipeline/{lead_id}/stage",
        "/api/leads-pipeline/{lead_id}/follow-up",
        "/api/leads-pipeline/{lead_id}/note",
        "/api/follow-ups",
        # Pilot reporting (2026-10-24): the source and feedback routes
        # record operator decisions against fixed vocabularies; the
        # weekly-report routes aggregate recorded data into counts and
        # shapes only (checked in tests/test_pilot_feedback_reporting.py,
        # including that no private text can appear in a report).
        "/api/leads-pipeline/{lead_id}/source",
        "/api/pilot-feedback/{lead_id}",
        "/api/weekly-report",
        "/api/weekly-report/markdown",
        "/api/weekly-report/csv",
        # Pilot features (2026-10-25): the founder pipeline view serves
        # the qualification ARITHMETIC over the dealer's own stated
        # requirements (score, temperature, stage, known/missing) - the
        # same shapes the conversation-state route serves, no market
        # figure. The site-visit routes serve the founder-owned calendar
        # (dates, times, statuses) and record the founder's approval
        # decision; a request carries only the dealer's stated
        # requirements. None serves a market figure. They are checked
        # in tests/test_pilot_features.py - not left unchecked.
        "/api/lead-pipeline/founder-view",
        "/api/site-visit/requests",
        "/api/site-visit/approve",
        # Stage 1: the versioned inventory workspace. These routes carry
        # NO figure from the approved master: upload/approve/activate/
        # rollback move operator-supplied files between the workspace and
        # the active pointer, `current` serves the resolved source's
        # fingerprint/row-count/date-range, `versions` lists manifests,
        # and the template serves a unit-labelled empty form. `preview`
        # returns rows of an UPLOADED, not-yet-active candidate - the
        # guard cannot verify them against the master by definition, and
        # they never reach a customer reply while the candidate is not
        # active. Checked in tests/test_inventory_workspace.py.
        "/api/inventory/upload",
        "/api/inventory/preview/{version_id}",
        "/api/inventory/approve",
        "/api/inventory/activate",
        "/api/inventory/rollback",
        "/api/inventory/current",
        "/api/inventory/versions",
        "/api/inventory/template.csv",
        # Showcase readiness (2026-11-21): the system-status route serves
        # INFRASTRUCTURE truth only - reachability, the desk's own store
        # row counts, the inventory serving MODE (never the master's
        # figures), and the recorded test evidence. No market figure, no
        # customer text. Checked in tests/test_system_status.py - not
        # left unchecked.
        "/api/system-status",
    }
    assert live - checked == mutations, (
        "a serving route is not covered by a guard: %r" % sorted(live - checked - mutations)
    )
