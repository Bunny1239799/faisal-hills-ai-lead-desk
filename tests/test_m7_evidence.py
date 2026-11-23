"""M7 - the matching-listings / evidence / operator workflow layer.

M7 moves the product from "here are aggregated facts" to "here are the
**verified listings that support those facts**", and gives the operator
a review workflow that is bound to that evidence.

The properties this module proves:

  1. the evidence is derived from the approved master, and it agrees
     with the answer it explains (one authority, no drift);
  2. the **scope rule is the lookup's rule** - a parked block is
     refused before any row is counted;
  3. the **plot identifier is redacted by default** and served only on
     an explicit authorisation, with the mode recorded;
  4. **no uncontrolled dealer content leaves the layer** - no raw chat,
     no sender, no note, no raw size string;
  5. a **thin cell's evidence carries no price**, exactly like the
     customer-facing path;
  6. the operator review is **auditable** - it records the evidence it
     was made against, a digest of that evidence, the fact identifiers,
     and whether the reply was edited;
  7. a **stale evidence** review is recorded as stale, not as a clean
     approval.

Run with:  python -m pytest tests/test_m7_evidence.py -q
"""

import io
import json
import os
import sys

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from market import evidence  # noqa: E402
from market import price_lookup  # noqa: E402
from market import review  # noqa: E402
from market.fh_query import load_inventory  # noqa: E402

# Every cell in the active scope, measured against the approved master.
CELLS = [
    ("A", 5), ("A", 7), ("A", 10), ("A", 14), ("A", 20), ("A", 40),
    ("B", 5), ("B", 7), ("B", 10), ("B", 14), ("B", 20),
    ("C", 5), ("C", 7), ("C", 10), ("C", 20),
]

THIN = [("A", 14), ("B", 7), ("C", 10)]


def _strings(value, path=""):
    """Every string in a payload, with its path."""
    out = []
    if isinstance(value, dict):
        for key, item in value.items():
            out += _strings(item, "%s.%s" % (path, key))
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            out += _strings(item, "%s[%d]" % (path, index))
    elif isinstance(value, str):
        out.append((path, value))
    return out


def _audit_db():
    """An in-memory database with the audit_log table the review uses.

    The review writes to the SAME audit trail the pipeline writes to -
    that is the point of an auditable review - so the table is created
    from the project's own schema rather than being re-declared here.
    """
    import sqlite3

    from data.db import init_db

    conn = init_db(":memory:")
    return conn


@pytest.fixture(scope="module")
def master_sensitive_values():
    """The sensitive VALUES the approved master holds, in scope.

    These are the strings that must never appear in an evidence
    payload: a dealer's free-text note, a dealer organisation's name,
    a raw dimension string, and a plot identifier.

    The source chats are read with the query engine's OWN parser
    (``market.fh_query._source_values``), so the test sees the same
    values the master actually holds - including when the master was
    derived from the in-repo CSV, where the chats arrive as one
    bracketed string rather than a list.
    """
    from market.fh_query import _source_values

    rows = [
        row for row in load_inventory()
        if price_lookup.canonical_block(row.get("block")) in ("A", "B", "C")
    ]
    notes = {str(r["notes"]) for r in rows if r.get("notes")}
    chats = set()
    for r in rows:
        chats.update(_source_values(r.get("source_chats")))
    size_raw = {str(r["size_raw"]) for r in rows if r.get("size_raw")}
    plot_numbers = {str(r["plot_number"]) for r in rows if r.get("plot_number")}
    return {
        "notes": notes,
        "chats": chats,
        "size_raw": size_raw,
        "plot_numbers": plot_numbers,
    }


# ---------------------------------------------------------------------------
# 1. the evidence agrees with the answer it explains
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("block,size_marla", CELLS)
def test_m7_the_evidence_counts_agree_with_the_lookup(block, size_marla):
    """One authority: the evidence layer and the lookup cannot disagree."""
    lookup = price_lookup.lookup_price(block=block, size_marla=size_marla)
    ev = evidence.evidence_for_cell(block=block, size_marla=size_marla)

    assert ev["summary"]["matched_plots"] == lookup["summary"]["matched_plots"]
    assert ev["summary"]["observation_count"] == \
        lookup["summary"]["observation_count"]
    assert ev["answerable"] == lookup["answerable"]
    assert len(ev["listings"]) == lookup["summary"]["matched_plots"]


