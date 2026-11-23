import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _edit_helper import apply  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent.parent

# --- DEFECTS.md: update the index row for the M4-closed defects ---------
BEFORE = '''| D-02 | Query-engine scope ownership; eval tool bypasses customer policy path | major | VERIFIED (impact assessed) | M4/M5 |'''

AFTER = '''| D-02 | Query-engine scope ownership; eval tool bypasses customer policy path | major | **RESOLVED (M4)** | closed |'''

apply(ROOT / "DEFECTS.md", BEFORE, AFTER)

BEFORE2 = '''| D-07 | `controlled_gateway.py` has no link to the master lookup (handoff §8 step 5) | major | VERIFIED | M4 |
| D-08 | `real-estate-agent\\scripts\\price_lookup.py` + `questions.json`/`policies.json` absent | major | VERIFIED | M4 |'''

AFTER2 = '''| D-07 | `controlled_gateway.py` has no link to the master lookup (handoff §8 step 5) | major | **MITIGATED (M4)** — protected-file conflict, see D-22 | M4 |
| D-08 | `real-estate-agent\\scripts\\price_lookup.py` + `questions.json`/`policies.json` absent | major | **RESOLVED (M4)** | closed |'''

apply(ROOT / "DEFECTS.md", BEFORE2, AFTER2)

BEFORE3 = '''| D-10 | Root `faisal_hills.db` holds 5,867 `market_listings` with 5,756 non-empty `raw_text` + `sender` column | major | VERIFIED (not customer-reachable) | M4 |'''

AFTER3 = '''| D-10 | Root `faisal_hills.db` holds 5,867 `market_listings` with 5,756 non-empty `raw_text` + `sender` column | major | **RESOLVED (M4)** | closed |'''

apply(ROOT / "DEFECTS.md", BEFORE3, AFTER3)

BEFORE4 = '''| D-18 | Approved master lives outside the repo; suite is not self-contained without `FH_MASTER_PATH` | major | **MITIGATED (M3)**; first-class fix outstanding | M4 |
| D-19 | `run_write_test.py` hangs 30 min on import and is a pytest collection hazard if named explicitly | minor | OPEN (excluded from collection) | M4 |
| D-20 | `data/schema.sql` has no `messages` table, but `app/pipeline.py` inserts into one | minor | **MITIGATED (M3)**; schema outstanding | M4 |
| D-21 | `data/db.py` defaults `DB_PATH` to a CWD-relative path | minor | **MITIGATED (M3)**; app-side fix outstanding | M4 |'''

AFTER4 = '''| D-18 | Approved master lives outside the repo; suite is not self-contained without `FH_MASTER_PATH` | major | **MITIGATED (M3)**; owner decision outstanding (FH-02 Q1) | M9 |
| D-19 | `run_write_test.py` hangs 30 min on import and is a pytest collection hazard if named explicitly | minor | OPEN (excluded from collection) | owner |
| D-20 | `data/schema.sql` has no `messages` table, but `app/pipeline.py` inserts into one | minor | **RESOLVED (M4)** | closed |
| D-21 | `data/db.py` defaults `DB_PATH` to a CWD-relative path | minor | **RESOLVED (M4)** | closed |
| D-24 | Customer-facing path crashed when the lookup declined to run (`TypeError` on `facts = None`) | major | **RESOLVED (M4)** | closed |
| D-25 | Entity extractor's boolean default (`is_corner=False`) applied as a real "exclude corner" filter — made every ordinary price question unanswerable | major | **RESOLVED (M4)** | closed |
| D-26 | The v1 scope was hard-coded in three places; `config/policies.json` did not drive the customer-facing path | major | **RESOLVED (M4)** | closed |
| D-27 | Three different spellings for the same block ("E" / "EXECUTIVE" / "EXEC") across the policy gate, the lookup and the entity extractor | major | **RESOLVED (M4)** | closed |
| D-28 | An M4 test hard-coded the owner's absolute master path — the suite failed on CI and on every other machine | major | **RESOLVED (M4)** | closed |
| D-29 | `python -m market.price_lookup --block C --size-marla 7` ignored its arguments and printed the 20-question report | minor | **RESOLVED (M4)** | closed |
| D-30 | `config/` and `market/master_inventory.csv` are untracked, so CI cannot work until they are committed | major | **OPEN — owner (commit boundary D-16)** | owner |'''

apply(ROOT / "DEFECTS.md", BEFORE4, AFTER4)
