import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _edit_helper import apply  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent.parent

# --- D-10 ---------------------------------------------------------------
BEFORE = '''**Next action:** M4 — decide explicitly whether the demo may use it (recommend: **no**; keep the master as the only demo source) and quarantine/record the exclusion in `DECISIONS.md`.
'''

AFTER = '''**Resolution (M4):** the answer is **no** — the root database is not a demo or seed source and is now structurally excluded from every demo path.
* `data/db.py` → `DEFAULT_DB_PATH` is `<project root>/data/faisal_hills.db`. The root `faisal_hills.db` is never the default.
* `data/demo_seed.py` → the seed's default is `data/faisal_hills.db` (a path under `data/`, never `parent.parent`).
* `app/server.py` → `/api/market` no longer selects from `market_listings`. It returns the approved-master summary only: counts, price ranges and dates, with no `raw_text` and no `sender`.
* `app/server.py` → `/api/message` returns only the gated, whitelisted fields.
**Evidence (M4, measured):** `tools/m4_verify/verify_no_price_leak.py` → `LEAKS: 0`; `tests/test_m4_integration.py::test_console_market_endpoint_serves_no_raw_dealer_text` asserts `"raw_text" not in blob` and `"sender" not in blob`; `test_demo_seed_never_targets_the_root_database` asserts the seed's default path; `test_root_database_hash_is_unchanged_by_the_m4_suite` asserts the root DB's SHA256 is identical before and after a run. The root DB SHA256 after M4 is `b7504af1…` — **unchanged**, and its 5,867 `market_listings` rows, 1,200 `leads`, 1,200 `messages` and 1,200 `audit_log` rows are **preserved** (D-17 residue is owner-gated).
**Next action:** none for D-10. The exclusion is recorded in `DECISIONS.md` (DEC-38).
'''

apply(ROOT / "DEFECTS.md", BEFORE, AFTER)

BEFORE2 = '''## D-10 — Root DB holds raw dealer text and sender names
**Severity:** major · **Status:** VERIFIED (not customer-reachable)'''

AFTER2 = '''## D-10 — Root DB holds raw dealer text and sender names — **RESOLVED (M4)**
**Severity:** major · **Status:** RESOLVED (M4) · **Closed:** 2026-10-21 08:40'''

apply(ROOT / "DEFECTS.md", BEFORE2, AFTER2)