@pytest.mark.parametrize("block,size_marla", CELLS)
def test_m7_the_evidence_prices_agree_with_the_lookup(block, size_marla):
    lookup = price_lookup.lookup_price(block=block, size_marla=size_marla)
    ev = evidence.evidence_for_cell(block=block, size_marla=size_marla)

    assert ev["summary"]["price_min_pkr"] == lookup["summary"]["price_min_pkr"]
    assert ev["summary"]["price_median_pkr"] == \
        lookup["summary"]["price_median_pkr"]
    assert ev["summary"]["price_max_pkr"] == lookup["summary"]["price_max_pkr"]


def test_m7_the_evidence_carries_its_provenance():
    ev = evidence.evidence_for_cell(block="C", size_marla=7)
    assert ev["evidence_source"] == "FaisalHills verified partial master (read-only)"
    assert ev["price_basis"] == "dealer asking prices"
    assert ev["is_sold_price"] is False


# ---------------------------------------------------------------------------
# 2. the scope rule is the lookup's rule
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("block", ["D", "E", "Z", "Executive", "EXEC"])
def test_m7_a_parked_or_unknown_block_is_refused_before_any_row_is_counted(block):
    with pytest.raises(evidence.EvidenceError):
        evidence.build_listing_evidence(block=block, size_marla=7)


def test_m7_a_refused_block_leaks_no_listing():
    try:
        evidence.build_listing_evidence(block="D", size_marla=7)
        assert False, "the parked block was not refused"
    except evidence.EvidenceError:
        pass


def test_m7_the_evidence_reads_the_single_scope_configuration():
    """The scope lives in one place (D-26)."""
    policies = price_lookup.load_policies()
    ev = evidence.build_listing_evidence(block="A", size_marla=5)
    assert ev["answerable"] is True
    assert policies["active_blocks"] == ["A", "B", "C"]


# ---------------------------------------------------------------------------
# 3. the plot identifier is redacted by default
# ---------------------------------------------------------------------------


def test_m7_the_plot_number_is_redacted_by_default():
    ev = evidence.evidence_for_cell(block="C", size_marla=7)
    assert ev["plot_number_mode"] == "redacted"
    for listing in ev["listings"]:
        assert listing["plot_number"] is None
        assert listing["plot_number_redacted"] is True
        assert listing["listing_ref"]


def test_m7_the_plot_number_is_served_on_explicit_authorisation():
    ev = evidence.evidence_for_cell(
        block="C", size_marla=7, include_plot_number=True
    )
    assert ev["plot_number_mode"] == "identified"
    served = [l for l in ev["listings"] if l.get("plot_number")]
    assert served
    for listing in ev["listings"]:
        assert listing["plot_number_redacted"] is False


def test_m7_the_listing_ref_is_stable_and_unique():
    first = evidence.build_listing_evidence(block="C", size_marla=7)
    second = evidence.build_listing_evidence(block="C", size_marla=7)
    assert [l["listing_ref"] for l in first["listings"]] == \
        [l["listing_ref"] for l in second["listings"]]

    refs = [l["listing_ref"] for l in first["listings"]]
    assert len(refs) == len(set(refs)), "listing_refs must be unique"


def test_m7_the_listing_ref_carries_no_digits():
    """An identifier must not look like a market figure.

    A digit inside a reference would be read by the numeric guard as
    an untraceable number on a serving surface, and by an operator as a
    price. The reference is therefore rendered in letters only.
    """
    ev = evidence.build_listing_evidence(block="C", size_marla=7)
    for listing in ev["listings"]:
        ref = listing["listing_ref"]
        assert not any(ch.isdigit() for ch in ref), ref


