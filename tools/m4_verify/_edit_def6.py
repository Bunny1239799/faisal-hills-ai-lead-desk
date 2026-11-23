import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _edit_helper import apply  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent.parent

# --- D-20 ---------------------------------------------------------------
BEFORE = '''## D-20 — `messages` table missing from `data/schema.sql` — **MITIGATED (M3)**
**Severity:** minor · **Status:** MITIGATED (M3) · **Schema outstanding**'''

AFTER = '''## D-20 — `messages` table missing from `data/schema.sql` — **RESOLVED (M4)**
**Severity:** minor · **Status:** RESOLVED (M4) · **Closed:** 2026-10-21 08:40'''

apply(ROOT / "DEFECTS.md", BEFORE, AFTER)

BEFORE2 = '''**Next action:** M4 — add `CREATE TABLE IF NOT EXISTS messages (...)` to `data/schema.sql` so a schema-built database is usable by the pipeline without harness help. The conftest workaround should remain as a safety net, not a requirement.
'''

AFTER2 = '''**Resolution (M4):** `data/schema.sql` now defines `CREATE TABLE IF NOT EXISTS messages (...)` with the columns the pipeline inserts into (`lead_id`, `message_text`, `message_timestamp`, `created_at`). A database built from the schema alone is now usable by the pipeline without harness help; `conftest.py` keeps its idempotent `_create_pipeline_tables()` as a safety net, not a requirement.
**Evidence (M4, measured):** `tests/test_m4_integration.py::test_schema_defines_the_messages_table` asserts the DDL is present, and `test_schema_built_database_can_serve_the_pipeline` builds a database from `data/schema.sql` alone in a temp directory and asserts `messages`, `leads` and `audit_log` all exist.
'''

apply(ROOT / "DEFECTS.md", BEFORE2, AFTER2)

# --- D-21 ---------------------------------------------------------------
BEFORE3 = '''## D-21 — `DB_PATH` default is CWD-relative — **MITIGATED (M3)**
**Severity:** minor · **Status:** MITIGATED (M3) · **App-side fix outstanding**'''

AFTER3 = '''## D-21 — `DB_PATH` default is CWD-relative — **RESOLVED (M4)**
**Severity:** minor · **Status:** RESOLVED (M4) · **Closed:** 2026-10-21 08:40'''

apply(ROOT / "DEFECTS.md", BEFORE3, AFTER3)

BEFORE4 = '''**Next action:** M4 — make the application default to a path anchored at the project root, so behaviour no longer depends on the launch directory. This is the same defect that allowed D-17 to happen.
'''

AFTER4 = '''**Resolution (M4):** `data/db.py` now anchors the database at the **project root**, never at the process working directory. Resolution order:
1. an explicit `db_path` argument;
2. the `DB_PATH` environment variable — an absolute path is used as-is, a **relative** path is resolved against the project root (not the CWD);
3. `DEFAULT_DB_PATH` = `<project root>/data/faisal_hills.db`.
SQLite's `:memory:` DSN is recognised and left alone.
**Evidence (M4, measured):** `tests/test_m4_integration.py::test_db_path_does_not_depend_on_the_working_directory` changes the CWD to a temp directory and asserts the opened file is still `data/faisal_hills.db`; `test_relative_db_path_resolves_against_the_project_root` asserts a relative `DB_PATH` resolves against the project root; `test_default_db_path_is_the_demo_database_not_the_root_database` asserts the default is the demo database and **not** the root database; `test_in_memory_database_still_works` asserts `:memory:` still works.
**Next action:** none for D-21. This was the same defect that allowed D-17 to happen; D-17's harness-side isolation remains in `conftest.py` as a second layer.
'''

apply(ROOT / "DEFECTS.md", BEFORE4, AFTER4)
