"""M12.4 - the real-question replay harness.

What this module is
-------------------
Replays a file of real dealer questions through the REAL turn pipeline
- the same policy gate, the same lookup, the same two final gates the
operator desk uses - and produces a per-question quality report with a
mechanical classification and, where the question file carries an
expectation, a correct/wrong verdict.

The mechanical classes are exactly what the deterministic pipeline can
prove about its own answer:

* ``route``            exact / alternative / clarify / escalate
* ``escalation``       the policy escalated or refused the turn
* ``thin_data``        the answer is the policy's own insufficient-data
                       wording (a cell below the evidence threshold)
* ``price_leak``       a number in the reply the approved master may
                       not serve (the M5 traceability check, per reply)
* ``privacy``          a plot number, a phone pattern or an email in
                       the reply - none may ever appear
* ``gates_ok``         both final gates reported true

``correct`` / ``wrong`` is ONLY decided when the question file states
an expectation (``expect.route`` / ``expect.escalates``); a question
with no expectation is listed for founder judgement, never guessed.

The harness is read-only for everything except its report directory. It
decides nothing and changes nothing: the founder reviews the report
before any change (handoff §5, M12.4).
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.turn_pipeline import run_turn  # noqa: E402
from market import fact_guard  # noqa: E402
from market.fact_validator import extract_numbers  # noqa: E402

__all__ = ["classify_turn", "load_questions", "replay"]

_PLOT_NUMBER = re.compile(r"\b[A-Z]{1,2}-\d{2,}\b")
_PHONE = re.compile(r"(?:\+92|0)3\d{2}[- ]?\d{7}\b")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
_SESSION_PREFIX = "m12-4-replay-"

ROUTES = ("exact", "alternative", "clarify", "escalate")


def _insufficient_reply_prefix() -> str:
    try:
        with (ROOT / "config" / "policies.json").open("r", encoding="utf-8") as handle:
            text = json.load(handle)["answer_policy"]["insufficient_data_reply"]
        return text[:60]
    except Exception:
        return "I need to confirm the current market information"


_ALLOWED_CACHE: List[Optional[set]] = [None]


def _allowed_numbers() -> set:
    """The numbers any replayed reply may legitimately carry.

    M12.4/EB-01: the union spans the SAME filter dimensions the
    product's own M5 gate judges per turn - block, size AND the feature
    filters (corner / sun-facing / NDC), INCLUDING the no-block and
    no-size combinations ("any block ... corner", "Block C corner
    plot") whose replies quote the wider cell's counts and price band.
    The union is a SUPERSET of every per-turn allowed set, so a genuine
    leak - a number no allowed combination serves - is still flagged,
    while a correct reply is no longer misclassified as
    "wrong:price_leak".
    """
    if _ALLOWED_CACHE[0] is not None:
        return _ALLOWED_CACHE[0]
    from market.fh_query import load_inventory
    rows = load_inventory()
    policies = None
    allowed = set()
    for block in (None, "A", "B", "C"):
        for size in (None, 5, 7, 10, 14, 20, 40):
            for corner in (None, True, False):
                for sun in (None, True, False):
                    for ndc in (None, True, False):
                        allowed |= fact_guard.allowed_numbers_for(
                            block=block,
                            size_marla=size,
                            corner=corner,
                            sun_facing=sun,
                            ndc_open=ndc,
                            policies=policies,
                            rows=rows,
                        )
    _ALLOWED_CACHE[0] = allowed
    return allowed


def load_questions(path: Path) -> List[Dict[str, Any]]:
    """The question file: JSONL of ``{"id", "question", "expect"?}`` or a
    plain-text file of one question per line (ids are generated)."""
    questions: List[Dict[str, Any]] = []
    with Path(path).open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            text = line.strip()
            if not text:
                continue
            try:
                record = json.loads(text)
            except json.JSONDecodeError:
                record = {"question": text}
            if not isinstance(record, dict) or not record.get("question"):
                continue
            record.setdefault("id", "q%03d" % line_number)
            questions.append(record)
    return questions


def classify_turn(result: Dict[str, Any]) -> Dict[str, Any]:
    """The mechanical classification of one replayed turn."""
    reply = str(result.get("reply") or "")
    route = result.get("route")

    untraceable = {value for _text, value in extract_numbers(reply)} - \
        _allowed_numbers()
    privacy_hits = []
    if _PLOT_NUMBER.search(reply):
        privacy_hits.append("plot_number")
    if _PHONE.search(reply):
        privacy_hits.append("phone_pattern")
    if _EMAIL.search(reply):
        privacy_hits.append("email_pattern")

    gates = result.get("gates") or {}
    return {
        "route": route,
        "escalation": bool(result.get("escalation")),
        "thin_data": reply.startswith(_insufficient_reply_prefix()),
        "price_leak": sorted(untraceable),
        "privacy": privacy_hits,
        "gates_ok": gates.get("traceability_ok") is True and
                    gates.get("claim_guard_ok") is True,
        "unmet_recorded": bool(result.get("unmet_demand")),
    }


def _verdict(classification: Dict[str, Any],
             expect: Optional[Dict[str, Any]]) -> str:
    """correct / wrong when an expectation exists, else founder review."""
    if classification["privacy"]:
        return "wrong:privacy"
    if classification["price_leak"]:
        return "wrong:price_leak"
    if not expect:
        return "needs_founder_review"
    expected_route = expect.get("route")
    expected_escalation = expect.get("escalates")
    if expected_route and classification["route"] != expected_route:
        return "wrong:route"
    if expected_escalation is not None and \
            bool(classification["escalation"]) != bool(expected_escalation):
        return "wrong:escalation"
    if expected_route == "escalate":
        return "correct"
    return "correct"


def replay(questions_path: Path, out_dir: Path,
           limit: Optional[int] = None) -> Dict[str, Any]:
    """Replay every question and write report.md + report.json."""
    questions = load_questions(Path(questions_path))
    if limit:
        questions = questions[:int(limit)]
    if not questions:
        raise ValueError("no questions found in %s" % questions_path)

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    rows: List[Dict[str, Any]] = []
    counts: Dict[str, int] = {}
    for index, question in enumerate(questions, start=1):
        session = "%s%04d" % (_SESSION_PREFIX, index)
        result = run_turn(str(question["question"]), session)
        classification = classify_turn(result)
        verdict = _verdict(classification, question.get("expect"))
        counts[verdict] = counts.get(verdict, 0) + 1
        rows.append({
            "id": question["id"],
            "question": question["question"],
            "classification": classification,
            "verdict": verdict,
            "reply_head": str(result.get("reply") or "")[:160],
        })

    summary = {
        "questions": len(rows),
        "counts": counts,
        "escalations": sum(1 for r in rows if r["classification"]["escalation"]),
        "thin_data": sum(1 for r in rows if r["classification"]["thin_data"]),
        "price_leaks": sum(1 for r in rows if r["classification"]["price_leak"]),
        "privacy_hits": sum(1 for r in rows if r["classification"]["privacy"]),
        "gates_ok": sum(1 for r in rows if r["classification"]["gates_ok"]),
    }
    payload = {"summary": summary, "rows": rows}
    with (out_dir / "report.json").open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)

    lines = [
        "# Real-question replay - quality report",
        "",
        "* questions: %d" % summary["questions"],
        "* escalations: %d   thin-data answers: %d" % (
            summary["escalations"], summary["thin_data"]),
        "* price leaks: %d   privacy hits: %d   gates ok: %d" % (
            summary["price_leaks"], summary["privacy_hits"],
            summary["gates_ok"]),
        "* verdict counts: %s" % json.dumps(counts, ensure_ascii=False),
        "",
        "| id | verdict | route | esc | thin | question |",
        "|---|---|---|---|---|---|",
    ]
    for row in rows:
        c = row["classification"]
        lines.append("| %s | %s | %s | %s | %s | %s |" % (
            row["id"], row["verdict"], c["route"],
            "Y" if c["escalation"] else "",
            "Y" if c["thin_data"] else "",
            str(row["question"])[:60].replace("|", "/")))
    lines += [
        "",
        "A question with no stated expectation is marked",
        "`needs_founder_review`: the harness classifies mechanically and",
        "never guesses correctness. **Founder reviews this report before",
        "any change** (handoff §5, M12.4).",
        "",
    ]
    (out_dir / "report.md").write_text("\n".join(lines), encoding="utf-8")
    return payload


if __name__ == "__main__":
    import argparse
    from datetime import datetime

    parser = argparse.ArgumentParser(
        description="Replay a dealer-question file through the real "
                    "pipeline and produce the quality report.")
    parser.add_argument("questions", help="JSONL or plain-text question file")
    parser.add_argument("--out", default=None,
                        help="report directory (default: a timestamped "
                             "folder under data\\replay_reports)")
    args = parser.parse_args()

    out = Path(args.out) if args.out else \
        ROOT / "data" / "replay_reports" / datetime.now().strftime(
            "%Y%m%d_%H%M%S")
    result = replay(Path(args.questions), out)
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
    print("report: %s" % (out / "report.md"))