def test_m7_the_listing_ref_is_not_the_plot_number():
    """The reference must not be a disguised copy of the identifier."""
    ev = evidence.build_listing_evidence(
        block="C", size_marla=7, include_plot_number=True
    )
    for listing in ev["listings"]:
        assert listing["listing_ref"] != listing["plot_number"]


def test_m7_the_listing_ref_is_the_same_in_both_modes():
    """The reference is a property of the ROW, not of the mode."""
    redacted = evidence.build_listing_evidence(block="C", size_marla=7)
    identified = evidence.build_listing_evidence(
        block="C", size_marla=7, include_plot_number=True
    )
    assert [l["listing_ref"] for l in redacted["listings"]] == \
        [l["listing_ref"] for l in identified["listings"]]


def test_m7_the_served_plot_number_is_the_real_one():
    """In the identified mode the identifier must be correct, not a
    placeholder - an operator would act on it."""
    ev = evidence.build_listing_evidence(
        block="C", size_marla=7, include_plot_number=True
    )
    master = load_inventory()
    master_numbers = {
        (str(r.get("block")).strip().upper(), str(r.get("plot_number")))
        for r in master
    }
    for listing in ev["listings"]:
        key = (listing["block"], str(listing["plot_number"]))
        assert key in master_numbers, key


# ---------------------------------------------------------------------------
# 4. no uncontrolled dealer content leaves the layer
# ---------------------------------------------------------------------------


def test_m7_no_note_from_the_master_reaches_the_evidence(master_sensitive_values):
    for block, size_marla in CELLS:
        ev = evidence.evidence_for_cell(block=block, size_marla=size_marla)
        for path, value in _strings(ev):
            if len(value) > 6 and value in master_sensitive_values["notes"]:
                pytest.fail("a master note reached the evidence: %s -> %r"
                            % (path, value))


def test_m7_no_dealer_name_reaches_the_evidence(master_sensitive_values):
    """No dealer organisation name may reach the evidence.

    The check is an EXACT match against every string in the payload. A
    substring test would be wrong here: the CI-derived master stores
    the source chats as one bracketed string, and a dealer name can
    then be a substring of it - and a two-letter block code can be a
    substring of a dealer name. Only an exact match identifies a value
    that was actually served.
    """
    for block, size_marla in CELLS:
        ev = evidence.evidence_for_cell(block=block, size_marla=size_marla)
        for path, value in _strings(ev):
            if value in master_sensitive_values["chats"]:
                pytest.fail("a dealer name reached the evidence: %s -> %r"
                            % (path, value))


def test_m7_no_dealer_name_reaches_the_evidence_in_any_substring_form(
    master_sensitive_values,
):
    """A dealer name must not reach the evidence inside a LONGER
    string either.

    The CI-derived master stores the source chats as one bracketed
    string ("['AB YOU Properties (Pvt.) Limited']"), so a leak could
    hide inside a longer value. This test looks for each dealer name
    inside every served string, with a length floor that excludes the
    one-character artefacts a block code would produce.
    """
    for block, size_marla in CELLS:
        ev = evidence.evidence_for_cell(block=block, size_marla=size_marla)
        for path, value in _strings(ev):
            for name in master_sensitive_values["chats"]:
                if len(name) < 8:
                    # A short name could coincide with a block code or a
                    # feature word. It is checked by the exact-match test
                    # above; here only a real leak matters.
                    continue
                if name in value:
                    pytest.fail(
                        "a dealer name reached the evidence: %s -> %r"
                        % (path, value)
                    )


def test_m7_no_raw_size_string_reaches_the_evidence(master_sensitive_values):
    for block, size_marla in CELLS:
        ev = evidence.evidence_for_cell(block=block, size_marla=size_marla)
        for path, value in _strings(ev):
            if value in master_sensitive_values["size_raw"]:
                pytest.fail("a raw size string reached the evidence: %s -> %r"
                            % (path, value))


