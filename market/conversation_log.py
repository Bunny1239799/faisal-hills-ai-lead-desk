"""M12.2 - the conversation log: what was said, and what the operator did.

What this module is
-------------------
The persistence the operator desk was missing. Every turn the
application handles is recorded (the dealer's own words as the operator
typed them, and the application's own already-validated reply), and so
is every operator action on a draft (sent as is, edited, rejected, an
operator reply, a take-over). The desk can therefore list the
conversations, replay a thread after a reload, and show basic activity
counts.

What this module is NOT
-----------------------
It is **not** an intelligence surface. It decides nothing, it reads no
master row, it serves no market figure and no price: the reply text it
replays is the text the pipeline already validated and already served
for that turn - it is a record, not a new answer. The activity view
carries counts, action names, session ids and times - no message text.

The store lives in a SQLite file of its own (the owner's
``faisal_hills.db`` is never touched) and fails **closed** like the
other stores: a state that cannot be read yields nothing, and a write
that cannot be made returns ``False`` without failing the turn.
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

__all__ = [
    "ACTIONS",
    "ConversationLogStore",
    "default_log_path",
]


# The operator actions the desk records. "taken_over" is recorded by the
# take-over route; the draft actions, the copy and the operator reply by
# the page.
ACTIONS = (
    "sent",
    "edited",
    "rejected",
    "copied",
    "operator_reply",
    "taken_over",
    "followup_approved",
    "followup_edited",
    "followup_rejected",
    "followup_copied",
)


def default_log_path() -> str:
    """Where the M12.2 conversation log lives.

    The environment variable wins, so the tests can point it at a
    temporary file.
    """
    return os.environ.get("M12_LOG_DB") or os.path.join(
        "data", "m12_conversation_log.db"
    )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ConversationLogStore:
    """The turns and the operator actions, in a SQLite file of their own."""

    def __init__(self, path: Optional[str] = None) -> None:
        self.path = path or default_log_path()

    def _connect(self) -> sqlite3.Connection:
        directory = os.path.dirname(os.path.abspath(self.path))
        if directory and not os.path.isdir(directory):
            os.makedirs(directory, exist_ok=True)
        conn = sqlite3.connect(self.path)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS conversation_turns (
                session_id     TEXT NOT NULL,
                turn           INTEGER NOT NULL,
                dealer_message TEXT NOT NULL,
                reply          TEXT NOT NULL,
                route          TEXT NOT NULL,
                escalation     INTEGER NOT NULL DEFAULT 0,
                created_at     TEXT NOT NULL,
                options_json   TEXT,
                PRIMARY KEY (session_id, turn)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS operator_actions (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                action     TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.commit()
        # Showcase readiness (2026-11-22): a database created by an
        # earlier version lacks the options column. ALTER TABLE ADD
        # COLUMN with no default is an instant, safe metadata change.
        columns = {row[1] for row in conn.execute(
            "PRAGMA table_info(conversation_turns)")}
        if "options_json" not in columns:
            conn.execute(
                "ALTER TABLE conversation_turns ADD COLUMN options_json TEXT")
            conn.commit()
        return conn

    # ------------------------------------------------------------------
    # the turns
    # ------------------------------------------------------------------
    def record_turn(self, session_id: str, turn: int, dealer_message: str,
                    reply: str, route: str, escalation: bool,
                    created_at: Optional[str] = None,
                    options: Optional[Any] = None) -> bool:
        """Store one handled turn. Returns ``True`` when it was written.

        ``options`` is the verified-options list the turn served - the
        very list the /api/conversation response carried. It is stored
        as JSON so the transcript can replay it unchanged later.
        """
        if not session_id or turn is None:
            return False
        try:
            conn = self._connect()
        except Exception:
            return False
        try:
            options_json = None
            if options is not None:
                try:
                    options_json = json.dumps(options)
                except (TypeError, ValueError):
                    options_json = None
            conn.execute(
                "INSERT OR REPLACE INTO conversation_turns "
                "(session_id, turn, dealer_message, reply, route, "
                " escalation, created_at, options_json) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (str(session_id), int(turn), str(dealer_message or ""),
                 str(reply or ""), str(route or ""),
                 1 if escalation else 0, created_at or _now(), options_json),
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

    def transcript(self, session_id: str) -> List[Dict[str, Any]]:
        """The turns of a session, oldest first.

        An unknown session yields an empty list; the store never guesses.
        """
        if not session_id:
            return []
        try:
            conn = self._connect()
        except Exception:
            return []
        try:
            rows = conn.execute(
                "SELECT turn, dealer_message, reply, route, escalation, "
                "created_at, options_json FROM conversation_turns "
                "WHERE session_id = ? ORDER BY turn", (str(session_id),)
            ).fetchall()
        except Exception:
            return []
        finally:
            try:
                conn.close()
            except Exception:
                pass
        turns: List[Dict[str, Any]] = []
        for row in rows:
            options: List[Dict[str, Any]] = []
            if row[6]:
                try:
                    decoded = json.loads(row[6])
                    if isinstance(decoded, list):
                        options = decoded
                except ValueError:
                    options = []
            turns.append({
                "turn": row[0],
                "dealer_message": row[1],
                "reply": row[2],
                "route": row[3],
                "escalation": bool(row[4]),
                "created_at": row[5],
                "options": options,
            })
        return turns

    def list_conversations(self, limit: int = 100) -> List[Dict[str, Any]]:
        """The sessions that have at least one recorded turn, newest first.

        Each item carries the session id, the turn count, the last route,
        the last escalation flag, the last activity time and a short
        preview of the last dealer message. No market figure is derived
        here - the preview is the dealer's own words, already visible to
        the operator in the thread.
        """
        try:
            conn = self._connect()
        except Exception:
            return []
        try:
            rows = conn.execute(
                "SELECT session_id, COUNT(*), MAX(turn), "
                "MAX(created_at) FROM conversation_turns "
                "GROUP BY session_id ORDER BY MAX(created_at) DESC "
                "LIMIT ?", (int(limit),)
            ).fetchall()
        except Exception:
            return []
        finally:
            try:
                conn.close()
            except Exception:
                pass

        conversations: List[Dict[str, Any]] = []
        for session_id, turns, _last_turn, last_activity in rows:
            turns_list = self.transcript(session_id)
            if not turns_list:
                continue
            last = turns_list[-1]
            preview = " ".join(str(last["dealer_message"] or "").split())
            if len(preview) > 60:
                preview = preview[:59] + "\u2026"
            # Showcase readiness (2026-11-21): the FIRST dealer words as a
            # title source for the rail. Same class as ``preview`` - the
            # dealer's own words, already visible to the operator in the
            # thread. No market figure is derived here.
            first = turns_list[0]
            first_preview = " ".join(str(first["dealer_message"] or "").split())
            if len(first_preview) > 60:
                first_preview = first_preview[:59] + "\u2026"
            conversations.append({
                "session_id": session_id,
                "turns": turns,
                "route": last["route"],
                "escalation": bool(last["escalation"]),
                "last_activity": last_activity,
                "preview": preview or "No message text",
                "first_preview": first_preview or "No message text",
            })
        return conversations

    # ------------------------------------------------------------------
    # the operator actions
    # ------------------------------------------------------------------
    def record_action(self, session_id: str, action: str,
                      created_at: Optional[str] = None) -> bool:
        """Record one operator action. Returns ``True`` when it was written."""
        if not session_id or action not in ACTIONS:
            return False
        try:
            conn = self._connect()
        except Exception:
            return False
        try:
            conn.execute(
                "INSERT INTO operator_actions "
                "(session_id, action, created_at) VALUES (?, ?, ?)",
                (str(session_id), str(action), created_at or _now()),
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

    def activity(self, limit: int = 20) -> Dict[str, Any]:
        """The activity view: a count per action and the recent events.

        The recent events carry the session id, the action and the time -
        no message text, so the activity view can never become a leak
        surface.
        """
        return {
            "counts": self.action_counts(),
            "recent": self.recent_events(limit),
            "totals": self.totals(),
        }

    def totals(self) -> Dict[str, int]:
        """The M12.5 pilot metrics over the recorded turns: how many
        conversations, how many AI drafts (one per recorded turn) and
        how many escalations. Counts only - no text, no identity."""
        empty = {"conversations": 0, "ai_drafts": 0, "escalations": 0}
        try:
            conn = self._connect()
        except Exception:
            return empty
        try:
            row = conn.execute(
                "SELECT COUNT(DISTINCT session_id), COUNT(*), "
                "COALESCE(SUM(escalation), 0) FROM conversation_turns"
            ).fetchone()
        except Exception:
            return empty
        finally:
            try:
                conn.close()
            except Exception:
                pass
        return {
            "conversations": int(row[0]),
            "ai_drafts": int(row[1]),
            "escalations": int(row[2]),
        }

    def action_counts(self) -> Dict[str, int]:
        try:
            conn = self._connect()
        except Exception:
            return {}
        try:
            rows = conn.execute(
                "SELECT action, COUNT(*) FROM operator_actions "
                "GROUP BY action"
            ).fetchall()
        except Exception:
            return {}
        finally:
            try:
                conn.close()
            except Exception:
                pass
        return {row[0]: row[1] for row in rows}

    def recent_events(self, limit: int = 20) -> List[Dict[str, Any]]:
        try:
            conn = self._connect()
        except Exception:
            return []
        try:
            rows = conn.execute(
                "SELECT session_id, action, created_at FROM "
                "operator_actions ORDER BY id DESC LIMIT ?", (int(limit),)
            ).fetchall()
        except Exception:
            return []
        finally:
            try:
                conn.close()
            except Exception:
                pass
        return [
            {"session_id": row[0], "action": row[1], "time": row[2]}
            for row in rows
        ]

    def actions_for(self, session_id: str) -> List[Dict[str, Any]]:
        """The operator actions recorded for one lead, oldest first."""
        if not session_id:
            return []
        try:
            conn = self._connect()
        except Exception:
            return []
        try:
            rows = conn.execute(
                "SELECT action, created_at FROM operator_actions "
                "WHERE session_id = ? ORDER BY id", (str(session_id),)
            ).fetchall()
        except Exception:
            return []
        finally:
            try:
                conn.close()
            except Exception:
                pass
        return [{"action": row[0], "time": row[1]} for row in rows]

    def actions_between(self, start_iso: str,
                        end_iso: str) -> List[Dict[str, Any]]:
        try:
            conn = self._connect()
        except Exception:
            return []
        try:
            rows = conn.execute(
                "SELECT session_id, action, created_at FROM "
                "operator_actions WHERE created_at >= ? AND created_at <= ? "
                "ORDER BY id", (str(start_iso), str(end_iso))
            ).fetchall()
        except Exception:
            return []
        finally:
            try:
                conn.close()
            except Exception:
                pass
        return [
            {"session_id": row[0], "action": row[1], "time": row[2]}
            for row in rows
        ]

    def turns_between(self, start_iso: str,
                      end_iso: str) -> List[Dict[str, Any]]:
        """The recorded turns in a window (for report aggregation)."""
        try:
            conn = self._connect()
        except Exception:
            return []
        try:
            rows = conn.execute(
                "SELECT session_id, dealer_message, reply, route, "
                "escalation, created_at FROM conversation_turns "
                "WHERE created_at >= ? AND created_at <= ? "
                "ORDER BY session_id, turn",
                (str(start_iso), str(end_iso))
            ).fetchall()
        except Exception:
            return []
        finally:
            try:
                conn.close()
            except Exception:
                pass
        return [
            {"session_id": row[0], "dealer_message": row[1],
             "reply": row[2], "route": row[3], "escalation": bool(row[4]),
             "created_at": row[5]}
            for row in rows
        ]
