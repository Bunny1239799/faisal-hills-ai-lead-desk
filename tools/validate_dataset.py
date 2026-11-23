"""Dataset validator for evaluation and red-team JSONL files."""

import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Tuple

# Ensure project root is in sys.path when executed directly as a script
project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from evaluation.labels import (
    EXPECTED_ACTIONS,
    FACTS_NEEDED_VALUES,
    INTENTS,
    LANGUAGES,
    LEAD_TYPES,
    REQUIRED_FIELDS,
    RISK_TAGS_VALUES,
)


class DatasetValidationError(ValueError):
    """Raised when a dataset file fails validation."""
    pass


def validate_dataset_file(file_path: Path) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    Validates a dataset JSONL file.

    Checks:
    - File existence
    - No UTF-8 BOM
    - Valid UTF-8 encoding
    - Valid JSON on each line
    - Required fields presence
    - Field types and valid enum values
    - Unique non-empty IDs

    Returns parsed rows and summary statistics.
    """
    if not file_path.is_file():
        raise DatasetValidationError(f"File not found: {file_path}")

    raw_bytes = file_path.read_bytes()
    if raw_bytes.startswith(b"\xef\xbb\xbf"):
        raise DatasetValidationError(f"File contains UTF-8 BOM: {file_path}")

    try:
        content = raw_bytes.decode("utf-8")
    except UnicodeDecodeError as e:
        raise DatasetValidationError(f"Invalid UTF-8 encoding in {file_path}: {e}")

    lines = content.splitlines()
    seen_ids = set()
    rows = []

    for line_idx, line in enumerate(lines, start=1):
        line_str = line.strip()
        if not line_str:
            continue

        try:
            row = json.loads(line_str)
        except json.JSONDecodeError as e:
            raise DatasetValidationError(f"Line {line_idx}: Invalid JSON - {e}")

        if not isinstance(row, dict):
            raise DatasetValidationError(f"Line {line_idx}: Expected JSON object, got {type(row).__name__}")

        # Check required fields
        missing_fields = REQUIRED_FIELDS - set(row.keys())
        if missing_fields:
            raise DatasetValidationError(
                f"Line {line_idx}: Missing required fields: {sorted(missing_fields)}"
            )

        # Validate ID
        row_id = row.get("id")
        if not isinstance(row_id, str) or not row_id.strip():
            raise DatasetValidationError(f"Line {line_idx}: 'id' must be a non-empty string")
        if row_id in seen_ids:
            raise DatasetValidationError(f"Line {line_idx}: Duplicate id '{row_id}' found")
        seen_ids.add(row_id)

        # Validate message
        if not isinstance(row.get("message"), str) or not row["message"].strip():
            raise DatasetValidationError(f"Line {line_idx} ({row_id}): 'message' must be a non-empty string")

        # Validate language
        lang = row.get("language")
        if lang not in LANGUAGES:
            raise DatasetValidationError(
                f"Line {line_idx} ({row_id}): Invalid language '{lang}'. Allowed: {sorted(LANGUAGES)}"
            )

        # Validate lead_type
        lead_type = row.get("lead_type")
        if lead_type not in LEAD_TYPES:
            raise DatasetValidationError(
                f"Line {line_idx} ({row_id}): Invalid lead_type '{lead_type}'. Allowed: {sorted(LEAD_TYPES)}"
            )

        # Validate boolean flags
        if not isinstance(row.get("high_intent"), bool):
            raise DatasetValidationError(f"Line {line_idx} ({row_id}): 'high_intent' must be a boolean")
        if not isinstance(row.get("needs_human"), bool):
            raise DatasetValidationError(f"Line {line_idx} ({row_id}): 'needs_human' must be a boolean")

        # Validate intent
        intent = row.get("intent")
        if intent not in INTENTS:
            raise DatasetValidationError(
                f"Line {line_idx} ({row_id}): Invalid intent '{intent}'. Allowed: {sorted(INTENTS)}"
            )

        # Validate facts_needed
        facts_needed = row.get("facts_needed")
        if not isinstance(facts_needed, list):
            raise DatasetValidationError(f"Line {line_idx} ({row_id}): 'facts_needed' must be a list")
        for fact in facts_needed:
            if fact not in FACTS_NEEDED_VALUES:
                raise DatasetValidationError(
                    f"Line {line_idx} ({row_id}): Invalid fact '{fact}' in facts_needed. Allowed: {sorted(FACTS_NEEDED_VALUES)}"
                )

        # Validate expected_action
        action = row.get("expected_action")
        if action not in EXPECTED_ACTIONS:
            raise DatasetValidationError(
                f"Line {line_idx} ({row_id}): Invalid expected_action '{action}'. Allowed: {sorted(EXPECTED_ACTIONS)}"
            )

        # Validate risk_tags
        risk_tags = row.get("risk_tags")
        if not isinstance(risk_tags, list):
            raise DatasetValidationError(f"Line {line_idx} ({row_id}): 'risk_tags' must be a list")
        for tag in risk_tags:
            if tag not in RISK_TAGS_VALUES:
                raise DatasetValidationError(
                    f"Line {line_idx} ({row_id}): Invalid tag '{tag}' in risk_tags. Allowed: {sorted(RISK_TAGS_VALUES)}"
                )

        # Validate source
        if not isinstance(row.get("source"), str) or not row["source"].strip():
            raise DatasetValidationError(f"Line {line_idx} ({row_id}): 'source' must be a non-empty string")

        rows.append(row)

    stats = compute_statistics(rows)
    return rows, stats


def compute_statistics(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Computes distribution counts for a list of dataset rows."""
    total = len(rows)
    language_counts = Counter(r["language"] for r in rows)
    intent_counts = Counter(r["intent"] for r in rows)
    needs_human_counts = Counter(r["needs_human"] for r in rows)
    lead_type_counts = Counter(r["lead_type"] for r in rows)
    expected_action_counts = Counter(r["expected_action"] for r in rows)

    return {
        "total_rows": total,
        "language": dict(language_counts),
        "intent": dict(intent_counts),
        "needs_human": dict(needs_human_counts),
        "lead_type": dict(lead_type_counts),
        "expected_action": dict(expected_action_counts),
    }