def test_m7_no_plot_number_reaches_the_redacted_evidence(
    master_sensitive_values,
):
    for block, size_marla in CELLS:
        ev = evidence.evidence_for_cell(block=block, size_marla=size_marla)
        for path, value in _strings(ev):
            if value in master_sensitive_values["plot_numbers"]:
                pytest.fail("a plot number reached the redacted evidence: "
                            "%s -> %r" % (path, value))


def test_m7_the_evidence_has_no_raw_text_sender_or_notes_field():
    """The layer is built field by field, so the field itself is absent."""
    ev = evidence.evidence_for_cell(block="C", size_marla=7)
    for listing in ev["listings"]:
        assert "raw_text" not in listing
        assert "sender" not in listing
        assert "notes" not in listing
        assert "source_chats" not in listing
        assert "size_raw" not in listing


def test_m7_the_excluded_fields_are_declared():
    """The layer says what it refuses to serve, and why."""
    ev = evidence.evidence_for_cell(block="C", size_marla=7)
    assert set(ev["excluded_fields"]) == set(evidence.EXCLUDED_FIELDS)
    for field in ("source_chats", "notes", "size_raw", "plot_number"):
        assert field in ev["excluded_fields"]


def test_m7_the_whitelist_covers_only_real_master_fields():
    """The whitelist names real master fields - a typo would silently
    drop a field."""
    master_fields = set(load_inventory()[0].keys())
    for field in evidence.LISTING_FIELDS:
        assert field in master_fields, field


# ---------------------------------------------------------------------------
# 5. a thin cell's evidence carries no price
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("block,size_marla", THIN)
def test_m7_a_thin_cell_serves_no_price(block, size_marla):
    """The operator panel must not become a way to quote a figure the
    customer path withholds."""
    ev = evidence.evidence_for_cell(block=block, size_marla=size_marla)
    assert ev["answerable"] is False
    assert ev["summary"]["price_min_pkr"] is None
    assert ev["summary"]["price_median_pkr"] is None
    assert ev["summary"]["price_max_pkr"] is None
    for listing in ev["listings"]:
        assert listing["price_min_pkr"] is None
        assert listing["price_median_pkr"] is None
        assert listing["price_max_pkr"] is None
        assert listing["price_latest_pkr"] is None


def test_m7_a_thin_cell_still_serves_its_rows():
    """The operator must be able to see WHY the product refused."""
    ev = evidence.evidence_for_cell(block="B", size_marla=7)
    assert len(ev["listings"]) == 2
    assert ev["summary"]["matched_plots"] == 2
    assert ev["summary"]["priced_plots"] == 2


def test_m7_the_raw_evidence_builder_can_serve_a_thin_cells_prices():
    """The build function is unfiltered by design; the SAFE entry point
    is `evidence_for_cell`. The distinction is deliberate and tested."""
    ev = evidence.build_listing_evidence(block="B", size_marla=7)
    assert ev["answerable"] is False
    # The prices are present in the raw build ...
    assert ev["summary"]["price_median_pkr"] is not None
    # ... and removed by the safe entry point.
    safe = evidence.evidence_for_cell(block="B", size_marla=7)
    assert safe["summary"]["price_median_pkr"] is None


# ---------------------------------------------------------------------------
# 6. the matching reason
# ---------------------------------------------------------------------------


def test_m7_the_matching_reason_names_the_filters_that_matched():
    ev = evidence.evidence_for_cell(block="C", size_marla=7)
    for listing in ev["listings"]:
        reason = " ".join(listing["matching_reason"])
        assert "block C" in reason
        assert "7 marla" in reason


def test_m7_the_matching_reason_names_a_feature_that_matched():
    ev = evidence.evidence_for_cell(block="C", size_marla=7, corner=True)
    cornered = [l for l in ev["listings"] if l.get("corner") is True]
    assert cornered
    for listing in cornered:
        assert "corner plot" in listing["matching_reason"]


