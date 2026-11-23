import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _edit_helper import apply  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent.parent

BEFORE = '''## D-08 — `price_lookup.py`, `questions.json`, `policies.json` absent
**Severity:** major (handoff §8 steps 4, and §2 project layout) · **Status:** VERIFIED
**Evidence:** `D:\\AI-Projects\\real-estate-agent\\scripts\\` does not exist; `questions.json` and `policies.json` absent. `real-estate-agent` contains only `approved_data\\` (handoff, `COVERAGE.json`, `master_inventory.jsonl`).
**Impact:** handoff §2 lists `real-estate-agent` as the project folder with `questions.json`, `policies.json`, `approved_data\\`, `scripts\\`, `evaluation\\`, `logs\\`. The functional lookup equivalent lives in the sibling repo (`laya-gateway\\market\\fh_query.py`) — a drift risk if duplicated.
**Next action:** M4 — one shared implementation plus a thin wrapper; owner decision required (Q1 in FH-02: which repo owns it).
'''

AFTER = '''## D-08 — `price_lookup.py`, `questions.json`, `policies.json` absent — **RESOLVED (M4)**
**Severity:** major (handoff §8 steps 4, and §2 project layout) · **Status:** RESOLVED (M4) · **Closed:** 2026-10-21 08:40
**Resolution:**
* `D:\\AI-Projects\\real-estate-agent\\scripts\\price_lookup.py` — the **thin wrapper** at the handoff's named path. It imports the implementation and adds only argument parsing; it reimplements nothing.
* `D:\\AI-Projects\\laya-gateway\\market\\price_lookup.py` — the **single implementation**, inside the git repository.
* `D:\\AI-Projects\\laya-gateway\\config\\questions.json` — the 20 hand-checked questions (13 must-answer, 7 must-not-answer), each with a measured expected match count, observation count and min/median/max.
* `D:\\AI-Projects\\laya-gateway\\config\\policies.json` — the runtime policy: `active_blocks`, `min_listings_for_answer`, the reply template, and the price/privacy/lookup/escalation policy.
**Why the split:** `real-estate-agent` is **not** a git repository (`git rev-parse` → "fatal: not a git repository"), so code written there is unversioned and unreviewable. The handoff itself warns that duplicating the lookup across two projects is a drift risk. M4 therefore keeps **one implementation** and a **thin entry point** at the handoff's path. The closeout test `test_handoff_wrapper_agrees_with_the_module` asserts the two return the same median for the same filter, so they cannot drift silently.
**Evidence (M4, measured):** `tools\\evaluate_fh_queries.py` → `MASTER_RECORDS=374 CASES=20 PASSED=20 FAILED=0`. The wrapper and the module both return median 7,900,000 for Block C / 7 marla.
**Next action:** none for D-08. The **ownership** question (which repo owns the lookup and the data long-term — FH-02 Q1) remains an **owner decision**; see D-18.
'''

apply(ROOT / "DEFECTS.md", BEFORE, AFTER)
