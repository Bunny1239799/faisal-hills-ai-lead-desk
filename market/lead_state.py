"""M11.1 - the lead state: what the dealer has said, and where they said it.

Why this module exists
-----------------------
M9's qualification layer knows the requirements of a conversation, but it
holds them as a flat dict of values with no **provenance**: it cannot say
*which turn* a requirement came from, whether the dealer has since
**changed** it, or which requirements are still **unknown**.

The operator needs exactly that. "The dealer said 8 million on turn 4,
then corrected it to 12 million on turn 6" is a different situation from
"the dealer never said a budget", and the second one is the reason to ask
the next question.

So this module adds a **record**, not a rule:

* five fields - ``size``, ``block``, ``budget``, ``purpose``, ``timeline``;
* each field holds a **value**, a **status** and the **turn** the value came
  from;
* a field that was never stated stays **explicitly unknown** - it is never
  defaulted, guessed or inferred;
* a **correction replaces the old value and records the change**.

What this module does NOT do
----------------------------
It does not decide anything, it does not read the approved master, and it
does not extract anything on its own. The **values** come from
:func:`market.qualify.extract_requirements` - the M9 extractor, which reads
the dealer's own words and nothing else - and the module records where they
came from.

The state is therefore a **cache with provenance**, never a second
authority: where the state and the M9 conversation requirements disagree,
the M9 requirements win.

Storage
-------
The state is kept in a **separate** SQLite file (``data/m11_lead_state.db``
by default, overridable with the ``M11_STATE_DB`` environment variable and
by an explicit argument). The owner's ``faisal_hills.db`` is never touched:
no table is added to it and no residue is removed from it.

The module is stdlib-only (RULES_SHORT #5), reads nothing it did not write,
writes nothing but its own file, and never calls a model.
"""

from __future__ import annotations

import json
import os
import sqlite3
from typing import Any, Dict, List, Optional

__all__ = [
    "FIELDS",
    "STATUS_UNKNOWN",
    "STATUS_STATED",
    "STATUS_CORRECTED",
    "LeadState",
    "LeadStateStore",
    "default_store_path",
    "state_from_requirements",
]


# The five qualification fields the product supports. M9 supports exactly
# these five; this module adds nothing.
FIELDS = ("size", "block", "budget", "purpose", "timeline")

# A field that was never stated.
STATUS_UNKNOWN = "unknown"
# A field the dealer stated.
STATUS_STATED = "stated"
# A field the dealer stated and then CHANGED.
STATUS_CORRECTED = "corrected"


def default_store_path() -> str:
    """Where the M11 lead-state store lives.

    The environment variable wins, so the tests can point it at a
    temporary file and the owner's database is never used.
    """
    return os.environ.get("M11_STATE_DB") or os.path.join(
        "data", "m11_lead_state.db"
    )


def _same_value(left: Any, right: Any) -> bool:
    """Whether two field values are the same requirement.

    ``None`` is only the same as ``None``. A budget is compared as a
    ``(min, max)`` pair, so a budget of 8 million and a budget of
    "up to 8 million" are the same budget, and a budget of 8 million and a
    budget of 12 million are not.
    """
    if left is None or right is None:
        return left is None and right is None
    if isinstance(left, dict) and isinstance(right, dict):
        return (
            left.get("min_pkr") == right.get("min_pkr")
            and left.get("max_pkr") == right.get("max_pkr")
        )
    return left == right