def test_m7_the_feature_values_are_real_booleans():
    """A feature must be served as a boolean, whatever the master
    holds.

    The approved JSONL master holds real booleans; the in-repo CSV
    (which CI derives the master from) holds the STRING "True". The
    evidence layer normalises both the same way, so the two masters
    produce the same evidence.
    """
    ev = evidence.evidence_for_cell(block="C", size_marla=7, corner=True)
    for listing in ev["listings"]:
        for field in ("corner", "sun_facing", "ndc_open"):
            value = listing[field]
            assert value is None or isinstance(value, bool), (
                field, value, type(value).__name__
            )


def test_m7_the_matching_reason_carries_no_number_it_cannot_support():
    """The reason is derived from the query and the row, so it can only
    name what actually matched."""
    ev = evidence.evidence_for_cell(block="C", size_marla=7)
    for listing in ev["listings"]:
        for part in listing["matching_reason"]:
            assert listing["block"] in part or "marla" in part \
                or "plot" in part or "facing" in part or "NDC" in part \
                or "approved master" in part, part


# ---------------------------------------------------------------------------
# 7. the limit
# ---------------------------------------------------------------------------


def test_m7_a_limited_view_does_not_look_like_the_whole_cell():
    ev = evidence.build_listing_evidence(block="C", size_marla=7, limit=3)
    assert ev["returned"] == 3
    assert ev["total_matched"] == 21
    assert ev["limited"] is True
    # The counts always describe the whole cell.
    assert ev["summary"]["matched_plots"] == 21


# ---------------------------------------------------------------------------
# The operator review
# ---------------------------------------------------------------------------


def test_m7_the_review_records_the_evidence_it_was_made_against():
    conn = _audit_db()
    try:
        ev = evidence.build_listing_evidence(block="C", size_marla=7)
        refs = [l["listing_ref"] for l in ev["listings"]]

        recorded = review.record_review(
            conn,
            lead_id="lead-1",
            decision="approved",
            reply_text="Based on 21 matching listings ...",
            evidence={"listing_refs": refs},
            fact_ids=["market:C/7:price_median_pkr"],
        )

        assert recorded["recorded"] is True
        assert recorded["decision"] == "approved"
        assert recorded["outcome"] == "approved"
        assert recorded["listing_count"] == len(refs)
        assert recorded["evidence_digest"] == review.evidence_digest(refs)

        row = conn.execute(
            "SELECT step, decision_payload, fact_ids_used FROM audit_log"
        ).fetchone()
        assert row["step"] == "evidence_approve"

        payload = json.loads(row["decision_payload"])
        assert payload["listing_refs"] == refs
        assert payload["evidence_digest"] == recorded["evidence_digest"]
        assert payload["action"] == "approved"
        assert payload["edited"] is False
        assert json.loads(row["fact_ids_used"]) == \
            ["market:C/7:price_median_pkr"]
    finally:
        conn.close()


def test_m7_the_review_does_not_store_the_plot_identifier():
    """The audit trail must not become a side channel for the
    identifier the evidence layer redacts."""
    conn = _audit_db()
    try:
        ev = evidence.build_listing_evidence(block="C", size_marla=7)
        refs = [l["listing_ref"] for l in ev["listings"]]
        review.record_review(
            conn, lead_id="lead-2", decision="approved",
            reply_text="ok", evidence={"listing_refs": refs},
        )
        row = conn.execute(
            "SELECT decision_payload FROM audit_log"
        ).fetchone()
        payload = json.loads(row["decision_payload"])
        for ref in payload["listing_refs"]:
            assert ref.startswith("L")
            # The reference carries NO digits: an identifier must not
            # look like a market figure.
            assert not any(ch.isdigit() for ch in ref), ref
    finally:
        conn.close()


def test_m7_a_rejection_records_the_reason():
    conn = _audit_db()
    try:
        recorded = review.record_review(
            conn, lead_id="lead-3", decision="rejected",
            reason="the price is stale, please re-check the master",
            evidence={"listing_refs": ["L-abc123"]},
        )
        assert recorded["outcome"] == "rejected"
        row = conn.execute(
            "SELECT step, decision_payload FROM audit_log"
        ).fetchone()
        assert row["step"] == "evidence_reject"
        payload = json.loads(row["decision_payload"])
        assert payload["reason"] == \
            "the price is stale, please re-check the master"
    finally:
        conn.close()


