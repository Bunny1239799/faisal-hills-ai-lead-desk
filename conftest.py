"""M3 test-harness configuration for the Faisal Hills AI Lead Desk.

This file is TEST HARNESS ONLY. It does not change any application logic,
any price computation, any policy rule, or any test assertion. It exists so
that the suite is reproducible on a machine other than the author's.

Two responsibilities:

1. Put the project root on ``sys.path``.
   The test modules import the application packages by their real names
   (``from app.policy import evaluate_policy``,
   ``from market.fh_query import ...``). The project is not installed as a
   package and ``tests/`` has no ``__init__.py``, so the project root must be
   importable. ``pytest.ini`` also sets ``pythonpath = .`` (pytest >= 7.0);
   this is a version-independent safety net for the same guarantee.

2. Isolate the test database from the owner's real database.
   ``data/db.py:get_db_connection()`` resolves its path as
   ``os.getenv("DB_PATH", "faisal_hills.db")`` - a CWD-relative path. The
   pipeline writes a lead, a message and an audit row for every message it
   handles. ``tests/test_step12_matrix.py`` drives ``handle_message()`` 22
   times with no isolation, so without this every test run inserted 22
   leads/messages/audit rows into the REAL ``faisal_hills.db`` in the
   project root. That file is the one holding the 5,867 ``market_listings``
   rows with dealer ``raw_text`` and ``sender`` (D-10).

   Here, ``DB_PATH`` is pointed at a throwaway copy for the whole session,
   so a test run never writes to the project database. The copy is made
   from the project database when one exists, so schema and behaviour match
   the real thing; when none exists a fresh one is created from the schema.

   This is isolation only. It changes no assertion, no policy rule, no
   price computation and no expected value.

3. Relocate the approved master inventory when ``FH_MASTER_PATH`` is set.
   ``market/fh_query.py`` points at the owner machine's absolute path
   (``D:\\AI-Projects\\real-estate-agent\\approved_data\\master_inventory.jsonl``),
   which lives OUTSIDE this repository. On any other machine (CI, a second
   laptop) that path does not exist and 17 of the 155 tests fail with
   ``FileNotFoundError`` - an environment blocker, not a product regression.

   When ``FH_MASTER_PATH`` is set, the master lookup is pointed at that file.
   When it is NOT set - the default, and the situation on the owner machine -
   nothing is patched and behaviour is byte-for-byte unchanged.

Usage on a machine where the master lives elsewhere::

    set FH_MASTER_PATH=D:\\path\\to\\master_inventory.jsonl
    .venv\\Scripts\\python.exe -m pytest -q

The master is only ever READ. Nothing here writes to it, to any database,
or to any dataset.
"""

import os
import shutil
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent

# --- 1. Make the project root importable -------------------------------
_root = str(PROJECT_ROOT)
if _root not in sys.path:
    sys.path.insert(0, _root)

# --- 2. Isolate the test database ---------------------------------------
# Done at import time (not via a fixture) so that EVERY test that opens a
# connection - including module-level or fixture-level code - is covered.
#
# The copy is made from the project database when one exists, so schema and
# behaviour match the real thing. When none exists a fresh one is created
# from data/schema.sql. Note that the project schema does NOT define a
# `messages` table, but app/pipeline.py writes to one, so a schema-created
# database is given that table too - otherwise the pipeline raises
# "no such table: messages" on any message it handles.
_TEST_DB_DIR = tempfile.mkdtemp(prefix="faisal_hills_pytest_")
_TEST_DB_PATH = os.path.join(_TEST_DB_DIR, "faisal_hills.db")

_source_db = None
for _candidate in (
    PROJECT_ROOT / "faisal_hills.db",
    PROJECT_ROOT / "data" / "faisal_hills.db",
):
    if _candidate.is_file():
        _source_db = _candidate
        break

if _source_db is not None:
    shutil.copy2(_source_db, _TEST_DB_PATH)
