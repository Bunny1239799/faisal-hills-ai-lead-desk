from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path
from statistics import median
from typing import Any, Dict, Iterable, List, Optional


# The approved master is the owner's external file. FH_MASTER_PATH is
# the ONE documented relocation variable: the test suite already uses
# it (conftest), CI uses it, and the SYNTHETIC founder demo (demo/)
# uses it to run the real deterministic architecture over clearly
# labeled demo data. When the variable is unset - production and every
# normal run - the owner's approved master is used, unchanged.
MASTER_PATH = Path(
    os.environ.get("FH_MASTER_PATH", "").strip()
    or r"D:\AI-Projects\real-estate-agent\approved_data\master_inventory.jsonl"
)

# Stage 1: the configured path captured at import time. The versioned
# inventory workspace only redirects loads that target this configured
# default; any explicit path (a test fixture, an ingest-gate control run)
# is always honoured exactly as given.
_CONFIGURED_MASTER_PATH = MASTER_PATH


def _serving_path(path: Path) -> Path:
    """The active workspace version when one exists, else ``path``.

    With no valid ``active_version.json`` this returns ``path`` unchanged,
    so the serving path is byte-identical to the pre-Stage-1 behavior.
    """
    try:
        from market.inventory_workspace import resolve_active_source

        active = resolve_active_source()
    except Exception:
        active = None

    if not active:
        return path

    try:
        if Path(path).resolve() == Path(_CONFIGURED_MASTER_PATH).resolve():
            return Path(active["path"])
    except OSError:
        return path
    return path


def _number(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)

    text = str(value).strip().replace(",", "")
    if not text:
        return None

    try:
        return float(text)
    except ValueError:
        return None


def _boolean(value: Any) -> Optional[bool]:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return value

    text = str(value).strip().lower()

    if text in {"true", "1", "yes", "y", "open"}:
        return True
    if text in {"false", "0", "no", "n", "close", "closed"}:
        return False

    return None


def _normalize_block(value: Any) -> Optional[str]:
    if value is None:
        return None

    text = str(value).strip().upper()

    aliases = {
        "FHA": "A",
        "FHB": "B",
        "FHC": "C",
        "FHD": "D",
        "FHE": "E",
        "EXECUTIVE": "E",
        "EXECUTIVE BLOCK": "E",
    }

    if text in aliases:
        return aliases[text]

    match = re.fullmatch(r"F?H?([A-E])", text)
    if match:
        return match.group(1)

    if text in {"A", "B", "C", "D", "E"}:
        return text

    return text


def _source_values(value: Any) -> Iterable[str]:
    if value is None or value == "":
        return []

    if isinstance(value, list):
        return [str(x).strip() for x in value if str(x).strip()]

    text = str(value).strip()

    if not text:
        return []

    parts = re.split(r"[|;,]", text)
    return [part.strip() for part in parts if part.strip()]


def load_inventory(path: Path = MASTER_PATH) -> List[Dict[str, Any]]:
    path = _serving_path(Path(path))

    if not path.exists():
        raise FileNotFoundError(f"Approved master not found: {path}")

    rows: List[Dict[str, Any]] = []

    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            text = line.strip()

            if not text:
                continue

            try:
                record = json.loads(text)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"Invalid JSON on line {line_number}: {exc}"
                ) from exc

            if not isinstance(record, dict):
                raise ValueError(
                    f"Line {line_number} is not a JSON object."
                )

            rows.append(record)

    return rows


def query_inventory(
    block: Optional[str] = None,
    size_marla: Optional[float] = None,
    corner: Optional[bool] = None,
    sun_facing: Optional[bool] = None,
    ndc_open: Optional[bool] = None,
    inventory: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    rows = inventory if inventory is not None else load_inventory()

    wanted_block = _normalize_block(block)
    wanted_size = _number(size_marla)

    matches: List[Dict[str, Any]] = []

    for row in rows:
        row_block = _normalize_block(row.get("block"))

        if wanted_block is not None and row_block != wanted_block:
            continue

        row_size = _number(row.get("size_marla"))

        if wanted_size is not None:
            if row_size is None or abs(row_size - wanted_size) > 0.001:
                continue

        for field, wanted in (
            ("corner", corner),
            ("sun_facing", sun_facing),
            ("ndc_open", ndc_open),
        ):
            if wanted is None:
                continue

            actual = _boolean(row.get(field))

            if actual is None or actual != wanted:
                break
        else:
            matches.append(row)

    return matches


def summarize_matches(
    matches: List[Dict[str, Any]],
) -> Dict[str, Any]:
    if not matches:
        return {
            "matched_plots": 0,
            "observation_count": 0,
            "price_min_pkr": None,
            "price_median_pkr": None,
            "price_max_pkr": None,
            "latest_date": None,
            "distinct_source_chats": 0,
            "coverage_level": "insufficient",
            "trust_status": "insufficient_data",
            "answerable_for_demo": False,
        }

    minimums = [
        _number(row.get("price_min_pkr"))
        for row in matches
    ]
    medians = [
        _number(row.get("price_median_pkr"))
        for row in matches
    ]
    maximums = [
        _number(row.get("price_max_pkr"))
        for row in matches
    ]

    minimums = [value for value in minimums if value is not None]
    medians = [value for value in medians if value is not None]
    maximums = [value for value in maximums if value is not None]

    observations = sum(
        int(_number(row.get("observation_count")) or 0)
        for row in matches
    )

    latest_values = []
    for row in matches:
        raw_date = row.get("latest_date")
        if not raw_date:
            continue

        try:
            latest_values.append(
                datetime.strptime(str(raw_date), "%m/%d/%y")
            )
        except ValueError:
            try:
                latest_values.append(
                    datetime.strptime(str(raw_date), "%Y-%m-%d")
                )
            except ValueError:
                pass

    source_chats = set()

    for row in matches:
        source_chats.update(_source_values(row.get("source_chats")))

    latest_date = None

    if latest_values:
        latest_date = max(latest_values).date().isoformat()

    price_available = bool(minimums or medians or maximums)
    enough_plots = len(matches) >= 3

    return {
        "matched_plots": len(matches),
        "observation_count": observations,
        "price_min_pkr": min(minimums) if minimums else None,
        "price_median_pkr": (
            round(median(medians), 2) if medians else None
        ),
        "price_max_pkr": max(maximums) if maximums else None,
        "latest_date": latest_date,
        "distinct_source_chats": len(source_chats),
        "coverage_level": "partial",
        "trust_status": (
            "partial_dataset"
            if enough_plots and price_available
            else "insufficient_data"
        ),
        "answerable_for_demo": bool(enough_plots and price_available),
        "note": (
            "Asking-price observations from the privacy-clean partial "
            "master. Sender-level trust cannot be established from this "
            "master because sender identities/counts are not stored."
        ),
    }


def query_and_summarize(**filters: Any) -> Dict[str, Any]:
    matches = query_inventory(**filters)
    result = summarize_matches(matches)
    result["filters"] = filters
    return result
