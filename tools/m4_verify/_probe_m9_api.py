"""End-to-end probe of the M9 qualification and next-best-action surface.

Run:  python tools/m4_verify/_probe_m9_api.py

It attacks the M9 surface from outside the application, the way an
operator or a curious customer would:

  * the decision matches the evidence;
  * a requirement narrows and never widens;
  * a budget that excludes everything produces a QUESTION, not a
    fabricated answer;
  * a thin cell is never offered;
  * a parked block is refused;
  * the surface carries no price and no dealer content.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

TMP = tempfile.mkdtemp(prefix="fh_m9_api_")
os.environ["DB_PATH"] = os.path.join(TMP, "probe.db")

from fastapi import HTTPException  # noqa: E402

from app import server  # noqa: E402
from data.db import init_db  # noqa: E402

failures = []


def check(name, cond, detail=""):
    print("%-52s %s %s" % (name, "ok  " if cond else "FAIL", detail))
    if not cond:
        failures.append(name)


def main() -> int:
    conn = init_db(os.environ["DB_PATH"])
    conn.close()

    # -- 1. a thin cell: the alternatives are offered ------------------
    body = server.next_best_action_endpoint(block="C", size_marla=10)
    check("the action is to offer the alternatives",
          body.get("action") == "offer_verified_alternatives",
          body.get("action"))
    check("the alternatives were produced", bool(body.get("options")),
          len(body.get("options") or []))
    check("the thin cell is reported as a gap",
          bool(body.get("thin_cells")))
    check("no availability is claimed",
          body.get("availability_claimed") is False)
    check("human approval is still required",
          body.get("requires_human_approval") is True)

    # -- 2. the thin cell is never offered -----------------------------
    thin = {(c["block"], c["size_marla"]) for c in body.get("thin_cells") or []}
    offered = {(o["block"], o["size_marla"]) for o in body.get("options") or []}
    check("the thin cell is not offered", not (thin & offered),
          sorted(thin & offered))

    # -- 3. every option clears the threshold --------------------------
    threshold_ok = True
    for option in body.get("options") or []:
        for cell in body.get("thin_cells") or []:
            if (option["block"] == cell["block"]
                    and option["size_marla"] == cell["size_marla"]):
                threshold_ok = False
    check("every option clears the evidence threshold", threshold_ok)

    # -- 4. an answerable cell is quoted -------------------------------
    exact = server.next_best_action_endpoint(block="C", size_marla=7)
    check("an answerable cell is quoted",
          exact.get("action") == "quote_exact_match",
          exact.get("action"))

    # -- 5. the requirements are reported, and the unknown are absent --
    with_budget = server.next_best_action_endpoint(
        block="C", size_marla=10, message="My budget is 6 million.")
    check("the stated budget is reported",
          (with_budget.get("requirements_stated") or {}).get("budget_max_pkr")
          == 6_000_000.0)
    check("the unstated requirements are reported as unknown",
          "purpose" in (with_budget.get("requirements_unknown") or []))
    check("the unstated requirements are not invented",
          "purpose" not in (with_budget.get("requirements_stated") or {}))

    # -- 6. a budget narrows the option set ---------------------------
    check("a budget narrows the alternatives",
          len(with_budget.get("options") or [])
          < len(body.get("options") or []),
          "%d vs %d" % (len(with_budget.get("options") or []),
                        len(body.get("options") or [])))
    for option in with_budget.get("options") or []:
        check("a narrowed option is a verified cell: %s/%s"
              % (option["block"], option["size_marla"]),
              option["block"] in ("A", "B", "C"))

    # -- 7. a budget that excludes everything asks a question ----------
    excluded = server.next_best_action_endpoint(
        block="C", size_marla=10, message="Budget 5 million.")
    check("an impossible budget asks a question",
          excluded.get("action") == "ask_clarifying_question",
          excluded.get("action"))
    check("the question is about the budget",
          (excluded.get("clarifying_question") or {}).get("requirement")
          == "budget")
    check("no option survives an impossible budget",
          excluded.get("options") == [])

    # -- 8. a preferred block re-ranks without removing ----------------
    preferred = server.next_best_action_endpoint(
        block="C", size_marla=10, message="I prefer Block B.")
    check("a preferred block keeps every option",
          len(preferred.get("options") or [])
          == len(body.get("options") or []))
    check("the preferred block comes first",
          (preferred.get("options") or [{}])[0].get("block") == "B",
          (preferred.get("options") or [{}])[0].get("block"))

    # -- 9. a parked block is refused ----------------------------------
    try:
        server.next_best_action_endpoint(block="D", size_marla=10)
        check("a parked block is refused (400)", False, "no exception")
    except HTTPException as exc:
        check("a parked block is refused (400)", exc.status_code == 400,
              exc.status_code)

    # -- 10. the surface carries no price and no dealer content -------
    text = json.dumps(body, default=str)
    check("the surface carries no price",
          "price_min_pkr" not in text
          and "price_median_pkr" not in text
          and "price_max_pkr" not in text)

    private = server.next_best_action_endpoint(
        block="C", size_marla=10,
        message="I am Ali from Lahore, 03001234567, budget 6 million.")
    private_text = json.dumps(private, default=str)
    check("the surface carries no dealer name", "Ali" not in private_text)
    check("the surface carries no phone number",
          "03001234567" not in private_text)
    check("the surface carries no city", "Lahore" not in private_text)

    print("\nfailures: %d" % len(failures))
    for f in failures:
        print("  - %s" % f)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
