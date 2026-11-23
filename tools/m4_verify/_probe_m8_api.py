"""End-to-end probe of the M8 recommendations API surface.

Run:  python tools/m4_verify/_probe_m8_api.py
"""
from __future__ import annotations

import os
import sys
import tempfile

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

TMP = tempfile.mkdtemp(prefix="fh_m8_api_")
os.environ["DB_PATH"] = os.path.join(TMP, "probe.db")

from fastapi import HTTPException  # noqa: E402

from app import server  # noqa: E402
from data.db import init_db  # noqa: E402

failures = []


def check(name, cond, detail=""):
    print("%-48s %s %s" % (name, "ok  " if cond else "FAIL", detail))
    if not cond:
        failures.append(name)


def main() -> int:
    conn = init_db(os.environ["DB_PATH"])
    conn.close()

    # -- 1. a thin cell produces verified alternatives -----------------
    body = server.recommendations_endpoint(block="C", size_marla=10)
    check("recommendations 200", isinstance(body, dict))
    check("alternatives were produced", bool(body.get("options")),
          len(body.get("options") or []))
    check("the requested cell is not answerable",
          body.get("answerable") is False)
    check("the thin cell is reported as a gap",
          bool(body.get("thin_cells")))
    check("the next best action is an alternative",
          (body.get("next_best_action") or {}).get("action")
          == "offer_verified_alternatives")
    check("the numeric guard passed",
          (body.get("guard") or {}).get("ok") is True)
    check("no availability is claimed",
          body.get("availability_claimed") is False)

    # -- 2. every option names a real, scoped cell ---------------------
    for option in body.get("options") or []:
        check("option is in scope: %s/%s" % (option["block"],
                                             option["size_marla"]),
              option["block"] in ("A", "B", "C"))
        check("option clears the threshold: %s/%s" % (option["block"],
                                                     option["size_marla"]),
              int((option.get("summary") or {}).get("matched_plots") or 0) >= 3)

    # -- 3. the listings are redacted ----------------------------------
    redacted = True
    for option in body.get("options") or []:
        for listing in option.get("listings") or []:
            if listing.get("plot_number") is not None:
                redacted = False
    check("the option listings are redacted", redacted)

    # -- 4. a parked block is refused ----------------------------------
    try:
        server.recommendations_endpoint(block="D", size_marla=10)
        check("a parked block is refused (400)", False, "no exception")
    except HTTPException as exc:
        check("a parked block is refused (400)", exc.status_code == 400,
              exc.status_code)

    # -- 5. an answerable cell needs no alternatives -------------------
    exact = server.recommendations_endpoint(block="C", size_marla=7)
    check("an answerable cell reports the exact match",
          exact.get("answerable") is True)
    check("an answerable cell quotes the exact match",
          (exact.get("next_best_action") or {}).get("action")
          == "quote_exact_match")

    print("\nfailures: %d" % len(failures))
    for f in failures:
        print("  - %s" % f)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
