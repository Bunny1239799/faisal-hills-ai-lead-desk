"""M4 focused test for the evaluation tool.

`tools/evaluate_fh_queries.py` is the 20-question audit script. M4 gave it a
single source of truth: the hand-checked question set in `config/questions.json`,
which is the same set `market/price_lookup.py` and the console API use. The
tool must not keep its own private list of cases, or the audit and the
product would drift apart.

Run with:  python -m pytest tests/test_m4_eval_tool.py -q
"""

import io
import json
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from market import price_lookup

TOOL = PROJECT_ROOT / "tools" / "evaluate_fh_queries.py"


def test_evaluation_tool_exists():
    assert TOOL.is_file()


def test_evaluation_tool_uses_the_shared_question_set():
    source = TOOL.read_text(encoding="utf-8")

    # The tool must import the shared question set, not define its own.
    assert "price_lookup" in source
    assert "load_questions" in source or "check_questions" in source

    # The old private case list must be gone.
    assert "block_sizes[:8]" not in source
    assert "feature_candidates" not in source


def test_evaluation_tool_runs_and_passes():
    result = subprocess.run(
        [sys.executable, str(TOOL)],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=300,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASSED=20" in result.stdout
    assert "FAILED=0" in result.stdout


def test_evaluation_tool_report_has_no_raw_dealer_text():
    report_path = PROJECT_ROOT / "evaluation" / "reports" / "fh_query_20_latest.json"
    if not report_path.is_file():
        pytest.skip("report not generated yet")

    payload = json.loads(report_path.read_text(encoding="utf-8"))
    blob = json.dumps(payload)

    # The privacy FLAGS mention the words "sender"/"phone"; the DATA must
    # not contain them. Check the data rows, not the whole blob.
    assert "raw_text" not in blob
    for row in payload["results"]:
        assert "raw_text" not in row
        assert "sender" not in row
        assert set(row.keys()) <= {
            "id", "name", "filters", "expected_reference",
            "query_result", "reference_checks", "passed",
        }

    assert payload["privacy"]["sender_names_included"] is False
    assert payload["privacy"]["phone_numbers_included"] is False


def test_shared_question_set_is_the_one_the_tool_checks():
    config = price_lookup.load_questions()
    ids = [q["id"] for q in config["questions"]]

    assert ids == list(range(1, 21))
    assert len(ids) == len(set(ids))
