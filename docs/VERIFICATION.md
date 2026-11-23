# Verification matrix — Faisal Hills AI Lead Desk

Every component below is labelled from recorded evidence, not from a claim.
Re-verification commands are listed at the end; run them yourself — the
project is built so its claims are checkable.

Verified: 2026-11-22 (finishing pass; original suite baseline 2026-11-21).

## A. Core guarantees

| Component | Label | Evidence |
|---|---|---|
| Offline test suite | ✅ VERIFIED — 1,189 tests, 0 failed | `evaluation/reports/system_status_evidence.json`; raw log `D:\FaisalHillsAILeadDesk\phase1_evidence\testrun_final_20261122.txt` |
| Serving-surface guard completeness | ✅ VERIFIED | `tests/test_m5_surface_completeness.py` walks every FastAPI route and asserts each serving route is covered by a guard — a number that cannot trace to the approved master is detached and the turn escalated |
| Draft reply traceability | ✅ VERIFIED | `tests/test_m5_surface_completeness.py` + `market/fact_guard.py`, `market/fact_validator.py`; live desk shows the traceability banner per draft |
| Claim guard | ✅ VERIFIED | guard tests in `tests/test_m5_surface_completeness.py`; every customer-facing claim traced to approved data |
| Human-in-the-loop (no auto-send) | ✅ VERIFIED | `tests/test_lead_pipeline.py` asserts **no send route exists** (`"send" not in path`); composer states "The application drafts, a human sends" |
| Privacy: no private fields on surfaces | ✅ VERIFIED | per-surface tests (`test_m2_policy_scope_privacy.py`, `test_m12_2_persistence.py`, `test_system_status.py`); no dealer names/phones/plot numbers served |

## B. Operator desk (the product surface)

| Component | Label | Evidence |
|---|---|---|
| Desk page + request path | ✅ VERIFIED | `tests/test_m11_operator_page_request.py` — the page's own JS request asserted end-to-end for the owner's original five inputs; page never silent on failure |
| Conversation list + transcript replay | ✅ VERIFIED | `tests/test_m12_2_persistence.py` — transcript replays served replies byte-for-byte **including the verified options of each turn** (new 2026-11-22) |
| Verified-options panel on restored sessions | ✅ VERIFIED | same test: replayed `options` == the list the live turn served; verified live in browser (docs/screenshots/03-desk-exact-match.png) |
| Rail readability (title + route chip) | ✅ VERIFIED | live browser + docs/screenshots/01-desk.png; title = the dealer's first words (`first_preview`), session id on tooltip |
| Layout geometry | ✅ VERIFIED | measured in headless Chrome: rail 280px / thread 708px / context 360px at 1600px (the pre-fix flex override clipped the context panel) |
| Follow-ups queue | ✅ VERIFIED | `tests/test_lead_pipeline.py` + docs/screenshots/06-follow-ups.png |
| Lead pipeline, stages, scores | ✅ VERIFIED | `tests/test_lead_pipeline.py` |
| Weekly owner report (Markdown/CSV) | ✅ VERIFIED | `tests/test_pilot_feedback_reporting.py` — aggregates counts/shapes only; docs/screenshots/07-reports.png |
| Site-visit requests + approval | ✅ VERIFIED | `tests/test_pilot_features.py` |
| Offline map (Leaflet + bundled tiles) | ✅ VERIFIED (manual) | no network request at runtime; tiles under `app/static/map/`; docs/screenshots/05-map.png. Not covered by an automated test — labelled honestly |
| System status view (live truth) | ✅ VERIFIED | `tests/test_system_status.py` — numbers are infrastructure-only, counts are true counts of the env-named files, missing evidence file ⇒ no claim; docs/screenshots/04-system-status.png |

## C. Inventory & data

| Component | Label | Evidence |
|---|---|---|
| Versioned inventory workspace | ✅ VERIFIED | `tests/test_inventory_workspace.py` — upload → validate → review → approve → activate → rollback → audit |
| Truthful inventory chip | ✅ VERIFIED | page header shows the fingerprint/rows/date-range of the source actually served (`MASTER b77b3cb5 · 374 rows · 2026-09-22→2026-10-07`) |
| Demo fact database seeding | ✅ VERIFIED | `data/demo_seed.py` idempotent; demo DB separate from the raw archive |
| Curated demo state | ✅ VERIFIED | `tools/reset_demo_state.py` run 2026-11-21/22 (backup taken first): 10 conversations / 13 turns / 3 take-over actions, all through the real pipeline |
| Test-run isolation | ✅ VERIFIED | `conftest.py` isolates the main DB **and** all five side stores; a pytest run can no longer write into the live demo stores (root cause of the 2026-11-21 desk pollution) |

## D. Packaging & delivery

| Component | Label | Evidence |
|---|---|---|
| Encoding integrity (HTML assets) | ✅ VERIFIED | double-encoded characters repaired; zero mojibake; em-dash/ellipsis render correctly |
| Cache-safe assets | ✅ VERIFIED | `/static/...?v=1.0.3` busts stale caches on upgrade |
| Repo hygiene | ✅ VERIFIED | stray junk files moved to `archive/legacy_cleanup_20261122/`; `.gitignore` covers `*.db`, `*.bak*`, `.aider*`, logs, pycache |
| Upload package | ✅ VERIFIED | `tools/build_upload_package.ps1` builds a share-ready zip from an explicit include list — all databases, backups, logs and private data excluded |

## How to re-verify

```powershell
cd D:\AI-Projects\laya-gateway
.\.venv\Scripts\python.exe -m pytest -q          # full suite (offline)
.\.venv\Scripts\python.exe -m pytest -q tests\test_m5_surface_completeness.py   # guard completeness
.\.venv\Scripts\python.exe -m pytest -q tests\test_system_status.py              # status surface
.\start_operator_desk.bat                        # then open System status in the sidebar
```

Anything labelled VERIFIED above fails its check → treat the label as void
and fix before sharing. That is the point of the matrix.
