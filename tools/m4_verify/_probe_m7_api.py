"""End-to-end probe of the M7 API surface (evidence + review).

The repository keeps the core stdlib-only (RULES_SHORT #5) and the
FastAPI console is not covered by the test suite, so this probe calls the
**endpoint functions directly** against a temp database. That exercises
the real handler logic - the whitelist, the numeric guard, the review
recording - without needing httpx.

Run:  python tools/m4_verify/_probe_m7_api.py
"""
from __future__ import annotations

import os
import sys
import tempfile

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

TMP = tempfile.mkdtemp(prefix="fh_m7_api_")
os.environ["DB_PATH"] = os.path.join(TMP, "probe.db")

from fastapi import HTTPException  # noqa: E402

from app import server  # noqa: E402
from data.db import init_db  # noqa: E402

failures = []


def check(name, cond, detail=""):
    print("%-46s %s %s" % (name, "ok  " if cond else "FAIL", detail))
    if not cond:
        failures.append(name)


def main() -> int:
    conn = init_db(os.environ["DB_PATH"])
    conn.close()

    # -- 1. the evidence endpoint serves a cell ------------------------
    body = server.evidence_endpoint(block="C", size_marla=7)
    check("evidence has listings", bool(body.get("listings")))
    check("evidence plot_number_mode=redacted",
          body.get("plot_number_mode") == "redacted",
          body.get("plot_number_mode"))
    check("evidence numeric guard ok",
          (body.get("guard") or {}).get("ok") is True)

    # -- 2. the identified mode is opt-in ------------------------------
    b2 = server.evidence_endpoint(block="C", size_marla=7,
                                  include_plot_number=True)
    check("identified mode exposes a plot number",
          any((l.get("plot_number") or "") for l in b2.get("listings") or []))

    # -- 3. a parked block is refused ----------------------------------
    try:
        server.evidence_endpoint(block="D", size_marla=10)
        check("parked block refused (400)", False, "no exception")
    except HTTPException as exc:
        check("parked block refused (400)", exc.status_code == 400,
              exc.status_code)

    # -- 4. a thin cell carries no price -------------------------------
    b4 = server.evidence_endpoint(block="A", size_marla=14)
    prices = [l.get("price_median_pkr") for l in b4.get("listings") or []]
    check("thin cell serves no price", all(p is None for p in prices),
          prices[:3])
    check("thin cell not answerable", b4.get("answerable") is False,
          b4.get("answerable"))

    # -- 5. the review workflow records an auditable verdict -----------
    # the review is bound to a real lead
    conn = server.get_db_connection()
    conn.execute(
        "INSERT OR REPLACE INTO leads (lead_id, channel, created_at)"
        " VALUES (?,?,?)",
        ("probe_lead", "probe", "2026-10-21T00:00:00"),
    )
    conn.commit()
    conn.close()

    refs = [l.get("listing_ref") for l in body.get("listings") or []][:3]
    rec = server.review_lead(
        lead_id="probe_lead",
        decision="approved",
        edited_text="",
        reason="probe",
        listing_refs=refs,
        fact_ids=[],
    )
    check("review records the outcome",
          (rec.get("decision") or rec.get("outcome")) == "approved",
          rec.get("decision") or rec.get("outcome"))
    check("review records an evidence digest",
          bool(rec.get("evidence_digest")))

    hist = server.review_history_endpoint(lead_id="probe_lead")
    check("review history returns the verdict", len(hist.get("reviews") or []) >= 1,
          len(hist.get("reviews") or []))

    # -- 6. a review of a non-existent lead is refused -----------------
    try:
        server.review_lead(lead_id="no_such_lead", decision="approved")
        check("review of an unknown lead refused", False, "no exception")
    except HTTPException as exc:
        check("review of an unknown lead refused", exc.status_code == 404,
              exc.status_code)

    print("\nfailures: %d" % len(failures))
    for f in failures:
        print("  - %s" % f)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
