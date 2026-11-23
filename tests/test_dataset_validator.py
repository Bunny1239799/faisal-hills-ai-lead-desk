"""Tests for the dataset validation tool."""

import json
from pathlib import Path
import pytest

from tools.validate_dataset import DatasetValidationError, validate_dataset_file


def create_valid_row(row_id="g001", **overrides):
    base = {
        "id": row_id,
        "message": "Faisal Hills A block 5 marla plot price please?",
        "language": "roman_ur",
        "lead_type": "buyer",
        "high_intent": True,
        "needs_human": False,
        "intent": "price_inquiry",
        "facts_needed": ["pricing"],
        "expected_action": "answer_with_facts",
        "risk_tags": [],
        "source": "synthetic",
    }
    base.update(overrides)
    return base


def write_jsonl(file_path: Path, rows, bom: bool = False, encoding: str = "utf-8"):
    content = "\n".join(json.dumps(r) for r in rows) + "\n"
    data = content.encode(encoding)
    if bom:
        data = b"\xef\xbb\xbf" + data
    file_path.write_bytes(data)


def test_valid_dataset_passes(tmp_path):
    rows = [
        create_valid_row(row_id="g001"),
        create_valid_row(row_id="g002", language="en", intent="location", facts_needed=["blocks"]),
    ]
    file_path = tmp_path / "valid.jsonl"
    write_jsonl(file_path, rows)

    parsed_rows, stats = validate_dataset_file(file_path)
    assert len(parsed_rows) == 2
    assert stats["total_rows"] == 2
    assert stats["language"]["roman_ur"] == 1
    assert stats["language"]["en"] == 1


def test_reject_utf8_bom(tmp_path):
    rows = [create_valid_row()]
    file_path = tmp_path / "bom.jsonl"
    write_jsonl(file_path, rows, bom=True)

    with pytest.raises(DatasetValidationError, match="contains UTF-8 BOM"):
        validate_dataset_file(file_path)


def test_reject_duplicate_ids(tmp_path):
    rows = [
        create_valid_row(row_id="g001"),
        create_valid_row(row_id="g001"),
    ]
    file_path = tmp_path / "dup_id.jsonl"
    write_jsonl(file_path, rows)

    with pytest.raises(DatasetValidationError, match="Duplicate id 'g001'"):
        validate_dataset_file(file_path)


def test_reject_missing_field(tmp_path):
    row = create_valid_row()
    del row["expected_action"]
    file_path = tmp_path / "missing_field.jsonl"
    write_jsonl(file_path, [row])

    with pytest.raises(DatasetValidationError, match="Missing required fields: \\['expected_action'\\]"):
        validate_dataset_file(file_path)


def test_reject_invalid_language(tmp_path):
    row = create_valid_row(language="french")
    file_path = tmp_path / "invalid_lang.jsonl"
    write_jsonl(file_path, [row])

    with pytest.raises(DatasetValidationError, match="Invalid language 'french'"):
        validate_dataset_file(file_path)


def test_reject_invalid_intent(tmp_path):
    row = create_valid_row(intent="unknown_intent")
    file_path = tmp_path / "invalid_intent.jsonl"
    write_jsonl(file_path, [row])

    with pytest.raises(DatasetValidationError, match="Invalid intent 'unknown_intent'"):
        validate_dataset_file(file_path)


def test_reject_invalid_fact_needed(tmp_path):
    row = create_valid_row(facts_needed=["random_fact"])
    file_path = tmp_path / "invalid_fact.jsonl"
    write_jsonl(file_path, [row])

    with pytest.raises(DatasetValidationError, match="Invalid fact 'random_fact'"):
        validate_dataset_file(file_path)


def test_reject_invalid_risk_tag(tmp_path):
    row = create_valid_row(risk_tags=["invalid_tag"])
    file_path = tmp_path / "invalid_risk_tag.jsonl"
    write_jsonl(file_path, [row])

    with pytest.raises(DatasetValidationError, match="Invalid tag 'invalid_tag'"):
        validate_dataset_file(file_path)


def test_reject_invalid_lead_type(tmp_path):
    row = create_valid_row(lead_type="seller")
    file_path = tmp_path / "invalid_lead_type.jsonl"
    write_jsonl(file_path, [row])

    with pytest.raises(DatasetValidationError, match="Invalid lead_type 'seller'"):
        validate_dataset_file(file_path)


def test_reject_invalid_expected_action(tmp_path):
    row = create_valid_row(expected_action="auto_close")
    file_path = tmp_path / "invalid_action.jsonl"
    write_jsonl(file_path, [row])

    with pytest.raises(DatasetValidationError, match="Invalid expected_action 'auto_close'"):
        validate_dataset_file(file_path)


def test_reject_non_boolean_flags(tmp_path):
    row = create_valid_row(high_intent="yes")
    file_path = tmp_path / "non_bool.jsonl"
    write_jsonl(file_path, [row])

    with pytest.raises(DatasetValidationError, match="'high_intent' must be a boolean"):
        validate_dataset_file(file_path)


def test_reject_invalid_json_syntax(tmp_path):
    file_path = tmp_path / "bad_json.jsonl"
    file_path.write_text("{\"id\": \"g001\", unquoted: broken}\n", encoding="utf-8")

    with pytest.raises(DatasetValidationError, match="Invalid JSON"):
        validate_dataset_file(file_path)
