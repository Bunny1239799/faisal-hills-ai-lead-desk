"""SYNTHETIC_EVALUATION_SET runner - grounded-answer evaluation harness.

Every question in docs/evals/synthetic_eval_set.jsonl is SYNTHETIC
(written for evaluation, clearly labeled as such). Nothing here is a
genuine dealer question, and no result here may be presented as
real-world replay evidence (that is M12.4 / EB-01).

Each case runs through the REAL turn pipeline (same policy gate, same
lookup, same M5 + M6.1 gates) with isolated scratch stores. Expectations
are policy-level: route, escalation, thin-data wording, no-price,
privacy (no plot number / phone), final qualification values, gates,
and reply determinism across sessions.

Output: docs/reports/eval_results.json + eval_results.md and a console
summary. Verdicts: PASS / FAIL per expectation, WARN never hides a FAIL.

Run:
    .venv\\Scripts\\python.exe docs\\evals\\run_evals.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

SCRATCH = ROOT / "data" / "eval_scratch"
os.environ["M11_STATE_DB"] = str(SCRATCH / "state.db")
os.environ["M11_DEMAND_DB"] = str(SCRATCH / "demand.db")
os.environ["M12_LOG_DB"] = str(SCRATCH / "log.db")

from app.turn_pipeline import run_turn  # noqa: E402
from replay_questions import classify_turn  # noqa: E402

SET_PATH = Path(__file__).resolve().parent / "synthetic_eval_set.jsonl"
OUT_JSON = ROOT / "docs" / "reports" / "eval_results.json"
OUT_MD = ROOT / "docs" / "reports" / "eval_results.md"


def load_cases():
    cases = []
    for line in SET_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            cases.append(json.loads(line))
    return cases


def check(case, final, classifications, replies) -> tuple:
    """(passed, failures list, notes list) against the expectations."""
    expect = case.get("expect", {})
    classification = classifications[-1]
    reply = replies[-1]
    state = (final.get("lead_state") or {}).get("fields", {})
    failures = []
    notes = []

    if "route" in expect and classification["route"] != expect["route"]:
        failures.append("route=%s want %s" % (classification["route"],
                                              expect["route"]))
    if "route_any" in expect and classification["route"] not in \
            expect["route_any"]:
        failures.append("route=%s want one of %s"
                        % (classification["route"], expect["route_any"]))
    if expect.get("escalates") is True and not classification["escalation"]:
        failures.append("expected escalation, none happened")
    if expect.get("escalates") is False and classification["escalation"]:
        failures.append("unexpected escalation")
    if expect.get("thin") and not classification["thin_data"]:
        failures.append("expected thin-data wording")
    if expect.get("no_price") and "PKR" in reply:
        failures.append("reply contains a price against expectation")
    if expect.get("no_plot_number") and classification["privacy"]:
        failures.append("privacy patterns in reply: %s"
                        % classification["privacy"])
    if expect.get("gates_ok") and not classification["gates_ok"]:
        failures.append("final gates not ok")
    for field, key in (("size_final", "size"), ("block_final", "block"),
                       ("budget_final", "budget")):
        if field in expect:
            actual = (state.get(key) or {}).get("value")
            # a budget is a BAND {"min_pkr","max_pkr"}; an exact budget
            # the dealer stated has min == max == the stated figure
            if isinstance(actual, dict):
                actual = actual.get("min_pkr") \
                    if actual.get("min_pkr") == actual.get("max_pkr") \
                    else actual
            if actual != expect[field]:
                failures.append("%s=%r want %r" % (key, actual,
                                                   expect[field]))
    if "same_reply_as" in expect:
        notes.append("determinism compared by the runner (see report)")
    return (not failures), failures, notes


def main():
    SCRATCH.mkdir(parents=True, exist_ok=True)
    for stale in ("state.db", "demand.db", "log.db"):
        try:
            (SCRATCH / stale).unlink()
        except FileNotFoundError:
            pass

    cases = load_cases()
    replies_by_id = {}
    results = []

    # pass 1: run every case
    for case in cases:
        session = "eval-" + case["id"]
        turns = []
        replies = []
        classifications = []
        final = {}
        for text in case["turns"]:
            final = run_turn(text, session)
            replies.append(final.get("reply") or "")
            classifications.append(classify_turn(final))
            turns.append({
                "input": text,
                "route": final.get("route"),
                "escalation": final.get("escalation"),
                "reply_head": replies[-1][:140],
            })
        replies_by_id[case["id"]] = replies[-1]
        results.append({"case": case, "final": final,
                        "classifications": classifications,
                        "replies": replies, "turns": turns})

    # pass 2: expectations, incl. cross-case determinism
    rows = []
    for record in results:
        case = record["case"]
        passed, failures, notes = check(case, record["final"],
                                        record["classifications"],
                                        record["replies"])
        same_as = case.get("expect", {}).get("same_reply_as")
        if same_as:
            if record["replies"][-1] == replies_by_id.get(same_as):
                notes.append("reply identical to %s (deterministic)" % same_as)
            else:
                passed = False
                failures.append("reply differs from %s (non-deterministic?)"
                                % same_as)
        if case.get("expect", {}).get("determinism_key"):
            notes.append("determinism reference case")
        rows.append({"id": case["id"], "category": case["category"],
                     "language": case["language"],
                     "verdict": "PASS" if passed else "FAIL",
                     "failures": failures, "notes": notes,
                     "turns": record["turns"]})

    passed = sum(1 for r in rows if r["verdict"] == "PASS")
    payload = {"set": "SYNTHETIC_EVALUATION_SET", "cases": len(rows),
               "passed": passed, "failed": len(rows) - passed, "rows": rows}
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                        encoding="utf-8")

    lines = [
        "# SYNTHETIC evaluation results (NOT genuine dealer data)",
        "",
        "* set: SYNTHETIC_EVALUATION_SET (%d cases)" % len(rows),
        "* passed: %d   failed: %d" % (passed, len(rows) - passed),
        "* every case ran through the real pipeline with isolated stores",
        "",
        "| id | category | verdict | failures |",
        "|---|---|---|---|",
    ]
    for row in rows:
        lines.append("| %s | %s | %s | %s |" % (
            row["id"], row["category"], row["verdict"],
            "; ".join(row["failures"]) or ""))
    lines.append("")
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")

    print("SYNTHETIC_EVALUATION_SET: %d cases, %d passed, %d failed"
          % (len(rows), passed, len(rows) - passed))
    for row in rows:
        if row["verdict"] == "FAIL":
            print("  FAIL %s (%s): %s" % (row["id"], row["category"],
                                          "; ".join(row["failures"])))
    return 0 if passed == len(rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