def test_m7_an_edited_reply_is_recorded_as_edited():
    conn = _audit_db()
    try:
        recorded = review.record_review(
            conn, lead_id="lead-4", decision="approved",
            reply_text="the operator's edited text",
            evidence={"listing_refs": ["L-abc123"]},
            edited=True,
        )
        assert recorded["edited"] is True
        row = conn.execute(
            "SELECT output_text, decision_payload FROM audit_log"
        ).fetchone()
        assert row["output_text"] == "the operator's edited text"
        assert json.loads(row["decision_payload"])["edited"] is True
    finally:
        conn.close()


def test_m7_an_unknown_decision_is_refused():
    conn = _audit_db()
    try:
        with pytest.raises(review.ReviewError):
            review.record_review(
                conn, lead_id="lead-5", decision="maybe",
                evidence={"listing_refs": []},
            )
    finally:
        conn.close()


def test_m7_a_stale_evidence_review_is_recorded_as_stale():
    """If the evidence moved under the operator's feet, the review is
    not a clean approval."""
    conn = _audit_db()
    try:
        recorded = review.record_review(
            conn, lead_id="lead-6", decision="approved",
            reply_text="ok",
            evidence={
                "listing_refs": ["L-abc123"],
                "evidence_digest": "deadbeefdeadbeef",
            },
        )
        assert recorded["outcome"] == "stale_evidence"
    finally:
        conn.close()


def test_m7_the_evidence_digest_is_order_independent():
    refs = ["L-b", "L-a", "L-c"]
    assert review.evidence_digest(refs) == review.evidence_digest(
        ["L-a", "L-b", "L-c"]
    )
    assert review.evidence_digest(refs) != review.evidence_digest(
        ["L-a", "L-b"]
    )


def test_m7_the_review_history_is_ordered_and_parsed():
    conn = _audit_db()
    try:
        review.record_review(
            conn, lead_id="lead-7", decision="rejected", reason="first",
            evidence={"listing_refs": ["L-a"]},
        )
        review.record_review(
            conn, lead_id="lead-7", decision="approved",
            evidence={"listing_refs": ["L-a"]},
        )
        history = review.review_history(conn, "lead-7")
        assert len(history) == 2
        assert history[0]["decision_payload"]["reason"] == "first"
        assert history[1]["decision_payload"]["action"] == "approved"
        assert history[0]["audit_id"] < history[1]["audit_id"]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# The API surface
# ---------------------------------------------------------------------------


def test_m7_the_evidence_endpoint_serves_the_redacted_form_by_default():
    import app.server as server

    payload = server.evidence_endpoint(block="C", size_marla=7)
    assert payload["plot_number_mode"] == "redacted"
    assert payload["answerable"] is True
    assert len(payload["listings"]) == 21
    for listing in payload["listings"]:
        assert listing["plot_number"] is None


def test_m7_the_evidence_endpoint_serves_the_identified_form_on_request():
    import app.server as server

    payload = server.evidence_endpoint(
        block="C", size_marla=7, include_plot_number=True
    )
    assert payload["plot_number_mode"] == "identified"
    assert any(l.get("plot_number") for l in payload["listings"])


def test_m7_the_evidence_endpoint_refuses_a_parked_block():
    import app.server as server
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as excinfo:
        server.evidence_endpoint(block="D", size_marla=7)
    assert excinfo.value.status_code == 400


def test_m7_the_evidence_endpoint_carries_a_guard_report():
    import app.server as server

    payload = server.evidence_endpoint(block="C", size_marla=7)
    assert payload["guard"]["ok"] is True


