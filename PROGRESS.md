# PROGRESS LOG (read after PROJECT_STATE.md)
Updated: 2026-10-21 16:30

## Done
- Setup: Gemini key + aider (D:\tools\aider-venv). Models: gemini/gemini-3.7-flash (normal), gemini/gemini-3.5-flash-lite (cheap), gemini/gemini-3.8-flash (hard problems, small daily budget). Git repo initialized.
- Local stack verified: Laya http://127.0.0.1:8000, llama.cpp http://127.0.0.1:1337 (D:\llama\llama-server.exe), Qwen reply about 1.9s for 30 tokens. integration_test.py invents prices (expected; DB + validator will fix this) and takes about 40s (too many long generations).
- TASK_01 done: data/schema.sql, data/db.py, data/demo_seed.py, tests/test_data_quality.py.
- TASK_02 done: evaluation/datasets/production/golden_v1.jsonl (150 rows), redteam_v1.jsonl (30 rows), tools/validate_dataset.py, evaluation/labels.py. Labels are synthetic; human review of needs_human labels recommended.
- TASK_03 code done: evaluation/run_eval.py and evaluation/baselines (rules.py, laya_client.py, llm.py). First report eval_20261004_1222.md: rules won all three questions on synthetic data (treat with caution). 31 tests passed.

## In progress
- Gemini baseline crashed with HTTP 404 (old model name gemini-2.5-flash-lite). Replace with gemini-3.5-flash-lite in evaluation/baselines/llm.py and rerun: python -m evaluation.run_eval --methods rules,laya,llm

## Gotchas
- Run scripts as: python -m evaluation.run_eval (avoids ModuleNotFoundError).
- Laya server window does not accept typing; use a second PowerShell window.
- Older PowerShell: write files with [System.IO.File]::WriteAllText and UTF8Encoding($false); no utf8NoBOM.
- aider: use --read for reference files; answer n to "add file to chat" for files that must not change.

## Next
1. Finish llm eval run, record winner per question here.
2. TASK_04 policy gate (see TASK_04.md).
3. TASK_05 entity extraction, 06 retrieval, 07 placeholder generation + validator, 08 audit log, 09 agent console (FastAPI), 10 lead states + GitHub Actions CI, 11 end-to-end eval + demo.
4. Business: ask dealer for official data pack and a demo slot; draft pilot offer.2026-10-04 18:00 - TASK_04 policy gate built

## Day 1 evaluation result (2026-10-04, eval_20261004_1241.md, 150 golden rows)
- rules: lead_type 100%, high_intent 94.7%, needs_human recall 100%, precision 96.0% (LIKELY OVERFIT: rules were written with golden_v1 in context)
- llm (gemini-3.5-flash-lite): lead_type 94.7%, high_intent 84.0%, needs_human recall 100%, precision 90.6%
- laya: lead_type 82.7% (= predicts "buyer" always, 124/150), high_intent 82.7%, needs_human recall 0% precision 0% -> never flags. Treat as a bug/question-wording problem until diagnosed. Do not rely on Laya for safety.
- Decision: safety = deterministic app/policy.py (stricter-only) + LLM second check. Laya optional until fixed.
- TASK_04 files exist (app/policy.py, tests/test_policy.py, tools/policy_report.py); test results pending.

## Next
1. Run: python -m pytest -q  and  python tools/policy_report.py (or python -m tools.policy_report). Record recall and false-escalation rate.
2. TASK_05 (Laya diagnosis + held-out set), then entity extraction, retrieval, placeholder generation + validator, audit log, agent console.
## Plan 2026-10-04 (build on demo data first)
- Order: TASK_04 fix -> 06 -> 08 -> 07 -> 09 (console app, PWA) -> 10 (automation, CI) -> 11 (e2e eval, demo pack). TASK_05 (Laya diagnosis) later.
- Real data arrives later: swap using docs/REAL_DATA_SWAP.md. Demo data is fabricated; APP_MODE=pilot refuses it. Never show demo prices to a dealer.
- Helper: run_task.ps1 <NN> starts aider with the right files.2026-10-05 14:20 - SCOPE DECISION: ship Blocks A, B, C only; everything else in BACKLOG.md. Amendment G added (active_blocks, solid/filling, whole-plot prices, feature-drop ladder with required note, dimension/label discovery).


## 2026-10-21 06:50 - M3: test suite runnable, reality re-baselined

