import sqlite3
import threading
import time
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, asdict
from enum import Enum, auto

# Lead states
class LeadState(Enum):
    NEW = "new"
    QUALIFIED = "qualified"
    HANDOFF = "handoff"
    SITE_VISIT = "site_visit"
    CLOSED = "closed"
    LOST = "lost"

# Valid transitions
VALID_TRANSITIONS = {
    LeadState.NEW: [LeadState.QUALIFIED, LeadState.LOST],
    LeadState.QUALIFIED: [LeadState.HANDOFF, LeadState.LOST],
    LeadState.HANDOFF: [LeadState.SITE_VISIT, LeadState.LOST],
    LeadState.SITE_VISIT: [LeadState.CLOSED, LeadState.LOST],
    LeadState.CLOSED: [],
    LeadState.LOST: []
}

@dataclass
class Reminder:
    id: Optional[int]
    lead_id: str
    due_at: datetime
    reason: str
    done: bool = False

class LeadManager:
    def __init__(self, db_path: str = "data/laya_gateway.db"):
        self.db_path = db_path
        self._init_db()
        self._scheduler_thread = None
        self._scheduler_running = False

    def _init_db(self):
        """Initialize leads and reminders tables."""
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS leads (
                    id TEXT PRIMARY KEY,
                    state TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS reminders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    lead_id TEXT NOT NULL,
                    due_at TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    done INTEGER NOT NULL DEFAULT 0,
                    FOREIGN KEY (lead_id) REFERENCES leads (id)
                )
            """)
            conn.commit()
        finally:
            conn.close()

    def create_lead(self, lead_id: str) -> None:
        """Create a new lead in NEW state."""
        now = datetime.utcnow().isoformat()
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute(
                "INSERT INTO leads (id, state, created_at, updated_at) VALUES (?, ?, ?, ?)",
                (lead_id, LeadState.NEW.value, now, now)
            )
            conn.commit()
        finally:
            conn.close()

    def get_lead_state(self, lead_id: str) -> Optional[LeadState]:
        """Get current state of a lead."""
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.execute(
                "SELECT state FROM leads WHERE id = ?", (lead_id,)
            )
            row = cursor.fetchone()
            if row:
                return LeadState(row[0])
            return None
        finally:
            conn.close()

    def transition_lead(self, lead_id: str, new_state: LeadState) -> bool:
        """Transition lead to new state if valid."""
        current_state = self.get_lead_state(lead_id)
        if current_state is None:
            return False

        if new_state not in VALID_TRANSITIONS[current_state]:
            return False

        now = datetime.utcnow().isoformat()
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute(
                "UPDATE leads SET state = ?, updated_at = ? WHERE id = ?",
                (new_state.value, now, lead_id)
            )
            conn.commit()
            return True
        finally:
            conn.close()

    def add_reminder(self, lead_id: str, due_at: datetime, reason: str) -> int:
        """Add a reminder for a lead."""
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.execute(
                "INSERT INTO reminders (lead_id, due_at, reason) VALUES (?, ?, ?)",
                (lead_id, due_at.isoformat(), reason)
            )
            conn.commit()
            return cursor.lastrowid
        finally:
            conn.close()

    def get_reminders(self, lead_id: Optional[str] = None, done: Optional[bool] = None) -> List[Reminder]:
        """Get reminders with optional filtering."""
        query = "SELECT id, lead_id, due_at, reason, done FROM reminders WHERE 1=1"
        params = []
        if lead_id is not None:
            query += " AND lead_id = ?"
            params.append(lead_id)
        if done is not None:
            query += " AND done = ?"
            params.append(1 if done else 0)
        query += " ORDER BY due_at"

        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.execute(query, params)
            rows = cursor.fetchall()
            return [
                Reminder(
                    id=row[0],
                    lead_id=row[1],
                    due_at=datetime.fromisoformat(row[2]),
                    reason=row[3],
                    done=bool(row[4])
                )
                for row in rows
            ]
        finally:
            conn.close()

    def mark_reminder_done(self, reminder_id: int) -> bool:
        """Mark a reminder as done."""
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.execute(
                "UPDATE reminders SET done = 1 WHERE id = ?", (reminder_id,)
            )
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    def _scheduler_loop(self):
        """Background thread to check for overdue reminders."""
        while self._scheduler_running:
            try:
                overdue = self.get_reminders(done=False)
                now = datetime.utcnow()
                for reminder in overdue:
                    if reminder.due_at <= now:
                        print(f"[REMINDER] OVERDUE: Lead {reminder.lead_id} - {reminder.reason}")
                time.sleep(30)  # Check every 30 seconds
            except Exception as e:
                print(f"[SCHEDULER] Error: {e}")
                time.sleep(30)

    def start_scheduler(self):
        """Start the reminder scheduler thread."""
        if self._scheduler_thread is None or not self._scheduler_thread.is_alive():
            self._scheduler_running = True
            self._scheduler_thread = threading.Thread(target=self._scheduler_loop, daemon=True)
            self._scheduler_thread.start()
            print("[SCHEDULER] Started reminder scheduler")

    def stop_scheduler(self):
        """Stop the reminder scheduler thread."""
        self._scheduler_running = False
        if self._scheduler_thread:
            self._scheduler_thread.join(timeout=5)
            print("[SCHEDULER] Stopped reminder scheduler")
