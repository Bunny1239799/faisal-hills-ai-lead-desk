import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _edit_helper import apply  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent.parent

NEW = '''## D-24 — The customer-facing path crashed when the lookup declined to run — **RESOLVED (M4)**
**Severity:** major · **Status:** RESOLVED (M4) · **Closed:** 2026-10-21 08:40
**Found by:** M4 verification (`tools/m4_verify/verify_robustness.py`), not by the existing suite.
**Symptom:** `app/pipeline.py` did `facts = market_result["facts"]` and then read `facts["facts_source"]`. The lookup returns `facts = None` when it declines to run a lookup at all (`reply_mode = "no_lookup"` — no block, size or feature filter was usable), so the pipeline raised:
`TypeError: 'NoneType' object is not subscriptable` at `app/pipeline.py:718`.
**Reproduced on two ordinary customer questions:**
* "What is the price in Block C?" (a block but no size)
* "What is the price of a 1 kanal plot in Block C?"
A customer question that crashed the handler is a total service failure on that message, and the exception escaped `handle_message()` entirely — the caller got nothing, not even a safe reply.
**Resolution:** the pipeline now checks `if not facts:` and returns a safe, number-free reply with `facts_used = []`, `n = 0`, `level = "insufficient"` and `market_answerable = False`.
**Evidence (M4, measured):** `tools/m4_verify/verify_robustness.py` exercises 21 question shapes → `CRASHES: 0`, `LEAKS: 0`. `tests/test_m4_closeout.py::test_no_lookup_reply_does_not_crash` covers three no-answer questions and asserts the reply exists, carries no price figure and does not claim one.
**Next action:** none for D-24.

## D-25 — The entity extractor's boolean default was applied as a real filter — **RESOLVED (M4)**
**Severity:** major · **Status:** RESOLVED (M4) · **Closed:** 2026-10-21 08:40
**Found by:** M4 verification (`tools/m4_verify/verify_robustness.py`).
**Symptom:** `market.llm_extract.ExtractedEntity` carries `is_corner=False`, `is_boulevard=False` and `is_park_facing=False` as **defaults** when the message says nothing about those features. `_fh_pick()` treats any non-empty value as a real filter, so `is_corner=False` was passed to the lookup as "exclude corner plots".
**Why that is wrong twice over:**
1. the customer never asked about corner plots; and
2. the approved master stores `corner` as **null on 340 of 374 rows** and as `True` on the rest — it never stores `False`. The engine's filter requires an exact match, so `corner=False` matched **0 of the 21** Block C / 7-marla rows.
**Measured effect:** "What is the price of a 7 marla plot in Block C?" — the flagship question — could not be answered. The same question now returns 21 plots, 43 observations, median PKR 7,900,000.
**Resolution:** a feature filter is applied only when the entity says `True` or when the message text mentions the feature. An entity `False` is "not specified", not "exclude".
**Evidence (M4, measured):** `tests/test_m4_closeout.py::test_plain_price_question_is_not_filtered_by_the_extractor_default` (21 plots, median 7,900,000) and `test_explicit_corner_question_is_still_filtered` (3 plots, median 9,600,000) — the fix does not disable a genuine corner filter.
**Next action:** none for D-25. The underlying data limitation (D-13) is unchanged: `corner` is still null on most rows.

## D-26 — The v1 scope was hard-coded in three places — **RESOLVED (M4)**
**Severity:** major · **Status:** RESOLVED (M4) · **Closed:** 2026-10-21 08:40
**Found by:** M4 verification (`tools/m4_verify/verify_scope_authority.py`).
**Symptom:** `config/policies.json` → `active_blocks` was introduced in M4 as "the owner can change a scope rule without touching Python", but the scope was **not** actually read by the customer-facing path. It was hard-coded in `app/policy.py` (`_ACTIVE_BLOCK_CODES = {"A", "B", "C"}`) and again in `app/pipeline.py` (`_fh_classify_block`). The probe proved the split: with `active_blocks` set to `["A","B","C","EXECUTIVE"]` in a temp copy of the config, the **lookup** followed the config while the **customer-facing path** still escalated the Executive Block.
**Why it matters:** a configuration that silently does not work is worse than no configuration — it invites the owner to believe a scope change took effect when it did not.
**Resolution:** one authority. The policy gate, the pipeline's classifier, the lookup and the adapter all read `config/policies.json` → `active_blocks` and canonicalise it through one alias table. The gate no longer caches the scope.
**Evidence (M4, measured):** `tools/m4_verify/verify_scope_authority.py` → `RESULT: the customer-facing path FOLLOWS config/policies.json`. `tests/test_m4_closeout.py::test_configured_scope_is_the_single_authority` asserts the lookup, the policy gate and the customer-facing path all agree; `test_default_scope_is_unchanged_when_config_is_not_relocated` asserts the shipped configuration still scopes the product to A, B, C and that D, E, Z, X, Y and Executive all still escalate.
**Next action:** none for D-26.

## D-27 — Three different spellings for the same block — **RESOLVED (M4)**
**Severity:** major · **Status:** RESOLVED (M4) · **Closed:** 2026-10-21 08:40
**Found by:** M4 verification (`tools/m4_verify/verify_scope_authority.py`).
**Symptom:** the same block was spelled three ways across the project — `"E"` (the policy gate's tokenizer), `"EXECUTIVE"` / `"Executive"` (the approved master's `block` column) and `"EXEC"` (`market/blocks.json` and the entity extractor). The lookup's alias table knew `EXECUTIVE` but not `EXEC`, so a question the extractor had already resolved to `EXEC` was classified out of scope and never reached the lookup. The configured codes were also compared against the requested code **without canonicalising either side**, so a config entry of `"EXECUTIVE"` could never match a requested `"E"`.
A second, related bug: the policy gate **cached** the scope in a module global, so a scope read before the configuration was relocated kept being enforced forever.
**Resolution:** one alias table (`_BLOCK_ALIASES` in `market/price_lookup.py`, exposed as `canonical_block()`), used by the policy gate, the pipeline's classifier, the lookup and the adapter. Configured codes and requested codes are canonicalised through it on both sides. The gate reads the configuration on every call instead of caching it.
**Evidence (M4, measured):** `tests/test_m4_closeout.py::test_policy_scope_is_not_cached` and `test_configured_scope_is_the_single_authority`; the alias table maps `EXEC`, `EXECUTIVE`, `Executive`, `E` and `FHE` all to `E`, and `FHA`/`A` to `A`.
**Next action:** none for D-27.

## D-28 — An M4 test hard-coded the owner's absolute master path — **RESOLVED (M4)**
**Severity:** major · **Status:** RESOLVED (M4) · **Closed:** 2026-10-21 08:40
**Found by:** M4 verification (`tools/m4_verify/verify_ci_portability.py`), which reproduces the GitHub Actions run.
**Symptom:** `tests/test_m4_price_lookup.py::test_lookup_uses_the_approved_master_path` asserted
`price_lookup.MASTER_PATH == Path(r"D:\\AI-Projects\\real-estate-agent\\approved_data\\master_inventory.jsonl")`.
CI relocates the master through `FH_MASTER_PATH` (because the master lives outside the repository), so on CI — and on every other machine — that assertion failed and took the whole job red with it:
`AssertionError: assert WindowsPath('.../evaluation/_ci_master.jsonl') == WindowsPath('D:/AI-Projects/real-estate-agent/approved_data/master_inventory.jsonl')`.
**Resolution:** the test now asserts the **contract** — the lookup uses the master it was configured with, that master exists, and it is the approved 374-plot inventory with no `raw_text` and no `sender` — rather than one machine's path.
**Evidence (M4, measured):** `tools/m4_verify/verify_ci_portability.py` → `EXIT: 0`, 234 passed with `FH_MASTER_PATH` set, exactly as CI runs it.
**Next action:** none for D-28. See D-30 for the remaining CI prerequisite.

## D-29 — The module CLI ignored its arguments — **RESOLVED (M4)**
**Severity:** minor · **Status:** RESOLVED (M4) · **Closed:** 2026-10-21 08:40
**Found by:** M4 verification.
**Symptom:** `market/price_lookup.py`'s `main()` never read `sys.argv`. `python -m market.price_lookup --block C --size-marla 7` printed the 20-question report instead of the lookup, so the usage documented in the M4 checkpoint did not work from the implementation module. (The thin wrapper at the handoff's path had its own argparse and did work — the two entry points disagreed.)
**Resolution:** `main()` now parses the same arguments as the wrapper and behaves identically for both.
**Evidence (M4, measured):** `tests/test_m4_closeout.py::test_module_cli_honours_block_and_size` (asserts `matched_plots=21` and `price_median_pkr=7900000.0`, and that the question report is **not** printed), `test_module_cli_check_questions_still_works` and `test_module_cli_json_output_is_valid_json`.
**Next action:** none for D-29.

## D-30 — `config/` and `market/master_inventory.csv` are untracked, so CI cannot work — **OPEN (owner)**
**Severity:** major · **Status:** OPEN — **owner action required** (commit boundary, D-16)
**Evidence:** `git ls-files config/ market/master_inventory.csv` returns **nothing**. The whole `config/` directory (`policies.json`, `questions.json`) and `market/master_inventory.csv` are untracked. `.github/workflows/ci.yml` reads `market/master_inventory.csv` to build the CI master — so the CI job cannot succeed until that file is committed.
**Why this is not fixed here:** committing is an owner decision (D-16, the commit boundary), and M4's brief explicitly says not to stage or commit. Adding a file to version control is a repository-level decision, not a code change.
**Note:** `market/master_inventory.csv` is **byte-identical** to `D:\\FaisalHills_Master_Data\\07_MASTER\\master_inventory.csv` (SHA256 `fce70e99…`), and the derived CI master was verified to give identical results to the external approved master for all 20 block/size combinations.
**Next action:** **owner** — decide the commit boundary (D-16) and include `config/`, `market/master_inventory.csv` and `market/price_lookup.py` in it. Until then CI is expected to fail at the "Prepare approved master" step.

'''

path = ROOT / "DEFECTS.md"
src = path.read_text(encoding="utf-8")
if "## D-24 —" in src:
    raise SystemExit("ALREADY APPLIED")
path.write_text(src.rstrip("\n") + "\n\n" + NEW, encoding="utf-8", newline="")
print("OK appended D-24..D-30 to %s" % path)