else:
    # No project database: create one from the schema so the pipeline has the
    # tables it writes to.
    try:
        import sqlite3

        import data.db as _data_db

        _conn = _data_db.init_db(_TEST_DB_PATH)
        _conn.execute(
            """
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                lead_id TEXT,
                message_text TEXT,
                message_timestamp TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        _conn.commit()
        _conn.close()
    except Exception:  # pragma: no cover - schema creation is best effort
        pass

os.environ["DB_PATH"] = _TEST_DB_PATH

# --- 2b. Isolate the side stores ---------------------------------------
# The conversation log (M12), the lead-state and unmet-demand stores
# (M11), the lead pipeline and the pilot-feedback store each live in a
# SQLite file of their own under data/. Every test module that drives
# them monkeypatches its own temporary path; the session-level defaults
# below cover the code paths that do NOT patch (for example an endpoint
# test that posts a conversation without patching M12_LOG_DB). Without
# this, such a run writes its sessions into the owner's demo workspace
# and they appear on the live operator desk (seen 2026-11-21: replay
# gate sessions surfaced in the desk rail during a pytest run).
#
# The stores create their own schema on first use, so fresh empty files
# are enough. Per-test monkeypatches still win; nothing here reads or
# writes the project's demo databases.
for _store_var in ("M11_STATE_DB", "M11_DEMAND_DB", "M12_LOG_DB",
                   "LEAD_PIPELINE_DB", "PILOT_FEEDBACK_DB"):
    if _store_var not in os.environ:
        os.environ[_store_var] = os.path.join(
            _TEST_DB_DIR, _store_var.lower() + ".sqlite")

# --- 2b. Isolate the side stores ---------------------------------------
# The conversation log (M12), the lead-state and unmet-demand stores
# (M11), the lead pipeline and the pilot-feedback store each live in a
# SQLite file of their own under data/. Every test module that drives
# them monkeypatches its own temporary path; the session-level defaults
# below cover the code paths that do NOT patch (for example an endpoint
# test that posts a conversation without patching M12_LOG_DB). Without
# this, such a run writes its sessions into the owner's demo workspace
# and they appear on the live operator desk (seen 2026-11-21: replay
# gate sessions surfaced in the desk rail during a pytest run).
#
# The stores create their own schema on first use, so fresh empty files
# are enough. Per-test monkeypatches still win; nothing here reads or
# writes the project's demo databases.
for _store_var in ("M11_STATE_DB", "M11_DEMAND_DB", "M12_LOG_DB",
                   "LEAD_PIPELINE_DB", "PILOT_FEEDBACK_DB"):
    if _store_var not in os.environ:
        os.environ[_store_var] = os.path.join(
            _TEST_DB_DIR, _store_var.lower() + ".sqlite")


def _ensure_pipeline_tables(db_path):
    """Guarantee the tables ``app/pipeline.py`` writes to exist.

    ``data/schema.sql`` defines ``leads`` and ``audit_log`` but NOT
    ``messages``, and ``app/pipeline.py`` inserts into all three. A database
    built from the schema alone therefore fails the moment the pipeline
    handles a message.

    This helper is applied to whatever database a test actually ends up
    using, including the per-test temporary copies that
    ``tests/test_m2_policy_scope_privacy.py`` creates for itself.
    """
    import sqlite3

    conn = sqlite3.connect(str(db_path))
    try:
        _create_pipeline_tables(conn)
    finally:
        conn.close()


def _create_pipeline_tables(conn):
    """Idempotently create every table the pipeline writes to.

    The schema statements are all ``CREATE TABLE IF NOT EXISTS``, so this is
    safe to run against the project database as well as against an empty
    temporary one. It never drops, alters or deletes anything.
    """
    import data.db as _data_db
    from pathlib import Path as _Path

    schema_path = _Path(_data_db.__file__).resolve().parent / "schema.sql"
    try:
        with open(schema_path, "r", encoding="utf-8") as fh:
            conn.executescript(fh.read())
    except Exception:  # pragma: no cover - schema is present in this repo
        pass

    # `messages` is used by app/pipeline.py but is not in data/schema.sql.
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            lead_id TEXT,
            message_text TEXT,
            message_timestamp TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.commit()


# The session database, and any database a test substitutes for it, must have
# the tables the pipeline writes to.
try:
    _ensure_pipeline_tables(_TEST_DB_PATH)
except Exception:  # pragma: no cover
    pass

# A test module may point DB_PATH at a different file (for example a
# per-test temporary copy that it builds itself). Make sure that file also has
# the required tables, so the pipeline never fails on "no such table".
try:
    import data.db as _data_db

    _original_get_db_connection = _data_db.get_db_connection

    def _patched_get_db_connection(db_path=None):
        conn = _original_get_db_connection(db_path)
        try:
            _create_pipeline_tables(conn)
        except Exception:  # pragma: no cover
            pass
        return conn

    _data_db.get_db_connection = _patched_get_db_connection
except Exception:  # pragma: no cover
    pass


def pytest_sessionfinish(session, exitstatus):
    """Remove the throwaway database directory when the session ends."""
    try:
        shutil.rmtree(_TEST_DB_DIR, ignore_errors=True)
    except Exception:  # pragma: no cover
        pass


# --- 2b. Make the suite independent of the current working directory ----
# Several test modules and the application resolve paths relative to the
# process CWD (e.g. `Path("evaluation/datasets/production/redteam_v1.jsonl")`,
# `open("app/static/index.html")`). Running pytest from anywhere other than
# the project root therefore breaks them.
#
# pytest is always started at the project root in normal use, but pinning the
# CWD makes the suite reproducible from any directory and is what CI needs.
# It changes no test logic and no expected value.
if os.getcwd() != str(PROJECT_ROOT):
    os.chdir(str(PROJECT_ROOT))


# --- 3. Optional master relocation --------------------------------------
_MASTER_ENV = "FH_MASTER_PATH"
# .strip() matters: in cmd.exe, `set FH_MASTER_PATH=C:\x && ...` leaves a
# trailing space in the value, which would otherwise produce a confusing
# "file does not exist" error for a path that does exist.
_configured = (os.environ.get(_MASTER_ENV) or "").strip()

if _configured:
    _master_path = Path(_configured).expanduser()
    if not _master_path.is_file():
        raise FileNotFoundError(
            "%s is set to %r but that file does not exist."
            % (_MASTER_ENV, str(_master_path))
        )
    # Imported here (not at module import) so that the default path - the
    # owner's machine - never triggers this block and never pays the import
    # cost or any side effect.
    import market.fh_query as _fhq

    _original_load_inventory = _fhq.load_inventory

    def _load_inventory(path=_master_path):
        return _original_load_inventory(path)

    _fhq.MASTER_PATH = _master_path
    _fhq.load_inventory = _load_inventory


# --- 4. Isolate the versioned inventory workspace ------------------------
# Stage 1 adds a workspace that can redirect inventory loads. The suite
# must never read the founder's real workspace (a version activated there
# during a pilot session would otherwise silently change what 1,154 tests
# see), so each test session gets a throwaway workspace directory of its
# own. With no version in it - the normal case - resolution falls back to
# the configured master and behavior is identical to before.
#
# An explicitly set FH_INVENTORY_WORKSPACE_DIR is honoured, exactly like
# FH_MASTER_PATH above.
_WORKSPACE_ENV = "FH_INVENTORY_WORKSPACE_DIR"
if not (os.environ.get(_WORKSPACE_ENV) or "").strip():
    _TEST_WORKSPACE_DIR = tempfile.mkdtemp(prefix="faisal_hills_ws_")
    os.environ[_WORKSPACE_ENV] = _TEST_WORKSPACE_DIR