class LeadState:
    """The qualification state of one lead, with its provenance.

    Attributes:
        fields: a dict of field name -> ``{"value", "status", "source_turn"}``.
        turn: the number of the last turn applied to this state.
        changes: the list of corrections, oldest first. Each record is
            ``{"field", "old", "new", "turn"}``.
    """

    __slots__ = ("fields", "turn", "changes")

    def __init__(
        self,
        fields: Optional[Dict[str, Dict[str, Any]]] = None,
        turn: int = 0,
        changes: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        self.fields = fields or {}
        self.turn = int(turn or 0)
        self.changes = list(changes or [])
        for name in FIELDS:
            self.fields.setdefault(name, _unknown_field())

    # -- construction ---------------------------------------------------

    @classmethod
    def empty(cls) -> "LeadState":
        """A state in which **nothing** has been stated.

        Every field is explicitly unknown. This is the fail-closed
        state: a lead whose conversation cannot be read looks exactly
        like a lead that has said nothing, and never like a lead with
        guessed requirements.
        """
        return cls(fields={name: _unknown_field() for name in FIELDS})

    # -- reading --------------------------------------------------------

    def value(self, name: str) -> Any:
        """The current value of a field, or ``None`` when it is unknown."""
        return self.fields.get(name, _unknown_field()).get("value")

    def status(self, name: str) -> str:
        """The status of a field: unknown / stated / corrected."""
        return self.fields.get(name, _unknown_field()).get("status",
                                                           STATUS_UNKNOWN)

    def source_turn(self, name: str) -> Optional[int]:
        """The turn the current value came from, or ``None``."""
        return self.fields.get(name, _unknown_field()).get("source_turn")

    def unknowns(self) -> List[str]:
        """The fields the dealer has **not** stated.

        A missing requirement is a *known unknown*, and it is the reason
        to ask a question - never the reason to assume.
        """
        return [
            name for name in FIELDS
            if self.fields.get(name, {}).get("status") == STATUS_UNKNOWN
        ]

    def corrections(self) -> List[str]:
        """The fields the dealer has corrected."""
        return [
            name for name in FIELDS
            if self.fields.get(name, {}).get("status") == STATUS_CORRECTED
        ]

    # -- writing --------------------------------------------------------

    def apply(self, name: str, value: Any, turn: Optional[int] = None) -> bool:
        """Record a stated value for a field.

        * A field that was **unknown** becomes ``stated``.
        * A field that already holds the **same** value stays ``stated``
          (and its source turn moves to this turn). Restating a
          requirement is not a correction.
        * A field that holds a **different** value is **replaced**: the
          status becomes ``corrected`` and the change is recorded in
          :attr:`changes`.

        Returns:
            ``True`` when this was a correction.
        """
        if name not in FIELDS:
            raise ValueError("%r is not a qualification field." % name)

        turn_number = self.turn if turn is None else int(turn)
        previous = self.fields.get(name, _unknown_field())
        old_value = previous.get("value")
        old_status = previous.get("status", STATUS_UNKNOWN)

        if value is None:
            # Nothing was stated. An unknown field stays unknown; a
            # stated field keeps its value, because a turn that does not
            # mention a requirement does not withdraw it.
            return False

        if old_status == STATUS_UNKNOWN:
            self.fields[name] = {
                "value": value,
                "status": STATUS_STATED,
                "source_turn": turn_number,
            }
            return False

        if _same_value(old_value, value):
            self.fields[name] = {
                "value": old_value,
                "status": STATUS_STATED,
                "source_turn": turn_number,
            }
            return False

        self.fields[name] = {
            "value": value,
            "status": STATUS_CORRECTED,
            "source_turn": turn_number,
        }
        self.changes.append({
            "field": name,
            "old": old_value,
            "new": value,
            "turn": turn_number,
        })
        return True

    # -- serialisation --------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """The state as a plain dict, ready to be served or stored."""
        return {
            "fields": {
                name: dict(self.fields.get(name, _unknown_field()))
                for name in FIELDS
            },
            "turn": self.turn,
            "changes": [dict(change) for change in self.changes],
        }

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "LeadState":
        """Rebuild a state from :meth:`to_dict`.

        A record that cannot be read is **not** an error: it yields an
        all-unknown state, because an unreadable state is unknown, never
        guessed.
        """
        if not isinstance(data, dict):
            return cls.empty()

        raw_fields = data.get("fields")
        if not isinstance(raw_fields, dict):
            raw_fields = {}

        fields: Dict[str, Dict[str, Any]] = {}
        for name in FIELDS:
            record = raw_fields.get(name)
            if not isinstance(record, dict):
                fields[name] = _unknown_field()
                continue
            value = record.get("value")
            status = record.get("status", STATUS_UNKNOWN)
            if status not in (STATUS_UNKNOWN, STATUS_STATED, STATUS_CORRECTED):
                status = STATUS_UNKNOWN
            if value is None:
                status = STATUS_UNKNOWN
            if status == STATUS_UNKNOWN:
                # A record with no status carries no value either: the
                # store fails closed, so a half-written record can
                # never look like a stated requirement.
                value = None
            fields[name] = {
                "value": value,
                "status": status,
                "source_turn": record.get("source_turn"),
            }

        changes = data.get("changes")
        return cls(
            fields=fields,
            turn=int(data.get("turn") or 0),
            changes=[dict(c) for c in changes if isinstance(c, dict)]
            if isinstance(changes, list) else [],
        )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "LeadState(turn=%r, fields=%r)" % (self.turn, self.fields)


def _unknown_field() -> Dict[str, Any]:
    """The record of a field the dealer never stated."""
    return {"value": None, "status": STATUS_UNKNOWN, "source_turn": None}


def state_from_requirements(
    requirements: Optional[Dict[str, Any]],
    previous: Optional[LeadState] = None,
    turn: Optional[int] = None,
) -> LeadState:
    """Build the new lead state from the M9 requirements of one turn.

    The requirements are the ones
    :func:`market.qualify.extract_requirements` produced from the
    dealer's own words. This function only **records** them: it never
    derives a value the extractor did not find, and a field the
    requirements leave empty keeps whatever the previous state held.

    Args:
        requirements: the M9 requirements dict of this turn.
        previous: the state before this turn. ``None`` means a new lead.
        turn: the turn number. Defaults to ``previous.turn + 1``.

    Returns:
        The new state. The previous state's change log is carried over
        and extended.
    """
    state = previous.to_dict() if isinstance(previous, LeadState) else None
    if state is None:
        state = LeadState.empty().to_dict()

    turn_number = turn
    if turn_number is None:
        turn_number = int(state.get("turn") or 0) + 1

    working = LeadState.from_dict(state)
    working.turn = int(turn_number)

    requirements = requirements or {}

    budget_min = requirements.get("budget_min_pkr")
    budget_max = requirements.get("budget_max_pkr")
    budget = None
    if budget_min is not None or budget_max is not None:
        budget = {
            "min_pkr": _as_int(budget_min),
            "max_pkr": _as_int(budget_max),
        }

    working.apply("size", _as_float(requirements.get("size_marla")),
                  turn_number)
    working.apply("block", _as_block(requirements.get("block")), turn_number)
    working.apply("budget", budget, turn_number)
    working.apply("purpose", requirements.get("purpose"), turn_number)
    working.apply("timeline", requirements.get("timeline"), turn_number)

    return working


def _as_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return None


def _as_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_block(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip().upper()
    return text or None


class LeadStateStore:
    """The lead states, in a SQLite file of their own.

    The file is **separate** from the owner's ``faisal_hills.db``: no
    table is added to the owner's database and no residue is removed from
    it. A state that cannot be read yields an all-unknown state - the
    store fails **closed**, exactly like the rest of the product.
    """

    def __init__(self, path: Optional[str] = None) -> None:
        self.path = path or default_store_path()

    def _connect(self) -> sqlite3.Connection:
        directory = os.path.dirname(os.path.abspath(self.path))
        if directory and not os.path.isdir(directory):
            os.makedirs(directory, exist_ok=True)
        conn = sqlite3.connect(self.path)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS lead_state (
                session_id TEXT PRIMARY KEY,
                state_json TEXT NOT NULL,
                updated_at  TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS session_flags (
                session_id    TEXT PRIMARY KEY,
                taken_over_at TEXT NOT NULL,
                operator      TEXT
            )
            """
        )
        conn.commit()
        return conn

    def load(self, session_id: str) -> LeadState:
        """The state of a session.

        An unknown session, an unreadable file or a corrupt record all
        yield an **all-unknown** state. The store never guesses.
        """
        if not session_id:
            return LeadState.empty()
        try:
            conn = self._connect()
        except Exception:
            return LeadState.empty()
        try:
            row = conn.execute(
                "SELECT state_json FROM lead_state WHERE session_id = ?",
                (str(session_id),),
            ).fetchone()
        except Exception:
            return LeadState.empty()
        finally:
            try:
                conn.close()
            except Exception:
                pass

        if not row:
            return LeadState.empty()
        try:
            return LeadState.from_dict(json.loads(row[0]))
        except Exception:
            return LeadState.empty()

    def mark_taken_over(self, session_id: str,
                        operator: Optional[str] = None) -> bool:
        """Record that a human has taken this conversation over.

        The take-over is a **flag**, not a decision about the market: it
        says a person is handling the lead. It is written to the M11
        store, which is a file of its own, so the owner's database is
        not touched.

        Returns ``True`` when the flag was written.
        """
        if not session_id:
            return False
        from datetime import datetime, timezone

        stamp = datetime.now(timezone.utc).isoformat()
        try:
            conn = self._connect()
        except Exception:
            return False
        try:
            conn.execute(
                "INSERT INTO session_flags "
                "(session_id, taken_over_at, operator) VALUES (?, ?, ?) "
                "ON CONFLICT(session_id) DO UPDATE SET "
                "taken_over_at = excluded.taken_over_at, "
                "operator = excluded.operator",
                (str(session_id), stamp, operator),
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

    def taken_over(self, session_id: str) -> Optional[str]:
        """When a human took the conversation over, or ``None``."""
        if not session_id:
            return None
        try:
            conn = self._connect()
        except Exception:
            return None
        try:
            row = conn.execute(
                "SELECT taken_over_at FROM session_flags "
                "WHERE session_id = ?", (str(session_id),)).fetchone()
        except Exception:
            return None
        finally:
            try:
                conn.close()
            except Exception:
                pass
        return row[0] if row else None

    def save(self, session_id: str, state: LeadState) -> bool:
        """Store a state. Returns ``True`` when it was written."""
        if not session_id:
            return False
        from datetime import datetime, timezone

        payload = json.dumps(state.to_dict(), ensure_ascii=False,
                             sort_keys=True)
        stamp = datetime.now(timezone.utc).isoformat()
        try:
            conn = self._connect()
        except Exception:
            return False
        try:
            conn.execute(
                "INSERT INTO lead_state (session_id, state_json, updated_at) "
                "VALUES (?, ?, ?) ON CONFLICT(session_id) DO UPDATE SET "
                "state_json = excluded.state_json, "
                "updated_at = excluded.updated_at",
                (str(session_id), payload, stamp),
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