def test_m7_the_review_endpoint_records_a_decision():
    import app.server as server
    from data.db import get_db_connection

    conn = get_db_connection()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO leads (lead_id, status) VALUES (?, ?)",
            ("m7-lead", "new"),
        )
        conn.commit()
    finally:
        conn.close()

    recorded = server.review_lead(
        lead_id="m7-lead",
        decision="approved",
        edited_text="the reply",
        listing_refs=["L-abc123"],
        fact_ids=["market:C/7:price_median_pkr"],
    )
    assert recorded["recorded"] is True
    assert recorded["decision"] == "approved"
    assert recorded["listing_count"] == 1

    history = server.review_history_endpoint(lead_id="m7-lead")
    assert len(history["reviews"]) == 1
    assert history["reviews"][0]["decision_payload"]["action"] == "approved"


def test_m7_the_review_endpoint_refuses_an_unknown_decision():
    import app.server as server
    from fastapi import HTTPException
    from data.db import get_db_connection

    conn = get_db_connection()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO leads (lead_id, status) VALUES (?, ?)",
            ("m7-lead-2", "new"),
        )
        conn.commit()
    finally:
        conn.close()

    with pytest.raises(HTTPException) as excinfo:
        server.review_lead(
            lead_id="m7-lead-2", decision="maybe", listing_refs=[]
        )
    assert excinfo.value.status_code == 400


# ---------------------------------------------------------------------------
# The console panel (D-09)
# ---------------------------------------------------------------------------


def test_m7_the_console_has_a_matching_listings_panel():
    """D-09: the console had no matching-listings element."""
    html = io.open(
        os.path.join(PROJECT_ROOT, "app", "static", "index.html"),
        encoding="utf-8",
    ).read()
    assert 'id="evTable"' in html
    assert 'id="loadEvidence"' in html
    assert "/api/evidence" in html


def test_m7_the_console_has_an_operator_review_panel():
    html = io.open(
        os.path.join(PROJECT_ROOT, "app", "static", "index.html"),
        encoding="utf-8",
    ).read()
    assert 'id="rvApprove"' in html
    assert 'id="rvReject"' in html
    assert "/review" in html


def test_m7_the_console_defaults_to_the_redacted_plot_identifier():
    """The panel must not offer the identifier as the default."""
    html = io.open(
        os.path.join(PROJECT_ROOT, "app", "static", "index.html"),
        encoding="utf-8",
    ).read()
    assert '<option value="false">Redacted (default)</option>' in html


def test_m7_the_console_page_is_still_served():
    import app.server as server

    html = server.read_root()
    body = html.body
    if isinstance(body, bytes):
        body = body.decode("utf-8")
    assert "loadEvidence" in body
    assert "rvApprove" in body


def test_m7_the_console_page_is_well_formed():
    """The panel must not break the page."""
    import re

    html = io.open(
        os.path.join(PROJECT_ROOT, "app", "static", "index.html"),
        encoding="utf-8",
    ).read()
    assert html.count("<script>") == html.count("</script>")
    assert len(re.findall(r"<div\b", html)) == len(re.findall(r"</div>", html))


# ---------------------------------------------------------------------------
# Structure and safety
# ---------------------------------------------------------------------------


def test_m7_the_evidence_module_does_not_write_anything():
    source = io.open(
        os.path.join(PROJECT_ROOT, "market", "evidence.py"), encoding="utf-8"
    ).read()
    for forbidden in ("open(", "sqlite3", "requests", "urllib", "subprocess"):
        assert forbidden not in source, forbidden


def test_m7_the_evidence_module_does_not_read_the_raw_database():
    """The evidence comes from the approved master, never from the
    database that holds 5,867 raw dealer listings (D-10)."""
    source = io.open(
        os.path.join(PROJECT_ROOT, "market", "evidence.py"), encoding="utf-8"
    ).read()
    assert "market_listings" not in source
    assert "get_db_connection" not in source


def test_m7_the_evidence_module_does_not_modify_the_lookup():
    """The evidence layer is a READER of the lookup's rules, never a
    second authority."""
    source = io.open(
        os.path.join(PROJECT_ROOT, "market", "evidence.py"), encoding="utf-8"
    ).read()
    assert "def load_policies" not in source
    assert "def classify_block" not in source
    assert "def query_inventory" not in source
    assert "def summarize_matches" not in source
