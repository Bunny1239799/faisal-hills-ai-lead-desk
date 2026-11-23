"""M11.4 - the unmet-demand log: what the dealers ask for and we do not have.

Why this module exists
-----------------------
Every time the application cannot answer - a thin cell, a parked block, a
cell the approved master does not cover at all - the request is a piece of
sales intelligence. The master file calls it "the hidden gold": after a
couple of weeks the business owner can say exactly what dealers want that
Faisal Hills does not have, and that is real information with **zero
invention** in it.

What is recorded
----------------
Only the **shape** of the request:

* the **size** in marla, or ``None`` when the dealer never said one;
* the **block**, or ``None``;
* the **budget band** - a coarse band, never the exact figure, because a
  band is what a business owner needs and an exact figure identifies a
  buyer.

Never: the message, the dealer's name, a plot number, a note, a raw size,
a sender, a lead id or a phone number. The record is anonymous by
construction: it has no way to carry any of them.

Storage
-------
A **separate** SQLite file of its own (``data/m11_unmet_demand.db`` by
default, overridable with the ``M11_DEMAND_DB`` environment variable), so
the owner's ``faisal_hills.db`` is never touched.

The module is stdlib-only (RULES_SHORT #5), reads nothing, writes nothing
but its own file, and never calls a model.
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

__all__ = [
    "BAND_EDGES",
    "budget_band",
    "UnmetDemandStore",
    "default_store_path",
    "record_unmet_demand",
]


# The coarse budget bands. These are a **display** device, not a price
# rule: no band is ever used to decide whether a price may be shown.
BAND_EDGES = (
    0,
    5_000_000,
    10_000_000,
    15_000_000,
    20_000_000,
    30_000_000,
    50_000_000,
)


def default_store_path() -> str:
    """Where the unmet-demand log lives."""
    return os.environ.get("M11_DEMAND_DB") or os.path.join(
        "data", "m11_unmet_demand.db"
    )


def budget_band(budget: Optional[Dict[str, Any]]) -> Optional[str]:
    """The coarse band of a stated budget.

    Args:
        budget: the budget record - ``{"min_pkr": ..., "max_pkr": ...}`` -
            or ``None``.

    Returns:
        A band label such as ``"5M-10M"``, or ``None`` when no budget
        was stated. The exact figure is never returned.
    """
    if not isinstance(budget, dict):
        return None

    low = budget.get("min_pkr")
    high = budget.get("max_pkr")

    value = None
    if high is not None:
        try:
            value = float(high)
        except (TypeError, ValueError):
            value = None
    if value is None and low is not None:
        try:
            value = float(low)
        except (TypeError, ValueError):
            value = None
    if value is None:
        return None

    for index in range(len(BAND_EDGES) - 1):
        low_edge = BAND_EDGES[index]
        high_edge = BAND_EDGES[index + 1]
        if low_edge <= value < high_edge:
            if high_edge >= 50_000_000:
                return "50M+"
            return "%dM-%dM" % (low_edge // 1_000_000,
                                high_edge // 1_000_000)

    return "50M+"


class UnmetDemandStore:
    """The unmet-demand log, in a SQLite file of its own."""

    def __init__(self, path: Optional[str] = None) -> None:
        self.path = path or default_store_path()

    def _connect(self) -> sqlite3.Connection:
        directory = os.path.dirname(os.path.abspath(self.path))
        if directory and not os.path.isdir(directory):
            os.makedirs(directory, exist_ok=True)
        conn = sqlite3.connect(self.path)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS unmet_demand (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                size_marla   REAL,
                block        TEXT,
                budget_band  TEXT,
                route        TEXT,
                created_at   TEXT NOT NULL
            )
            """
        )
        conn.commit()
        return conn

    def record(
        self,
        size_marla: Optional[float] = None,
        block: Optional[str] = None,
        budget_band_value: Optional[str] = None,
        route: Optional[str] = None,
    ) -> bool:
        """Append one anonymous demand record.

        Only the size, the block, the budget band and the route are
        stored. There is no field for a message, a name or an identifier,
        so the log **cannot** carry private data.
        """
        try:
            conn = self._connect()
        except Exception:
            return False
        try:
            conn.execute(
                "INSERT INTO unmet_demand "
                "(size_marla, block, budget_band, route, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    None if size_marla is None else float(size_marla),
                    None if block is None else str(block).strip().upper(),
                    budget_band_value,
                    route,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            conn.commit()
            return True
        except Exception:
            return False
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def count(self) -> int:
        """How many demand records the log holds."""
        try:
            conn = self._connect()
        except Exception:
            return 0
        try:
            row = conn.execute(
                "SELECT COUNT(*) FROM unmet_demand").fetchone()
            return int(row[0]) if row else 0
        except Exception:
            return 0
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def shapes(self, limit: int = 50) -> List[Dict[str, Any]]:
        """The distinct demand shapes, most recent first.

        A shape is a size, a block and a budget band - nothing else.
        """
        try:
            conn = self._connect()
        except Exception:
            return []
        try:
            rows = conn.execute(
                "SELECT size_marla, block, budget_band, COUNT(*) AS n "
                "FROM unmet_demand "
                "GROUP BY size_marla, block, budget_band "
                "ORDER BY n DESC, id DESC LIMIT ?",
                (int(limit),),
            ).fetchall()
        except Exception:
            return []
        finally:
            try:
                conn.close()
            except Exception:
                pass

        return [
            {
                "size_marla": row[0],
                "block": row[1],
                "budget_band": row[2],
                "count": int(row[3]),
            }
            for row in rows
        ]


def record_unmet_demand(
    lead_state: Optional[Dict[str, Any]] = None,
    route: Optional[str] = None,
    store: Optional[UnmetDemandStore] = None,
) -> Optional[Dict[str, Any]]:
    """Record one unmet demand from a lead state.

    The record is written **only** when the request has a shape - a size,
    a block or a budget. A dealer who has not said anything yet has not
    asked for anything that can be counted, and a record with nothing in
    it is noise.

    Returns:
        The record that was written, or ``None`` when nothing was
        recorded.
    """
    fields = {}
    if isinstance(lead_state, dict):
        fields = lead_state.get("fields") or {}

    def _value(name):
        record = fields.get(name) or {}
        return record.get("value")

    size = _value("size")
    block = _value("block")
    budget = _value("budget")

    if size is None and block is None and budget is None:
        return None

    band = budget_band(budget) if isinstance(budget, dict) else None
    record = {
        "size_marla": size,
        "block": block,
        "budget_band": band,
        "route": route,
    }

    target = store if store is not None else UnmetDemandStore()
    target.record(
        size_marla=size,
        block=block,
        budget_band_value=band,
        route=route,
    )
    return record