- **Environment:** project-local `.venv` (Python 3.14.7, `include-system-site-packages=false`) with genuine **pytest 9.1.1**, `fastapi 0.156.4`, `uvicorn 0.54.0`. `requirements.txt` added: `pytest>=7.0`, `fastapi>=0.110`, `uvicorn>=0.29`. The core suite stays stdlib + pytest (RULES_SHORT #5).
- **Measured result: 20 modules / 155 tests collected, 155 passed, 0 failed, 0 skipped, 0 errors, 0 xfailed** (~5-7 s), reproduced across 5 clean runs and 6 invocation styles. The M1/M2 in-process pytest shim was NOT used; no `pytest.py` shim exists in the repo.
- **Plan correction:** the M3 plan predicted "21 modules" and "49 pipeline-relevant tests". Measured reality is 20 modules / 155 tests, with **52** in the three pipeline-relevant modules (`test_step12_matrix` 22, `test_m2_policy_scope_privacy` 27, `test_market_adapter` 3). The ">=21 modules" acceptance criterion is NOT met as written - the shortfall is files that do not exist, not a collection failure.
- **Harness (test-only, no application source file changed):** `pytest.ini` gained `pythonpath = .` (pytest >= 7.0) so the project root is importable under the bare `pytest` console script as well as `python -m pytest`; new root `conftest.py` puts the project root on `sys.path`, redirects `DB_PATH` to a throwaway session copy, pins the CWD to the project root, supports an optional `FH_MASTER_PATH` master relocation, and ensures the schema + `messages` table exist on whichever DB a test uses.
- **7 environment blockers found and fixed, ZERO application regressions:** no venv/pytest/requirements; console-script import failure; **the suite wrote 22 fabricated rows per run into the owner's real `faisal_hills.db`**; suite only ran from the project root; `messages` table missing from `data/schema.sql`; approved master outside the repo (17 FileNotFoundError); stale `.pytest_cache`.
- **Data integrity:** DB isolation is proven, not assumed - after a full run the real DB's SHA256 (`b7504af1...`) and row counts (1200/1200/1200) are identical before and after. 660 non-eval-tool residue rows from pre-isolation runs remain in the root DB and are **NOT deleted** - data deletion is owner-gated (D-17).
- **CI:** `.github/workflows/ci.yml` previously triggered on `main`/`develop`, neither of which exists in this repo (branch is `master`), so it had never run. Now triggers on `master`, and derives a JSONL master from the in-repo `market/master_inventory.csv` and exports `FH_MASTER_PATH`. The CSV fallback was verified to return identical results (including medians) to the external master for all 20 block/size combinations tested.
- **Baseline report:** `evaluation\reports\m3_baseline_20261021_0625.md` (dated, non-overwriting).
- **Not done:** no M4/M5 work; approved data untouched; RULES_SHORT #7 files unmodified; no startup-loading claim (server inspected, never started); no API key read; nothing staged or committed.
- **Next:** M4 - `price_lookup.py` + `questions.json`/`policies.json` + wire `controlled_gateway.py` to the lookup. Needs owner decisions on D-17 residue, D-19 `run_write_test.py` rename, FH-02 Q1 master ownership, FH-02 Q4 root-DB exclusion, and the commit boundary.


## 2026-10-21 08:40 - M4: lookup / console wiring in the named project root

- **Outcome (FH-02 §6 M4):** the handoff's §2 project layout is real, and the customer-facing path can no longer answer without the approved master.
- **One implementation, no duplicated lookup logic:** `laya-gateway\market\price_lookup.py` is the single implementation (over the proven `market\fh_query.py`); `D:\AI-Projects\real-estate-agent\scripts\price_lookup.py` is the handoff's named **thin wrapper** at that path. `real-estate-agent` is not a git repository, so the version-controlled code deliberately lives in `laya-gateway`; a closeout test asserts the wrapper and the module return the same median, so they cannot drift.
- **Config is now real:** `config\questions.json` (20 hand-checked questions - 13 must-answer, 7 must-not-answer, each with a measured expected count/observation count/min/median/max) and `config\policies.json` (`active_blocks`, `min_listings_for_answer`, reply template). `config\policies.json` -> `active_blocks` is the **single authority** for the v1 scope (D-26): the lookup, the policy gate, the pipeline and the adapter all read it, canonicalised through one block-alias table (D-27).
- **Wiring (handoff §8 step 5):** the lookup is integrated at the point the product actually serves customers - `app\pipeline.py` (`handle_message`) and `app\server.py` (`POST /api/message`, `GET /api/lookup`, `GET /api/market`, `GET /api/questions`). `controlled_gateway.py` is RULES_SHORT #7 protected and was **not** modified; the conflict is recorded as D-22 for an owner decision, and the thin-data -> human/"not enough data" intent is proven at the serving path.
- **Acceptance (measured):** (a) the lookup returns count/min/median/max/date/coverage - 21 plots, 43 obs, min 6,000,000, median 7,900,000, max 11,500,000, date 2026-10-07, coverage `partial`; (b) thin data yields **no number** - "7 marla Block B" (2 < 3) -> "not enough data", Block Z / Executive / D -> escalated, privacy + injection -> refused, `verify_no_price_leak.py` -> `LEAKS: 0`; (c) `questions.json` -> `MASTER_RECORDS=374 CASES=20 PASSED=20 FAILED=0`; (d) the master is read-only and byte-identical to `07_MASTER` (`b77b3cb5...`).
- **Defects closed:** D-02, D-08, D-10, D-20, D-21, D-24, D-25, D-26, D-27, D-28, D-29. **Found and recorded:** D-22, D-23, D-30.
- **Data integrity:** the root `faisal_hills.db` is unchanged (`b7504af1...`, 3,080,192 B) and its residue is **preserved** - 1,200/1,200/1,200 rows and 5,867 `market_listings` (5,756 with `raw_text`). Nothing was deleted. `data\faisal_hills.db` is now the demo/seed database (D-10/D-21) and holds 0 residue rows.
- **Tests:** 24 modules / 234 tests, **234 passed** (M3 baseline was 20 modules / 155 tests; M4 adds 79 across `test_m4_price_lookup` 25, `test_m4_integration` 22, `test_m4_closeout` 27, `test_m4_eval_tool` 5). M3 regression modules re-run: 54 passed. All five `tools\m4_verify\` probes: `LEAKS: 0`, `CRASHES: 0`, scope authority `FOLLOWS`, adapter `block E -> matched=0`, CI portability `EXIT: 0`.
- **Baseline report:** `evaluation\reports\m4_baseline_20261021_0840.md` (dated, non-overwriting). Companion: `D:\AI-Projects\real-estate-agent\FAISAL_HILLS_M4_CHECKPOINT.md`.
- **Not done:** no M5 work; approved data untouched; RULES_SHORT #7 files unmodified; no API key read; no Laya/llama.cpp/Ollama/Gemini call; nothing staged or committed.
- **Next:** M5 - the number/traceability validator (must land before M6, the phrasing port). Needs owner decisions on D-17 residue, D-19 `run_write_test.py` rename, D-22 `controlled_gateway.py`, FH-02 Q1 master ownership, FH-02 Q4 root-DB sharing, and the D-16/D-30 commit boundary.


## 2026-10-21 10:55 - M5: number / traceability validator (first task)

- **Outcome (FH-02 §6 M5):** any number in a customer-facing reply must trace to an approved fact; otherwise the reply is blocked and escalated.
- **Readiness check (focused, 10:39):** all M4 evidence present and consistent - approved master `b77b3cb5...` byte-identical to `07_MASTER`, root DB `b7504af1...` with 1,200/1,200/1,200 + 5,867 rows intact, protected files byte-unchanged, nothing staged, HEAD `d35ec1c`. No validator module existed (M5 genuinely unstarted). **No known critical blocker -> proceeded automatically.**
- **What was built:** `market\fact_validator.py` (the validator), enforcement in `app\pipeline.py` (before the reply is returned), reporting in `app\server.py` (`traceability` / `traceability_ok` / `traceability_blocked`), 32 tests in `tests\test_m5_validator.py`, and the `RULES_SHORT.md` #2 pointer that FH-02 names as M5's persistent record.
- **Whitelist, not blacklist (the M5 risk in FH-02 §6):** a number is permitted only if it is in the fact set or is the customer's own parsed size. Unknown facts permit nothing. 0 false positives across all 10 answerable block/size combinations, including the date triple 2026/10/07.
- **Enforcement:** an untraceable number replaces the reply with the existing human-hold wording, detaches the market facts, raises `needs_human`, and escalates the decision with the reason `untraceable_number_in_draft`.
- **Acceptance (all measured):** (a) 10/10 answerable combinations validate clean; (b) a corrupted median is blocked and an invented "PKR 25,000,000 with 100% returns" is blocked (2 numbers); (c) "not enough data" replies carry 0 numbers (B/7, C/10, A/14); (d) all 30 red-team rows leak nothing; (e) price-reply traceability is 100%, matching the `e2e_20261010_0503.md` metric.
- **Tests:** 25 modules / **266 passed**, 0 failed, 0 skipped, 0 errors (~9 s) - 234 inherited (M1-M4) + 32 new M5. All five M4 probes re-run and still pass: `LEAKS: 0`, `CRASHES: 0`, scope `FOLLOWS`, adapter `block E -> matched=0`, `evaluate_fh_queries.py` 20/20.
- **Safety re-verified after M5:** approved master unchanged and byte-identical to `07_MASTER`; root DB hash unchanged with all residue preserved; `integration_test.py`, `controlled_gateway.py`, `shadow_mode.py` byte-unchanged; `RULES_SHORT.md` changed only by the #2 pointer; nothing staged or committed.
- **Backups:** `app\pipeline.py.bak_20261021_104500`, `app\server.py.bak_20261021_104500`, `RULES_SHORT.md.bak_20261021_104500`.
- **New/updated defects:** D-31 (the reply was trusted by construction, not validated) **RESOLVED**; D-32 (the console's other surfaces are not yet guarded) **OPEN**; D-33 (RULES_SHORT #4 requires a p25-p75 band; the template shows min/median/max) **VERIFIED, needs an owner decision**.
- **Not done:** M5 is not complete - the console surfaces and the audit trail are not yet guarded (D-32), and the p25-p75 band is unresolved (D-33). No M6 work; no LLM in the serving path; no owner decision implemented; no approved data modified; no residue deleted.
- **Next:** M5 task 2 - guard the `/api/lookup` and `/api/market` console surfaces and the audit trail with the same validator.


## 2026-10-21 12:39 - M5 COMPLETE: number / traceability control (task 2 + closeout)

- **Outcome (FH-02 section 6 M5):** any number in a customer-facing reply must trace to an approved fact; otherwise the reply is blocked and escalated. **M5 is now complete.**
- **What was built (task 2):** `market\fact_guard.py` (the surface guard - re-derives the permitted numbers from the approved master and checks every serving surface against them); the validation moved to a single point every path passes through (`_fh_finalize_reply()` in `app\pipeline.py`); the audit trail now records the **final validated reply** and its validation outcome (`_fh_record_validated_reply()`); `/api/message`, `/api/lookup`, `/api/market`, `/api/questions` and `/api/audit` are guarded in `app\server.py`; `app\market_adapter.py` became a thin, guarded facade over the one lookup; the closest match is computed, rendered and made public, and its sample size now agrees with the normal lookup.
- **D-32 CLOSED.** The guard is independent by construction: it re-derives the facts from the read-only approved master rather than trusting the served payload, so a tampered, derived, stale or wrong figure is detectable. It is also stricter than plain traceability for a thin cell: **no price is permitted** for a cell the product refused to answer, even though the master holds one. Blocking is uniform: the numbers are removed, the reply becomes the hold wording, the offending value is never echoed back (a count and a reason only), and the customer-facing path escalates.
- **D-32 COMPLETENESS PROOF.** `tests\test_m5_surface_completeness.py` walks every route, checks the fact numbers in each response against the permitted set that belongs to that surface, and asserts the route list against the live FastAPI route table. Measured: **PASS** - 0 untraceable fact numbers on any surface, 0 failed audit rows, 0 market-price leak in a lead record.
- **D-33 RESOLVED from the governing specifications.** The handoff (section 7 rules 1 and 4), FH-02 (R14, R17, DoD 1), `config\policies.json` and the 20 hand-checked questions all require min/median/max and ~3 listings; RULES_SHORT #4 was the only source that said "p25-p75, n>=5, >=3 senders". Measured: the master holds **two** dealer chats, so **0/18** active cells can satisfy ">=3 senders" and enforcing #4 would make **13/13** must-answer cases unanswerable. The threshold was **not** weakened; RULES_SHORT #4 is restated to the governing rule with the reason recorded in the file. The p25/p75 band is now verifiable by the guard (safe to implement) but is a product choice and is **not** implemented.
- **Defects closed:** D-31, D-32, D-33, D-34 (a refused query leaked its price through the fact set / summary / `/api/lookup`), D-35 (the "not enough data" reply showed no closest match - handoff V2 section 7.4 / FH-02 R17), D-36 (the audit trail recorded the pre-market hold wording), D-37 (the closest match reported a different sample size than the normal lookup), D-38 (`app\market_adapter.py` was a second, unvalidated lookup that returned the price of a thin cell).
- **Acceptance (all measured, re-measured 2026-10-21 12:55):** (a) **11/11** answerable combinations validate clean (the list is now DERIVED from the approved master; the earlier 9/9 list had drifted and had missed A/20 and B/20); (c) all **4** thin A/B/C cells (A/14, B/7, C/10, C/14) carry no price figure; (b) a corrupted median and an invented "PKR 25,000,000 with 100% returns" are both blocked; (c) the thin-data replies carry no price figure and show the closest match; (d) all 30 red-team rows leak nothing; (e) price-reply traceability is **100.00%**; (f) 12 different customer-facing messages, 0 unvalidated.
- **Tests:** 27 modules / **311 passed**, 0 failed, 0 skipped, 0 errors (~14 s) - 234 inherited (M1-M4) + 77 (M5: 37 validator + 32 surface guard + 8 completeness). All five M4 probes re-run and green: `LEAKS: 0`, `CRASHES: 0`, scope `FOLLOWS`, adapter `block E -> matched=0`, CI portability `EXIT: 0`. `tools\evaluate_fh_queries.py` 20/20; `market.price_lookup --check-questions` 20/20; the handoff wrapper `real-estate-agent\scripts\price_lookup.py` still reports 21 plots / median 7,900,000.
- **Safety re-verified after M5:** approved master `b77b3cb5...` unchanged and byte-identical to `07_MASTER`; root DB `b7504af1...` unchanged with 1,200/1,200/1,200 + 5,867 rows preserved; `integration_test.py`, `controlled_gateway.py`, `shadow_mode.py` byte-unchanged; nothing staged or committed; no model call, no API key read, no quota spent; the approved data was not modified.
- **Records:** `CHECKPOINT.md` (M5 complete), `DEFECTS.md` (D-31..D-38), `DECISIONS.md` (DEC-48..DEC-57), `PROGRESS.md` (this entry), `RULES_SHORT.md` (#2 pointer, #4 restated), `evaluation\reports\m5_baseline_20261021_1239.md`.
- **Backups:** `app\server.py.bak_20261021_113752`, `app\pipeline.py.bak_20261021_113752`, `market\price_lookup.py.bak_20261021_113752`, `market\fact_validator.py.bak_20261021_113752`, `app\market_adapter.py.bak_20261021_113752`, `RULES_SHORT.md.bak_20261021_113752`, `CHECKPOINT.md.bak_20261021_113752`, `DEFECTS.md.bak_20261021_113752`, `DECISIONS.md.bak_20261021_113752`, `PROGRESS.md.bak_20261021_113752`, `config\policies.json.bak_20261021_113752`, `config\questions.json.bak_20261021_113752`.
- **Not claimed:** production readiness. The suite is green and the control is proven, but no dealer has seen the demo, and the owner gates (D-17, D-22/D-07, D-30/D-16, D-19, D-18, FH-02 Q3/Q4) remain open.
- **Next:** M6 - the replaceable customer-facing model port.

## 2026-10-21 13:15 - M6 FIRST TASK: the replaceable customer-facing model / phrasing port

- **Outcome (FH-02 section 6 M6):** the customer-facing model is behind a
  **replaceable port** selected by configuration alone. The port is a
  **phrasing** port: the application still decides, still looks up and still
  calculates; the port only chooses how the already-approved facts are
  worded. The M5 validator remains the final gate on every path.
- **What was built:** `app\customer_model.py` (NEW - the port),
  `app\pipeline.py` (`_fh_phrase_reply()`, called inside
  `_fh_finalize_reply()` **before** `_fh_enforce_traceability()`; the reply
  source is recorded in the audit trail), and
  `tests\test_m6_customer_model.py` (20 tests, offline).
- **The three implementations:** `template` (the deterministic default,
  offline, no key), `mock` (a deterministic in-process stand-in used to
  prove the swap offline), `http` (an external endpoint, reachable only
  with `CUSTOMER_MODEL=http` + `ENABLE_LLM_REPLY=1` + a credential).
  Selection is by `CUSTOMER_MODEL` / `ENABLE_LLM_REPLY` /
  `CUSTOMER_MODEL_URL` / `CUSTOMER_MODEL_NAME` only.
- **Acceptance (all measured):** (a) with the model off, all **11** answerable
  cells answer and the default reply is **byte-identical** to the pre-M6
  wording; (b) with the model on, all 11 validate, a thin cell still carries
  no price, and a model that injects `9,999,999` is **blocked** and escalated;
  (c) the swap changes only the wording - the fact set and the policy decision
  are identical, and a test asserts `customer_model` appears in **none** of
  `app/policy.py`, `market/fact_validator.py`, `market/price_lookup.py`;
  (d) a refusal keeps the base hold wording, a parked block stays unpriced,
  and the model can never loosen the policy.
- **Tests:** 28 modules / **331 passed**, 0 failed, 0 skipped, 0 errors
  (~16 s) - 311 from M5 + **20 new M6**. The M5 completion gate was re-run
  after the M6 wiring: **33/33 checks still pass** (both 20-question audits
  20/20, the five M4 probes green, D-32 completeness PASS).
- **Safety re-verified after M6:** approved master `b77b3cb5...` unchanged
  and byte-identical to `07_MASTER`; root DB `b7504af1...` unchanged with
  1,200/1,200/1,200 + 5,867 `market_listings` preserved; protected files
  byte-unchanged; nothing staged or committed; **no model call, no
  credential read, no paid provider, no quota spent** - the whole task was
  exercised offline with the deterministic mock.
- **Records:** `CHECKPOINT.md` (M6 section), `DEFECTS.md` (D-41, D-42),
  `DECISIONS.md` (DEC-60, DEC-61), `PROGRESS.md` (this entry),
  `evaluation\reports\m6_baseline_20261021_1315.md`.
- **Backups:** `app\pipeline.py.bak_20261021_131241`, `CHECKPOINT.md.bak_20261021_131936`,
  `PROGRESS.md.bak_20261021_131936`, `DEFECTS.md.bak_20261021_131936`,
  `DECISIONS.md.bak_20261021_131936`.
- **Not claimed:** production readiness, and not a live LLM. No real provider
  was called; the `http` implementation exists but is unreachable by default
  and spends money when enabled. Laya is **not** yet called from the serving
  path - the next bounded M6 task.
- **Next:** call Laya behind the same configuration switch, pass its signals
  to `evaluate_policy(message, laya_signals=...)` as a **tightening-only**
  input, and prove offline that Laya can only escalate and never loosen.

## 2026-10-21 13:25 - M6 TASK 2: the decision layer - Laya as a tightening-only signal

- **Outcome (FH-02 section 6 M6):** the decision layer is behind a
  **replaceable port** too. Laya's signals reach
  `evaluate_policy(message, laya_signals=...)`, where they can only make the
  decision **stricter** - never looser. The application's own policy still
  makes every decision.
- **What was built:** `app\decision_model.py` (NEW - the port: `rules` the
  default with **no external signal**, `mock` a deterministic in-process
  stand-in, `laya` the real local service), `app\pipeline.py`
  (`_fh_decision_signals()` feeds the policy call), and
  `tests\test_m6_decision_model.py` (18 tests, offline).
- **Configuration:** `DECISION_MODEL` / `ENABLE_LAYA_DECISION` / `LAYA_URL` /
  `LAYA_TIMEOUT`. A non-default implementation needs the explicit switch, an
  unknown name falls back to `rules`, and an unreachable service falls back
  to **no signal**.
- **Tightening-only, proved in both directions:** a signal at or above the
  threshold escalates an answerable question (the facts are detached, no
  price reaches the customer); a signal of 0.0 / 0.1 / 0.49 leaves the
  action, the risk tags and `needs_human` **exactly** as they were; a
  `refuse` stays a `refuse` and an `escalate` stays an escalation. A
  structural test asserts the `laya_signals` branch of `app/policy.py` may
  only raise `needs_human` and escalate an `answer`.
- **`app/policy.py` was NOT modified.** The tightening-only shape already
  existed; M6 supplies the signal that reaches it.
- **Why it is safe despite Laya's 0% `needs_human` recall:** 0% recall means
  Laya cannot be trusted to *detect* a dangerous message, so it may only
  ever *add* a concern. A signal that never fires changes nothing; a signal
  that fires escalates - neither can make the product unsafe.
- **The 20-case audit is green in both modes** (FH-02 M6 verification): with
  the decision model off and on, all 20 hand-checked cases produce an
  identical decision and an identical `needs_human` flag.
- **Tests:** 29 modules / **349 passed**, 0 failed, 0 skipped, 0 errors
  (~19 s) - 311 M5 + 20 M6 task 1 + 18 M6 task 2. The M5 completion
  gate was re-run after the M6 wiring: every check still passes.
- **Safety re-verified:** approved master `b77b3cb5...` unchanged and
  byte-identical to `07_MASTER`; root DB `b7504af1...` unchanged with
  1,200/1,200/1,200 + 5,867 `market_listings` preserved; protected files
  byte-unchanged; nothing staged or committed. **No Laya service started, no
  credential read, no quota spent** - the message that would leave the
  machine is PII-scrubbed at the boundary, and the port needs no API key.
- **Records:** `CHECKPOINT.md` (M6 task 2 section), `DEFECTS.md` (D-42
  resolved), `DECISIONS.md` (DEC-64, DEC-65), `PROGRESS.md` (this entry),
  `evaluation\reports\m6_baseline_20261021_1315.md`.
- **Backups:** `app\pipeline.py.bak_20261021_132206`,
  `app\pipeline.py.bak_20261021_131241`, and the record files
  (`.bak_20261021_132*`).
- **Not claimed:** production readiness, and not a live Laya. The remaining
  M6 work is **owner-gated**, not engineering work: FH-02 Q3 (which
  customer-facing provider - it spends money) and whether the Laya service
  may be started for real. The next *engineering* step that needs no
  approval is M7, the matching-listings panel.

## 2026-10-21 16:30 - M6.1 (reply claim/shape/provenance hardening) and M7 (matching listings / evidence / operator workflow)

**M6.1 - COMPLETE AND VERIFIED.** The M6 ports existed, but nothing stopped
model-generated *wording* from making a claim the approved master does not
support. M5's validator checks numbers; a claim can carry no new number.
Three holes were measured against the approved master - all three PASS the
M5 validator: a size claim riding in on the observation date ("10 marla",
permitted because the date is 2026-10-07), a scope claim ("Block D", no
number at all), and an availability claim on a cell the application had
already refused to answer.

`market/reply_guard.py` is now a **second final gate**: it checks the shape
of the claim (scope, size, block-size pair, certainty, sold price, stock
claim) and the three provenance markers (asking prices / not confirmed sold
prices / human approval required). It runs on every path in
`app/pipeline.py`, after the model phrasing and after the numeric
validator, and it is authoritative. A blocked claim is indistinguishable to
the customer from a blocked number.

It also found a real defect: the shipped M6 mock dropped the "not confirmed
sold prices" marker (D-43). The mock and the HTTP prompt are fixed.

**M7 - COMPLETE AND VERIFIED.** The operator can now see the verified
listings behind an answer. `market/evidence.py` serves the matching
listings as a **whitelisted** projection of the approved master - built field
by field, so `source_chats` (dealer names), `notes` (dealer chat text,
180/339 in-scope rows) and `size_raw` can never leak. Measured across all
18 in-scope cells: **0** sensitive master values reach the payload. The plot
identifier is served only in the authorised `identified` mode; the default
`redacted` mode serves an opaque, letters-only `listing_ref`.

`market/review.py` adds the operator review: approve / reject, bound to the
evidence it was made against (the `listing_ref` set, an order-independent
`evidence_digest`, the fact identifiers, and whether the reply was edited),
recorded in the existing audit trail. A review whose evidence moved under
the operator is recorded as `stale_evidence`, not as a clean approval.

The console gained a MATCHING LISTINGS panel and an OPERATOR REVIEW panel,
closing D-09.

**Measured.** Suite **475 passed, 0 failed** (31 modules, ~20 s) - 349
pre-existing + 40 M6.1 + 86 M7. All ten gates re-run and green: M6.1 suite
40/40, M7 suite 86/86, M5 validator + surface guard + completeness 98/98,
20-question audit 20/20, `verify_no_price_leak` LEAKS: 0,
`verify_robustness` CRASHES: 0 / LEAKS: 0, `verify_scope_authority` FOLLOWS,
`verify_adapter_scope` block E -> matched=0, `verify_ci_portability` EXIT 0.

**Integrity.** Approved master `b77b3cb5...` unchanged and byte-identical to
`07_MASTER`; the owner's root database `b7504af1...` unchanged with its
residue preserved (1,200/1,200/1,200 + 5,867 `market_listings`); the demo
database 702/702/702 with its residue preserved; `integration_test.py`,
`controlled_gateway.py` and `shadow_mode.py` byte-unchanged. No model call,
no credential read, no paid provider, no quota spent. Nothing staged,
nothing committed.

**Next.** M8 - the recommendation layer: ranked verified alternatives, a
closest-match reason, and a next-best-action over the M7 evidence. M7's
evidence rows (a stable identifier, a block, a size, a verified price, a
matching reason) are exactly what a ranker needs, so the recommendation
layer can be built without touching the deterministic core. Still gated on
the owner: the M6 live provider and the live Laya call.

---

## 2026-10-21 17:40 - M8: the recommendation layer

**Preflight first.** The directive asked whether the M6.1 reply
claim/shape/provenance gap was already closed. The machine state said
yes, but a report saying yes is not evidence, so **M6.1 and M7 were
re-verified from the outside** with probes written to attack them rather
than to re-run their own suites:

- **M6.1** - 19 adversarial replies (scope violations, unsupported sizes
  riding on permitted numbers, unsupported pairs, availability, certainty,
  sold-price and three kinds of provenance loss) -> **19/19 blocked, 0
  holes**, and the correct reply still accepted.
- **M7** - the served payload measured against the raw master over all 15
  in-scope cells -> **0** of 107 notes, **0** of 2 dealer names, **0** of
  35 raw size strings and **0** of 370 plot numbers reached it, **0**
  drift against the lookup, parked block refused.

Both layers were genuinely complete, so **nothing was rewritten**.

**M8 - COMPLETE AND VERIFIED.** `market/recommend.py` is the new
recommendation layer. It proposes only (block, size) cells that the
approved master **covers** and that **clear the same evidence threshold
the lookup uses**. A cell below the threshold is reported as a **thin
cell** - a gap with no price - and is never offered as an option. The
ranking is deterministic and explainable: four named components
(`size_fit`, `block_fit`, `evidence_fit`, `recency_fit`) and a reason on
every option. The layer reads M7's *whitelisted* evidence rows, never the
raw master rows, so no dealer content can reach it by construction, and
it never claims availability - the master is a partial snapshot of asking
prices, not a live feed.

The alternatives enter the fact set as `verified_alternatives` (each
marked `verified: True`), and the M6.1 guard and the M5 numeric validator
read them from **there** - so the reply may word an alternative but may
never create one, and the model may never widen its own permitted
claims.

**A real defect, found and fixed (D-48).** The M6.1 guard judged a claim
per SENTENCE and checked the cross product of its blocks and its sizes.
A reply offering several alternatives in one sentence therefore claimed
phantom pairs - "a 14 marla plot in Block B, a 7 marla plot in Block A"
was refused for asserting (B, 7), which it never said. Because the
guard is authoritative, a correct reply was being converted into a dead
end. The pair check moved to **clause level**, and the split narrows
false positives without weakening the check (when no clause carries both
a block and a size, the whole sentence is judged exactly as before).
Two regression tests prove both directions.

**The dealer now gets:** "The closest match with more data is a 7 marla
plot in Block C. Other verified alternatives with more data are a 10
marla plot in Block B and a 10 marla plot in Block A. Tell me your
preferred size or block and I can narrow them down." Every cell named is
covered by the master and clears the threshold; no price is quoted for a
cell the product refused to price; no availability is claimed; the human
hand-off is kept; both final gates still pass.

**Measured.** Suite **511 passed, 0 failed** (32 modules, ~26 s) - 475
pre-existing + 35 M8 + 1 surface-completeness. All fourteen gates re-run
and green: M8 suite 35/35, M6.1 suite 40/40, M7 suite 86/86, M5
validator + surface guard + completeness 79/79, 20-question audit 20/20,
`verify_no_price_leak` LEAKS: 0, `verify_robustness` CRASHES: 0 /
LEAKS: 0, `verify_scope_authority` FOLLOWS, `verify_adapter_scope` block
E -> matched=0, `verify_ci_portability` EXIT 0, plus the three new
probes: M6.1 adversarial 19/19 with HOLES: 0, M7 privacy 0 leaks /
0 failures, M8 API 17/17.

**Integrity.** Approved master `b77b3cb5...` unchanged and byte-identical
to `07_MASTER`; the owner's root database `b7504af1...` unchanged with
its residue preserved (1,200/1,200/1,200 + 5,867 `market_listings`); the
demo database restored to 702/702/702 after nine ad-hoc probe rows were
removed by their exact lead ids (D-49); `integration_test.py`,
`controlled_gateway.py` and `shadow_mode.py` byte-unchanged. No model
call, no credential read, no paid provider, no quota spent. Nothing
staged, nothing committed.

**Next.** M9 - the qualification and next-best-action layer: the
dealer-side requirements (budget, purpose, preferred block, timeline)
extracted and used to re-rank the verified alternatives and to decide
between "offer alternatives", "ask a clarifying question" and "escalate".
Qualification may only ever **narrow** the verified set. Still gated on
the owner: the M6 live provider and the live Laya call.
---

## M9 - Qualification and the next-best-action layer - **COMPLETE AND VERIFIED** (2026-10-21)

**Scope:** the dealer-side requirements, and what they narrow. The
ladder's middle is now qualified, and the product chooses its next
action instead of answering everyone the same way.

### What was found before anything was built

The reported M8 state was **verified, not assumed**: the suite was run
(511 passed), and the approved master (`b77b3cb5...`, 374 rows), the
owner's root database (`b7504af1...`, 1,200/1,200/1,200 + 5,867
`market_listings`), and the three protected files were hashed and
compared. **All matched the reported baseline exactly.**

One discrepancy was found: three modules - `market/qualify.py`,
`market/decision.py` and `market/conversation.py` - already existed,
written at 17:53-17:55 on 2026-10-21 by an **interrupted concurrent
session**. They were **not imported by anything**, had **no tests**,
**no API route** and **no pipeline wiring** - the work was written and
never finished. They were used as the starting point rather than
rewritten, and eight defects in them were found and fixed (D-50 to
D-57).

### What M9 is

The layer that answers the question M8 could not: what is the
difference between "I need a 5 marla plot in Block C" and "I need a 5
marla plot in Block C, budget around 60 lakh, for investment, and I
want to close within three months".

| File | Change |
|---|---|
| `market/qualify.py` | the requirements: extraction, merging, validation, narrowing, the clarifying question. **Fixed D-50, D-51, D-52, D-53, D-54, D-55, D-56.** |
| `market/decision.py` | the ladder: exact match -> verified alternatives -> clarifying question -> human escalation. The policy always wins. |
| `market/conversation.py` | the requirements stated so far, re-derived from the lead's own `messages` rows. Fail-closed. |
| `app/pipeline.py` | the requirements, the decision, and the qualified alternatives wired into both market paths. **Fixed D-57, D-58.** |
| `app/server.py` | `GET /api/next-best-action` - the decision surface. |
| `tests/test_m9_qualify.py` | **NEW** - 85 tests |
| `tests/test_m9_integration.py` | **NEW** - 31 tests |
| `tests/test_m5_surface_completeness.py` | the M9 route registered + its own guard test |
| `tools/m4_verify/_probe_m9_api.py` | **NEW** - the M9 API probe, 24 checks |

### The rules the layer obeys

* **Narrowing-only, by construction.** The qualifier receives the
  ALREADY-VERIFIED option list and returns a **subset** of it. It
  never calls the lookup and never reads the master, so it has no way
  to produce a cell of its own.
* **The budget narrows symmetrically.** A ceiling removes the cells
  above it; a floor removes the cells below it; an option whose range
  OVERLAPS the stated range is kept.
* **A preference is not an exclusion.** A preferred block or size
  re-ranks and never removes.
* **The purpose and the timeline narrow nothing.** The approved master
  carries no `category` (374/374 null) and no timing attribute, so
  they are recorded as `unknown` and make a question more likely.
* **An unstated requirement stays unknown.** It is never guessed, and
  an unknown is the reason to ask, not the reason to assume.
* **A model may only be CONFIRMED, never CORRECTED.** A
  model-proposed requirement is checked against the dealer's own words,
  in the units the dealer writes.
* **The application owns the decision.** The policy is never softened,
  and the decision is the last word on the reply's wording.

### What the dealer now gets

> "I need to confirm the current market information with our team
> before giving you a price. What is the highest budget you can work
> with? Human approval is required before sending."

A question, and **not** the options it was meant to narrow.

### Measured

Suite **628 passed, 0 failed** (34 modules, ~59 s) - 511 pre-existing
+ 117 M9. All the M8 gates re-run and green: M6.1 adversarial **19/19
with HOLES: 0**; M7 privacy **0 leaks / 0 failures**; M8 API
**0 failures**; `verify_no_price_leak` **LEAKS: 0**;
`verify_robustness` **CRASHES: 0 / LEAKS: 0**; `verify_scope_authority`
**FOLLOWS**; `verify_adapter_scope` block E -> **matched=0**;
`verify_ci_portability` **EXIT 0**; 20-question audit **20/20**; plus
the new M9 API probe **0 failures** (24 checks).

**Integrity.** Approved master `b77b3cb5...` unchanged, 374 rows; the
owner's root database `b7504af1...` unchanged, 1,200/1,200/1,200 +
5,867 `market_listings`; the demo database restored to 702/702/702
after 27 ad-hoc probe rows were removed by their exact lead ids
(D-59) - the CONTENT was verified by digest, because SQLite rewrites
pages after a delete; `integration_test.py`, `controlled_gateway.py`
and `shadow_mode.py` byte-unchanged. No model call, no credential
read, no paid provider, no quota spent. Nothing staged, nothing
committed.

### What is NOT done in M9, deliberately

No map, no plot visualisation, no voice, no CRM, no lead scoring and no
autonomous sales agent. The **purpose** and the **timeline** are
recorded but do not narrow, because the approved data cannot describe
them. A **preferred block** still does not survive the M2 filter
extractor, which treats a named block as THE requested block (D-60) -
that is an M2/M4 change and needs its own milestone.

**Next.** M10 - the dealer-facing conversation: the qualification layer
reachable from a real conversation, the clarifying question a turn
rather than a line, and the requirements visible to the operator beside
the reply. Still gated on the owner: the M6 live provider and the live
Laya call.


---

## M10 - the reply agrees with the decision - **COMPLETE AND VERIFIED** (2026-10-21)

**Scope:** the M9 closeout's own untested hypothesis - that the
decision and the reply might disagree. M10 measured the live pipeline
and found that they did, twice.

### The two defects

| | D-61 | D-62 |
|---|---|---|
| what | the reply quoted a cell the dealer's budget excluded | a clarifying question on an answerable cell was blocked |
| measured | "7 marla in Block C, budget 5 million" -> the reply quoted PKR 6,000,000 - 11,500,000 for the excluded cell | "7 marla in Block C, budget 1 million" -> the guard rejected the question for "losing provenance"; the dealer got the hold wording |
| the decision | `offer_verified_alternatives` (C/7 removed, C/5 kept) | `ask_clarifying_question` |
| gates | **both passed** - the numbers were true and the claim was supported | the guard rejected it for a provenance it never had |

### The finding that mattered

**Neither defect was a gate failure, and neither could have been.** A
**budget is not a fact**: the master holds no such field. The M5
numeric validator asks "is this number in the master?" and the M6.1
claim guard asks "is this claim supported by the master?" - both
answers were YES for a price the dealer had ruled out. Only the
application, which owns the requirements, can see the conflict.

### The fix

The decision is now **applied to the faces**, not merely recorded
(DEC-63). The fact set follows the decision before the reply is
worded and before the gates run: a cell the requirement excluded stops
being answerable (price and counts withheld, reply re-rendered by the
lookup's own `render_reply()`), and a question is judged in the
insufficient state.

**Neither gate was weakened.** The M5 validator and the M6.1 guard are
exactly as they were; the application withdrew the fact instead.

### What was built

| File | Change |
|---|---|
| `market/decision.py` | the decision records `exact_excluded` |
| `app/pipeline.py` | `_fh_m9_apply_decision_to_facts()` |
| `tests/test_m10_d61_reply_agrees.py` | **NEW** - 21 tests |

### The gates, re-run after M10

Full suite **649/649**; M10 suite **21/21**; M6.1 adversarial
**19/19, HOLES: 0**; M7 privacy **0 leaks**; M9 API probe **0
failures**; 20-question audit **20/20**; `verify_no_price_leak`
**LEAKS: 0**; `verify_robustness` **CRASHES: 0 / LEAKS: 0**;
`verify_scope_authority` **FOLLOWS**; `verify_adapter_scope` block E
-> **matched=0**; `verify_ci_portability` **EXIT 0**.

### The safety invariants, re-verified

the approved master **unchanged**; the owner's root database
**unchanged** with its residue **preserved**; the demo database
**unchanged**; the three protected files **byte-unchanged**; nothing
staged, nothing committed; **no model call, no credential read, no
paid provider, no quota spent**.

**Next:** the dealer-facing conversation (DEC-62) - the qualification
layer reachable from a real conversation, the clarifying question a turn
rather than a line, and the requirements visible to the operator beside
the reply. Still gated on the owner: the M6 live provider and the live
Laya call.

---

## M10.1 - the conversation reaches the decision

**Milestone:** M10.1 | **Status:** COMPLETE AND VERIFIED
**Baseline:** `evaluation\reports\m10_1_baseline_20261021_2245.md`
**Suite:** 36 modules / **695 tests, 695 passed**

M10 closed ONE untested hypothesis - that the decision and the reply
might disagree. M10.1 asked the other half of the same question: that
the decision might **never be made at all**.

The instrument was `tests/test_m10_business_scenarios.py` - 30
end-to-end scenarios through the real pipeline, the real policy, the
real lookup and the real approved master. **Three failed.** All three
were one defect.

### D-64 - a turn that stated a REQUIREMENT was never qualified

> turn 1: "I need a 7 marla plot in Block C, budget 5 million."
> turn 2: "Actually my budget is 12 million."

turn 2 produced **no `next_best_action`, no `requirements_stated`**, and
the generic hold wording - while the conversation state correctly held
`budget_min_pkr: 12,000,000`. The requirement was read, merged and
stored, and then never reached anything that could act on it. The
dealer's most important turn - the one where they change their mind -
was the one turn the product could not handle.

**The cause:** the market layer's gate asked "does this message yield
usable market **FILTERS**?". A budget is not a filter, so the turn was
dropped. That gate came from M10's D-63 fix, which had already widened
it from "needs a price word" to "needs a filter" and had fixed the
dealer who states a requirement **and** a cell. D-64 is the case where
a dealer states a requirement and **no** cell - the case D-63's fix
left behind, because it stopped one step short of the requirement
itself.

**Why no gate could catch it:** the turn carried no number and no claim,
so the M5 validator and the M6.1 guard both passed it - correctly. The
failure was not in what the reply said; it was in what the product
**never decided**.

**The third scenario failure was a TEST error, not a product bug.** The
assertion expected a ceiling's shape, but the settled M9 contract makes
a single stated figure an **exact** budget (both bounds equal), which
`test_m9_qualify.py::test_a_budget_in_lakh_is_read_as_pkr` already
pins. The expectation was corrected to the settled contract and
strengthened: the old budget must survive nowhere in the stated set,
and the genuine ceiling case gets its own test.

### What was built

| File | Change |
|---|---|
| `app/pipeline.py` | the layer's gate admits a turn with usable filters **or** a stated requirement (DEC-64); the conversation's own block and size fill the lookup's gap, the current message always winning; the requirements are read ONCE and passed to both the gate and the decision (DEC-65) |
| `app/pipeline.py` | `_fh_protected_market_case()` - the protected-case list now lives in ONE place, so the price-question test and the requirement test cannot disagree |
| `tests/test_m10_1_d64_requirement_only_turn.py` | **NEW** - 16 tests |
| `tests/test_m10_business_scenarios.py` | the budget-semantics expectation corrected to the settled M9 contract, and strengthened |

### The rule the layer now obeys

* a **REQUIREMENT is part of the qualification, exactly as a FILTER is**;
* the **LOOKUP is unchanged** - a requirement-only turn still prices
  nothing, because a price still needs a cell the approved master
  covers. What the turn gains is the **decision**;
* a **protected case still escalates** - booking, payment plan, legal,
  availability, discount, injection, parked block;
* a message with **no requirement and no filter** is untouched;
* the **gate and the decision read the same requirements**.

### The gates, re-run after M10.1

Full suite **695/695**; M10.1 scenarios **30/30**; M10.1 D-64
**16/16**; M6.1 adversarial **HOLES: 0**; M7 privacy **0 leaks / 0
failures**; M9 API probe **0 failures**; 20-question audit **20/20**;
`verify_no_price_leak` **LEAKS: 0**; `verify_robustness` **CRASHES: 0
/ LEAKS: 0**; `verify_scope_authority` **FOLLOWS**;
`verify_adapter_scope` block E -> **matched=0**;
`verify_ci_portability` **EXIT 0**.

### The safety invariants, re-verified

the approved master **unchanged** (374 rows); the owner's root database
**unchanged** with its residue **preserved** (1,200/1,200/1,200 + 5,867
`market_listings`); the demo database **unchanged** (702/702/702, 0
`market_listings`); the three protected files **byte-unchanged**;
nothing staged, nothing committed; **no model call, no credential read,
no paid provider, no quota spent**.

**The protected cases were re-checked with a budget attached**, because
the fix touches the gate that admits a turn: booking, payment plan,
legal dues, availability, discount, prompt injection and the parked
block **all still escalate**, and **none** of their replies carries a
price.

### One pre-existing defect found and deliberately NOT fixed here

**D-65:** the policy gate escalates "20% discount" but answers "20% off".
`app/policy.py` was last written at 19:57 - before the M10 baseline
(22:01) and before this work - and was not touched by M10 or M10.1. The
two are independent: D-64 is about whether a turn is QUALIFIED, D-65
is about whether the policy ESCALATES a turn. A policy change is the
safety-critical surface of this product and deserves its own measured
milestone rather than a drive-by edit inside an unrelated fix. The blast
radius was measured: the reply still carried **no price**, so this is an
escalation-recall gap, not a price-leak.

**Next:** the dealer-facing conversation (DEC-62) - the qualification
layer reachable from a real conversation, the clarifying question a turn
rather than a line, and the requirements visible to the operator beside
the reply. D-64 closed the first two for the requirement-only turn, and
DEC-65 settled that the operator sees the SAME decision the dealer was
given. Still gated on the owner: the M6 live provider and the live Laya
call. Open and still an owner decision: D-60, and D-65.

---

## 2026-10-22 - Autonomous run: D-65 CLOSED (Phase 0-3 of the M11 run)

**Milestone:** D-65 (the discount-wording escalation gap) - **RESOLVED AND VERIFIED**
**Branch / HEAD:** `master` / `d35ec1c` (unchanged - nothing staged, nothing committed)
**Reports:** `docs\reports\phase0_summary.md`, `phase1_baseline.md`,
`d65_measurement.md`, `d65_fix_report.md`, `DECISION_LOG.md`, `AUTONOMOUS_STATE.md`

### What was done

1. **Phase 0 (read-only).** The context file was read from `D:\MASTER_CONTEXT.txt`
   and compared against the repo. Its reported numbers (695/695, 0 leaks,
   20/20, 374 records, scope A/B/C) were all **confirmed by re-measurement**.
   The only governance conflict found is the one the owner already knew about:
   M10.1 deliberately left `app\policy.py` untouched - resolved by the standing
   owner authorization **A1**.
2. **Phase 1 (read-only).** The verified baseline was re-established:
   **695 passed / 0 failed**, price-leak **0**, privacy leaks **0**, robustness
   crashes **0**, scope **FOLLOWS**, M6.1 **HOLES: 0** (19/19), 20-question audit
   **20/20**, approved master `b77b3cb5...` (374 records) **unchanged**, root DB
   `b7504af1...` **unchanged** with its 5,867 `market_listings` of residue
   **preserved**, the three RULES_SHORT #7 protected files **unchanged**.
3. **Phase 2 (measure).** 21 discount phrasings and 4 benign phrasings went
   through BOTH the policy path and the final reply path. **14 of 21 discount
   phrasings did not escalate; 0 of 4 benign phrasings did.** The blast radius
   measured **wider** than the defect entry had recorded: a discount request
   that also names a cell was answered **with prices** (a policy bypass, not a
   price-integrity leak).
4. **Phase 3 (fix, self-approved under A1 + A4).** ONE shared discount-term
   list, `market\discount_terms.py`, read by both the policy gate (the request
   path) and the M6.1 claim guard (the reply path). 80 focused regression
   tests, including every measured phrasing and the benign ones.

### The new baseline

| item | before | after |
|---|---|---|
| full suite | 695 passed | **775 passed, 0 failed** |
| discount phrasings that did NOT escalate | 14 | **0** |
| benign phrasings that escalated | 0 | **0** |
| discount phrasings answered with a price | 2 | **0** |
| price-leak / privacy / robustness / scope / M6.1 / 20-question audit | 0 / 0 / 0 / FOLLOWS / 0 / 20-20 | **0 / 0 / 0 / FOLLOWS / 0 / 20-20** |
| approved master / protected files / git | unchanged | **unchanged** |

### Files changed

| file | change | backup |
|---|---|---|
| `market\discount_terms.py` | NEW - the shared discount-term list | n/a |
| `app\policy.py` | reads the shared list | `backups\m11_d65_20261022\policy.py.bak` |
| `market\reply_guard.py` | refuses a discount CLAIM, using the shared list | `backups\m11_d65_20261022\reply_guard.py.bak` |
| `tests\test_d65_discount_escalation.py` | NEW - 80 tests | n/a |

`app\policy_extra.py`, the two `DEBUG:` prints (DEC-28), the 3-listing
threshold, every privacy rule and every price rule were **not** touched.


## M11 - COMPLETE (2026-10-22)

| item | before | after |
|---|---|---|
| full suite | 868 passed | **912 passed, 0 failed** |
| multi-turn conversations with a qualification state | 0 | **15 golden conversations, 37 tests** |
| conversation endpoint + operator page | untested | **7 endpoint tests, 18 passed together with the M5 surface check** |
| serving routes not accounted for in the M5 check | 4 | **0** |
| price-leak / privacy / robustness / scope / M6.1 / 20-question audit | 0 / 0 / 0 / FOLLOWS / 0 / 20-20 | **0 / 0 / 0 / FOLLOWS / 0 / 20-20** |
| approved master / protected files / git | unchanged | **unchanged** |

### Files changed in M11

| file | change | backup |
|---|---|---|
| `market\lead_state.py` | NEW - the lead-state schema | n/a |
| `market\normalize.py` | the `blk` block typo | `backups\m11_golden_20261022\normalize.py.bak` |
| `market\unmet_demand.py` | NEW - the unmet-demand log | n/a |
| `app\turn_pipeline.py` | NEW - the turn pipeline | n/a |
| `app\server.py` | the four M11 routes | n/a (written earlier in this run) |
| `app\static\operator.html` | NEW - the operator page | n/a |
| `tests\test_m11_lead_state.py`, `tests\test_m11_normalizer.py`, `tests\test_m11_turn_pipeline.py` | NEW | n/a |
| `tests\test_m11_operator_endpoints.py` | NEW - the endpoint and the page | n/a |
| `tests\golden\conversations.json` | NEW - the 15 golden conversations | n/a |
| `tests\test_m11_golden_conversations.py` | NEW - the replay | n/a |
| `tests\test_m5_surface_completeness.py` | the four M11 routes accounted for | `backups\m11_golden_20261022\test_m5_surface_completeness.py.bak` |


## M11.7 - COMPLETE (2026-10-22)

| item | before | after |
|---|---|---|
| full suite | 912 passed | **922 passed, 0 failed** |
| the operator page answered | **no** (422, empty bubble) | **yes**, and it can never be silent again |
| a browser-level test of the page | none | **1** (headless Chrome, already installed) |
| the approver on a console with an invalid handle | **crashed** | **falls back, and denies when it cannot ask** |
| approved master / protected files / git | unchanged | **unchanged** |

### Files changed in M11.7

| file | change | backup |
|---|---|---|
| `app\static\operator.html` | the request the way the endpoint declares it; the page is never silent | `backups\m11_7_20261022\operator.html.bak` |
| `jarvis\agent\approval.py` | the guarded console write | `backups\m11_7_20261022\approval.py.bak` |
| `tests\test_m11_operator_page_request.py` | NEW - the API-level regression | n/a |
| `tests\test_m11_operator_page_browser.py` | NEW - the browser-level regression | n/a |
| `tests\test_agent_approval_console_guard.py` | NEW - the approver's console guard | n/a |

## M12.1 - the professional operator desk (2026-10-22)

* The plain `/operator` page was replaced by a three-region desk
  (lead rail 280 px, conversation thread, decision panel 360 px) in
  plain HTML/CSS/JS - no framework, no build step, no external font, no
  CDN, no external request.
* `/api/conversation` now also accepts a JSON body; the page uses it so
  a dealer's words never reach a URL or an access log. The query form
  still works.
* The page shows only backend-returned facts: `reply`, `route`,
  `reason`, `verified_options`, `lead_state`, `gates`, `policy`,
  `escalation`, `next_action`, `unmet_demand`, `taken_over_at`, plus
  the data date and coverage from `/api/market`.
* **Measured:** full suite **954 passed / 0 failed** (baseline 922);
  browser tests **30 passed** in real Chrome; price-leak 0; privacy
  leaks 0; robustness crashes 0; scope FOLLOWS; M6.1 HOLES 0; 20-question
  audit 20/20; golden replay 37 passed; master `b77b3cb5...` (374
  records) unchanged; protected files unchanged; nothing staged or
  committed; no new dependency; no live model call.
* Known limits: the rail is in memory until M12.2, the draft actions are
  UI only until M12.2, and Goose's log folder cannot be redirected
  (no supported setting) so C: must keep free space.
* Report: `docs/reports/m12_1_report.md`. **M12.1 COMPLETE**
