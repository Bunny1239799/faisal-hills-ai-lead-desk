import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _edit_helper import apply  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent.parent

# --- DEFECTS.md: replace the D-02 body with the resolved version --------
BEFORE = '''## D-02 — Query-engine scope ownership; eval tool bypasses the customer policy path
**Severity:** major · **Status:** VERIFIED (impact assessed)
**Evidence (2026-10-21 closeout audit):** `tools\\evaluate_fh_queries.py` imports only `from market.fh_query import load_inventory, query_and_summarize`; it does **not** import `app.pipeline.handle_message` nor `app.policy.evaluate_policy` (both confirmed `False` by regex). It writes a JSON report to disk — it is not an API response.
Direct-engine results (bypassing policy): `E/5 marla` → matched=5, answerable=True, median=8,850,000; `OTHER/7` → matched=10, answerable=True; `E/10` → matched=0.
**Customer-facing path (the only one `server.py` uses):** `app\\server.py` → `from app.pipeline import handle_message` → `/api/message` returns only `decision`/`policy_reasons`/`facts_used`/`draft_reply`/`lead_brief`/`demo` from the gated call. Verified 13/13 customer-facing cases safe (needs_human=True, zero price digits, `facts_used=[]`, `market_facts=None`) including Block D/E/Executive/FHD/FHE/X/Y/Z/Prime, injection, stale-quote and 3 PII phrasings.
**Impact:** **No customer can receive an out-of-scope price today** — verified. The defect is architectural: scope enforcement lives in `app\\pipeline.py`, not in the query engine, so *any* future consumer of `market.fh_query` (the eval tool, `tools\\check_trusted_prices.py`, a new script) silently bypasses it. Audit case 20 ("E / 5 marla") therefore reports an Executive price in a developer artifact.
**Next action:** M4/M5 — move the active-block restriction into `market\\fh_query.py` (its natural owner, with `active_blocks` from `market\\config.json`), keep the pipeline guard as defence-in-depth, and make the eval tool assert scope. Decide whether "E / 5 marla" stays an audit case or becomes a documented out-of-scope negative case.
'''

AFTER = '''## D-02 — Query-engine scope ownership; eval tool bypasses the customer policy path — **RESOLVED (M4)**
**Severity:** major · **Status:** RESOLVED (M4) · **Closed:** 2026-10-21 08:40
**Original evidence (M3 closeout audit):** `tools\\evaluate_fh_queries.py` imported only `from market.fh_query import load_inventory, query_and_summarize`; it did **not** import `app.pipeline.handle_message` nor `app.policy.evaluate_policy`. Direct-engine results (bypassing policy): `E/5 marla` → matched=5, answerable=True, median=8,850,000; `OTHER/7` → matched=10, answerable=True.
**Impact as stated then:** *no customer could receive an out-of-scope price* — that part was already true. The defect was architectural: scope enforcement lived in `app\\pipeline.py`, so **any** future consumer of `market.fh_query` or of the public `app.market_adapter.get_verified_market_facts()` silently bypassed it.
**What M4 did:**
1. **One scope rule, one place.** The active-block restriction is now read by the policy gate, the pipeline's classifier, the lookup and the adapter from the **same** configuration (`config/policies.json` → `active_blocks`). Before M4 the scope was hard-coded in three places and the configuration was misleading — changing `active_blocks` did **not** change what the customer-facing path did (proved by probe: the lookup followed the config, the customer path still escalated).
2. **The adapter no longer bypasses the scope.** `get_verified_market_facts()` used to call the query engine directly and priced a parked block: `block E / 5 marla` → matched=5, median=8,850,000, answerable=True. It now applies the same scope restriction and returns a zero-valued fact record for a parked or unknown block.
3. **The eval tool now uses the shared question set and the shared lookup**, so it can no longer answer a question the product would refuse.
**Evidence (M4, measured):**
* `tools/m4_verify/verify_adapter_scope.py` → `adapter block E -> matched=0 median=None answerable=False`; `block C -> matched=47 median=5600000`.
* `tools/m4_verify/verify_scope_authority.py` → `RESULT: the customer-facing path FOLLOWS config/policies.json` (the probe relocates the config to a temp dir; the repository's own config is never modified).
* `tests/test_m4_closeout.py` → 3 tests: the adapter must not price a parked block (7 block spellings), must still answer an in-scope block (C/7 → 21 plots, median 7,900,000), and must exclude parked blocks from a block-less query (A+B+C = 97).
* `app/market_adapter.py` is **not** a RULES_SHORT #7 protected file and was modified.
**Next action:** none for D-02. The scope rule now lives in the configuration and is enforced by every consumer.
'''

apply(ROOT / "DEFECTS.md", BEFORE, AFTER)
