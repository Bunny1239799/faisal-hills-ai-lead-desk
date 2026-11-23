"""Reset the demo workspace to a clean, curated showcase state.

What this tool does, in order:

1. BACK UP first: every SQLite file it is about to touch, plus the
   root ``faisal_hills.db`` archive, is copied to
   ``D:\\FaisalHillsAILeadDesk\\backups\\pre_showcase_<timestamp>\\``.
   The backup is outside the repository so it can never be uploaded by
   accident.
2. WIPE the operator-side stores only: the conversation log, the lead
   state store, the unmet-demand store, the lead pipeline and the
   pilot-feedback store. These hold test-run leftovers (machine session
   ids such as ``m12-1-*`` / ``golden-*``) that made the live desk look
   like a test bench.
3. WIPE the lead/message/audit tables of the DEMO database
   (``data/faisal_hills.db``) - the approved master facts (society,
   blocks, inventory, pricing, fact sources) are NEVER touched.
4. SEED a small curated set of demo conversations through the REAL
   pipeline (``app.turn_pipeline.run_turn`` - the exact code path the
   operator desk uses). Every reply on the desk is therefore the
   application's own validated output, never a handwritten string.

Run it from the repository root:

    .venv\\Scripts\\python.exe tools\\reset_demo_state.py

The desk server should be stopped while this runs.
"""

from __future__ import annotations

import datetime
import shutil
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
BACKUP_ROOT = Path(r"D:\FaisalHillsAILeadDesk\backups")

STORE_DBS = [
    DATA / "m12_conversation_log.db",
    DATA / "m11_lead_state.db",
    DATA / "m11_unmet_demand.db",
    DATA / "lead_pipeline.db",
    DATA / "pilot_feedback.db",
]
DEMO_DB = DATA / "faisal_hills.db"
DEMO_DB_WIPE_TABLES = ("messages", "audit_log", "leads")

# The curated demo conversations. Roman-Urdu and English mixes on
# purpose: this is how dealers actually write. Multi-turn sessions show
# qualification and mid-conversation correction.
DEMO_CONVERSATIONS = [
    ("demo-01-price-query", ["What is the price of a 7 marla plot in Block C?"]),
    ("demo-02-buyer-intro", ["I need a 5 marla plot in Block C"]),
    ("demo-03-budget-given", ["5 marla block c, budget 80 lakh"]),
    ("demo-04-thin-request", ["I need a plot"]),
    ("demo-05-discount-push",
     ["Can you give me 20% discount on a 5 marla plot in Block C?"]),
    ("demo-06-out-of-scope", ["I want a 10 marla plot in Block D"]),
    ("demo-07-full-qualification", [
        "I am looking for a 10 marla plot in Block A for investment",
        "budget around 1 crore",
        "probably next month",
    ]),
    ("demo-08-roman-urdu", ["budget 80 lakh hai"]),
    ("demo-09-availability",
     ["Do you have a 5 marla plot available in Block B right now?"]),
    ("demo-10-correction", [
        "I need a plot in Block B",
        "actually my budget is 12 million",
    ]),
]

OPERATOR = "founder"


def _table_names(conn: sqlite3.Connection) -> list:
    return [row[0] for row in conn.execute(
        "SELECT name FROM sqlite_master"
        " WHERE type='table' AND name NOT LIKE 'sqlite_%'")]


def wipe_all_tables(db_path: Path) -> None:
    """Delete every row from every table of one store database."""
    conn = sqlite3.connect(str(db_path))
    try:
        for name in _table_names(conn):
            conn.execute('DELETE FROM "%s"' % name)
        conn.commit()
        conn.execute("VACUUM")
    finally:
        conn.close()


def wipe_tables(db_path: Path, tables) -> None:
    """Delete the named tables' rows only; everything else stays."""
    conn = sqlite3.connect(str(db_path))
    try:
        existing = set(_table_names(conn))
        for table in tables:
            if table in existing:
                conn.execute('DELETE FROM "%s"' % table)
        conn.commit()
        conn.execute("VACUUM")
    finally:
        conn.close()


def backup(stamp: str) -> Path:
    backup_dir = BACKUP_ROOT / ("pre_showcase_" + stamp)
    backup_dir.mkdir(parents=True, exist_ok=True)
    for db in STORE_DBS + [DEMO_DB]:
        if db.is_file():
            shutil.copy2(db, backup_dir / db.name)
    root_db = ROOT / "faisal_hills.db"
    if root_db.is_file():
        shutil.copy2(root_db, backup_dir / ("ROOT_" + root_db.name))
    return backup_dir


def seed() -> None:
    """Seed the curated conversations through the REAL turn pipeline."""
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))

    from app.turn_pipeline import run_turn
    from market.lead_state import LeadStateStore
    from market.unmet_demand import UnmetDemandStore

    state_store = LeadStateStore()
    demand_store = UnmetDemandStore()

    escalated = set()
    for session_id, messages in DEMO_CONVERSATIONS:
        for text in messages:
            result = run_turn(
                text,
                session_id,
                store=state_store,
                demand_store=demand_store,
            )
            route = result.get("route")
            print("  %-26s %-22s -> %s" % (session_id, text[:22], route))
            if route == "escalate":
                escalated.add(session_id)

    # The escalated demo conversations were taken over by the operator:
    # recorded exactly the way the take-over endpoint records it (state
    # flag + activity action + pipeline flag), so the desk shows the truth.
    from market.conversation_log import ConversationLogStore
    from market.lead_pipeline import LeadPipelineStore

    log_store = ConversationLogStore()
    for session_id in sorted(escalated):
        state_store.mark_taken_over(session_id, operator=OPERATOR)
        log_store.record_action(session_id, "taken_over")
        try:
            LeadPipelineStore().mark_taken_over(session_id)
        except Exception:
            pass
        print("  %-26s taken over by %s" % (session_id, OPERATOR))


def main() -> None:
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    print("1. backup ->", backup(stamp))
    print("2. wiping operator-side stores")
    for db in STORE_DBS:
        if db.is_file():
            wipe_all_tables(db)
            print("   wiped", db.name)
    print("3. wiping demo lead tables (master facts untouched)")
    wipe_tables(DEMO_DB, DEMO_DB_WIPE_TABLES)
    print("4. seeding curated demo conversations")
    seed()
    print("done. The desk now shows the curated demo state.")


if __name__ == "__main__":
    main()