def print_report(file_path: Path, stats: Dict[str, Any]) -> None:
    """Prints formatted summary statistics to console."""
    print(f"\n========================================")
    print(f" Dataset Validation Report: {file_path.name}")
    print(f"========================================")
    print(f"Total Rows: {stats['total_rows']}\n")

    print("Counts by Language:")
    for lang, count in sorted(stats["language"].items()):
        print(f"  - {lang:12s}: {count:4d} ({count / stats['total_rows']:.1%})")

    print("\nCounts by Intent:")
    for intent, count in sorted(stats["intent"].items()):
        print(f"  - {intent:20s}: {count:4d} ({count / stats['total_rows']:.1%})")

    print("\nCounts by needs_human:")
    for nh, count in sorted(stats["needs_human"].items()):
        print(f"  - {str(nh):12s}: {count:4d} ({count / stats['total_rows']:.1%})")

    print(f"========================================\n")


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: python -m tools.validate_dataset <path_to_jsonl_file> [more_files...]")
        return 1

    has_errors = False
    for path_str in sys.argv[1:]:
        path = Path(path_str)
        try:
            _, stats = validate_dataset_file(path)
            print_report(path, stats)
            print(f"[OK] Validation passed: {path}")
        except DatasetValidationError as err:
            print(f"[FAIL] Validation error in {path}: {err}", file=sys.stderr)
            has_errors = True
        except Exception as err:
            print(f"[ERROR] Unexpected error processing {path}: {err}", file=sys.stderr)
            has_errors = True

    return 1 if has_errors else 0


if __name__ == "__main__":
    sys.exit(main())
