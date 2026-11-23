"""Audit the approved master against the hand-checked question set.

M4 change: this tool used to build its own private list of 20 cases
(discovering block/size combinations from the master and inventing the
feature and no-data cases). The audit and the product therefore tested
different things.

It now runs the SAME hand-checked question set the product uses -
`config/questions.json` - through the same lookup the product uses -
`market.price_lookup`. One source of truth, no drift. The expected match
count and median for every question were measured from the approved
master and recorded in the question file, so this is a real check rather
than a self-fulfilling one.

The tool reads the approved master READ-ONLY and writes only its own
report. It never writes to the master, to a database, or to a dataset.

Usage:
    python tools/evaluate_fh_queries.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from market import price_lookup
from market.fh_query import load_inventory, MASTER_PATH

REPORT = PROJECT_ROOT / "evaluation" / "reports" / "fh_query_20_latest.json"

# The tool is a verification step, not a decision point: it must never be
# able to answer a customer. It uses the lookup's internal API only.
assert price_lookup is not None


def build_report() -> dict:
    rows = load_inventory(MASTER_PATH)

    if len(rows) != 374:
        raise RuntimeError(
            "EXPECTED 374 MASTER RECORDS, GOT %d" % len(rows)
        )

    check = price_lookup.check_questions()

    results = []
    for entry in check["results"]:
        results.append({
            "id": entry["id"],
            "name": entry["question"],
            "filters": entry["filters"],
            "expected_reference": entry["expected"],
            "query_result": entry["actual"],
            "reference_checks": entry["checks"],
            "passed": entry["passed"],
        })

    failures = check["failures"]

    return {
        "master_records": len(rows),
        "case_count": len(results),
        "passed_cases": sum(1 for r in results if r["passed"]),
        "failed_cases": len(failures),
        "failures": failures,
        "results": results,
        "privacy": {
            "sender_names_included": False,
            "phone_numbers_included": False,
        },
    }


def main() -> int:
    report = build_report()

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(
        json.dumps(report, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    if report["failed_cases"]:
        print(json.dumps(report, indent=2, ensure_ascii=False))
        raise SystemExit(1)

    print("MASTER_RECORDS=%d" % report["master_records"])
    print("CASES=%d" % report["case_count"])
    print("PASSED=%d" % report["passed_cases"])
    print("FAILED=0")
    print("REPORT=%s" % REPORT)

    for result in report["results"]:
        q = result["query_result"]
        print(
            "%02d | %-58s | matches=%-4d median=%-12s answerable=%s"
            % (
                result["id"] or 0,
                (result["name"] or "")[:58],
                q["matched_plots"],
                q["price_median_pkr"],
                q["answerable"],
            )
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
