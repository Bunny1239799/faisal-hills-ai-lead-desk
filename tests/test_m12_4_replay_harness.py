"""M12.4 - the real-question replay harness.

The harness replays a question file through the REAL turn pipeline and
classifies every answer mechanically (route, escalation, thin data,
price leak, privacy, gates) - and decides correct/wrong ONLY when the
question file states an expectation. All questions in these tests are
FABRICATED; the real founder question file does not exist yet (see
docs/reports/engineering_blockers.md).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from replay_questions import (  # noqa: E402
    classify_turn, load_questions, replay,
)


@pytest.fixture(autouse=True)
def _stores(tmp_path, monkeypatch):
    monkeypatch.setenv("M11_STATE_DB", str(tmp_path / "state.db"))
    monkeypatch.setenv("M11_DEMAND_DB", str(tmp_path / "demand.db"))
    monkeypatch.setenv("M12_LOG_DB", str(tmp_path / "log.db"))


def _write(path: Path, records):
    lines = []
    for record in records:
        lines.append(record if isinstance(record, str)
                     else json.dumps(record, ensure_ascii=False))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_the_question_file_loads_from_jsonl_and_plain_text(tmp_path):
    jsonl = _write(tmp_path / "q.jsonl", [
        {"id": "a", "question": "price of 5 marla in block C?",
         "expect": {"route": "exact"}},
        {"question": "Any discount?"},
    ])
    loaded = load_questions(jsonl)
    assert loaded[0]["id"] == "a" and loaded[0]["expect"]["route"] == "exact"
    assert loaded[1]["id"] == "q002"  # generated id

    plain = _write(tmp_path / "q.txt", ["hello", "", "second question"])
    assert [q["question"] for q in load_questions(plain)] == \
        ["hello", "second question"]


def test_the_harness_classifies_each_route_and_flags_nothing(
        tmp_path):
    questions = _write(tmp_path / "q.jsonl", [
        {"id": "exact", "question": "5 marla in block C"},
        {"id": "clarify", "question": "I need a plot"},
        {"id": "discount", "question": "Any discount?"},
        {"id": "thin", "question": "10 marla C block price"},
    ])
    result = replay(questions, tmp_path / "out")
    rows = {row["id"]: row for row in result["rows"]}

    assert rows["exact"]["classification"]["route"] in ("exact", "alternative")
    assert rows["exact"]["classification"]["price_leak"] == []
    # M13: a bare intent ("I need a plot") now offers the strongest
    # verified cells AND asks the next clarifying question, so the
    # mechanical route is "alternative" (the question rides along in the
    # reply text; the escalation and leak checks below are unchanged).
    assert rows["clarify"]["classification"]["route"] in (
        "clarify", "alternative")
    assert rows["discount"]["classification"]["escalation"] is True
    assert rows["thin"]["classification"]["thin_data"] is True

    # nothing leaked anywhere: no price leak, no privacy hit, gates ok
    for row in result["rows"]:
        assert row["classification"]["price_leak"] == []
        assert row["classification"]["privacy"] == []
        assert row["classification"]["gates_ok"] is True

    assert result["summary"]["questions"] == 4
    assert result["summary"]["escalations"] == 1
    # M13: the bare-intent reply ("I need a plot") quotes no numbers and
    # starts with the same honest thin-data wording, so two of the four
    # questions now classify as thin-data.
    assert result["summary"]["thin_data"] == 2
    assert result["summary"]["privacy_hits"] == 0
    assert (tmp_path / "out" / "report.md").exists()
    assert (tmp_path / "out" / "report.json").exists()


def test_correct_and_wrong_require_a_stated_expectation(tmp_path):
    questions = _write(tmp_path / "q.jsonl", [
        {"id": "ok", "question": "Any discount?",
         "expect": {"escalates": True}},
        {"id": "bad", "question": "Any discount?",
         "expect": {"route": "exact"}},
        {"id": "open", "question": "5 marla in block C"},
    ])
    result = replay(questions, tmp_path / "out2")
    verdicts = {row["id"]: row["verdict"] for row in result["rows"]}
    assert verdicts["ok"] == "correct"
    assert verdicts["bad"].startswith("wrong:")
    # no expectation -> founder judgement, never a guess
    assert verdicts["open"] == "needs_founder_review"
    assert result["summary"]["counts"]["needs_founder_review"] == 1


def test_an_empty_question_file_is_refused(tmp_path):
    empty = tmp_path / "empty.jsonl"
    empty.write_text("\n\n", encoding="utf-8")
    with pytest.raises(ValueError):
        replay(empty, tmp_path / "out3")


def test_the_report_tells_the_founder_it_awaits_review(tmp_path):
    questions = _write(tmp_path / "q.jsonl", [{"question": "hello there"}])
    replay(questions, tmp_path / "out4")
    text = (tmp_path / "out4" / "report.md").read_text(encoding="utf-8")
    assert "Founder reviews this report" in text
    assert "needs_founder_review" in text
