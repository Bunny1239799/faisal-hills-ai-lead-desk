import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _edit_helper import apply  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent.parent

# --- D-07 ---------------------------------------------------------------
BEFORE = '''## D-07 — `controlled_gateway.py` not connected to the master lookup
**Severity:** major (handoff §8 step 5) · **Status:** VERIFIED
**Evidence:** `controlled_gateway.py` contains no `fh_query`/`master_inventory`/`approved_data`/`real-estate-agent`/`price_lookup` reference. It cannot see the inventory, so it cannot route thin data to a human/"not enough data" instead of Qwen inventing an answer.
**Next action:** M4.
'''

AFTER = '''## D-07 — `controlled_gateway.py` not connected to the master lookup — **MITIGATED (M4)**
**Severity:** major (handoff §8 step 5) · **Status:** MITIGATED (M4) · **Owner decision outstanding**
**The conflict:** handoff §8 step 5 asks that `controlled_gateway.py` be connected to the lookup; RULES_SHORT #7 forbids modifying it. Both are in force, and they cannot both be satisfied literally. **M4 did not edit the protected file and did not bypass the restriction.** The full statement is in D-22.
**What M4 did instead:** the lookup was integrated at the point the product actually serves customers — `app/pipeline.py` (`handle_message`, the customer-facing flow) and `app/server.py` (the console API; **not** protected). The handoff's *intent* — thin data must route to a human / "not enough data" with no number, and the model must never invent one — is satisfied and proven there.
**Evidence (M4, measured):** "7 marla Block C" → answer, 21 plots, median PKR 7,900,000. "7 marla Block B" → **not enough data, no number in the reply** (2 listings < 3). "5 marla Block Z" / "10 marla Executive Block" / "7 marla Block D" → **escalated, no number**. "another customer's phone number" → **refused, no number**. `git diff --numstat` for `integration_test.py`, `controlled_gateway.py` and `shadow_mode.py` is **empty**.
**Why it is only a mitigation:** `controlled_gateway.py` itself still has no link to the lookup. If the owner wants the protected file to consult the lookup, that needs explicit approval; the thin wrapper makes it a one-line change once approved.
**Next action:** owner decision — (a) accept the allowed integration point as M4's completion of step 5, or (b) approve a one-time edit to `controlled_gateway.py`.
'''

apply(ROOT / "DEFECTS.md", BEFORE, AFTER)

# --- D-08 ---------------------------------------------------------------
BEFORE2 = '''## D-08 — `price_lookup.py`, `questions.json`, `policies.json` absent
**Severity:** major · **Status:** VERIFIED
**Evidence:** `D:\\AI-Projects\\real-estate-agent\\scripts\\` does not exist; `questions.json` and `policies.json` absent. `real-estate-agent` contains only `approved_data\\` (handoff, `COVERAGE.json`, `master_inventory.jsonl`).
**Impact:** handoff §2 lists `real-estate-agent` as the project folder with `questions.json`, `policies.json`, `approved_data\\`, `scripts\\`, `evaluation\\`, `logs\\`. The functional lookup equivalent lives in the sibling repo (`laya-gateway\\market\\fh_query.py`) — a drift risk if duplicated.
**Next action:** M4 — one shared implementation plus a thin wrapper; owner decision required (Q1 in FH-02: which repo owns it).
'''

AFTER2 = '''## D-08 — `price_lookup.py`, `questions.json`, `policies.json` absent — **RESOLVED (M4)**
**Severity:** major · **Status:** RESOLVED (M4) · **Closed:** 2026-10-21 08:40
**Resolution:**
* `D:\\AI-Projects\\real-estate-agent\\scripts\\price_lookup.py` — the **thin wrapper** at the handoff's named path. It imports the implementation and adds only argument parsing; it reimplements nothing.
* `D:\\AI-Projects\\laya-gateway\\market\\price_lookup.py` — the **single implementation**, inside the git repository.
* `D:\\AI-Projects\\laya-gateway\\config\\questions.json` — the 20 hand-checked questions (13 must-answer, 7 must-not-answer), each with a measured expected match count, observation count and min/median/max.
* `D:\\AI-Projects\\laya-gateway\\config\\policies.json` — the runtime policy: `active_blocks`, `min_listings_for_answer`, the reply template, the price/privacy/lookup/escalation policy.
**Why the split:** `real-estate-agent` is **not** a git repository (`git rev-parse` → "fatal: not a git repository"), so code written there is unversioned and unreviewable. The handoff itself warns that duplicating the lookup across two projects is a drift risk. M4 therefore keeps **one implementation** and a **thin entry point** at the handoff's path. The closeout test `test_handoff_wrapper_agrees_with_the_module` asserts the two return the same median for the same filter, so they cannot drift silently.
**Evidence (M4, measured):** `tools\\evaluate_fh_queries.py` → `MASTER_RECORDS=374 CASES=20 PASSED=20 FAILED=0`. The wrapper and the module both return median 7,900,000 for Block C / 7 marla.
**Next action:** none for D-08. The **ownership** question (which repo owns the lookup and the data long-term — FH-02 Q1) remains an **owner decision**; see D-18.
'''

apply(ROOT / "DEFECTS.md", BEFORE2, AFTER2)
