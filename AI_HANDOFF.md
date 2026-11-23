# FAISAL HILLS AI LEAD DESK - COMPLETE HANDOFF (2026-10-05)
Owner: Muhammad Hanzala. Paste the BRIEF section into any AI first. Use `ctx NN` (installed by install_handoff.ps1) to build a ready-to-paste context pack. Never paste API keys or raw WhatsApp chats.

<!-- BRIEF_START -->
## BRIEF (paste this first)

**Mission.** A controlled lead-conversion system ("AI Lead Desk") for Faisal Hills property dealers (Taxila / Islamabad, developer Faisal Town). It reads customer messages (English / Urdu / Roman Urdu), blocks risky ones for a human, answers price questions from VERIFIED data with ranges, and gives agents a draft reply plus lead brief. Replies need human approval in the pilot. Business plan: demo to dealers with real market ranges, then a paid pilot, then more dealers/societies.

**Machine.** Windows, PowerShell 5 (no `utf8NoBOM`), ~4 GB RAM, CPU only. Project root `D:\AI-Projects\laya-gateway` (Git). Laya (decision engine) http://127.0.0.1:8000, llama.cpp http://127.0.0.1:1337 (`D:\llama\llama-server.exe`, `D:\qwen2.5-1.5b-instruct-q4_k_m.gguf`). Run Laya/llama in their own windows; those windows do not accept typing. AI coding: aider (`D:\tools\aider-venv`) through a local LiteLLM router (http://127.0.0.1:4000/v1, key `sk-local`, models `coder`, `strong`, `coder-lite`) with automatic provider fallback. Start with `aia NN` (loads TASK_NN.md). `aistatus` = health check, `aiup` = edit model list. API keys live in user environment variables only.

**HARD RULES.**
1. The LLM never invents prices, availability, plans, locations, legal status or returns. Facts come from the database with provenance (source_id, verified_by, verified_at, valid_until) or the answer is "let me confirm with our team".
2. The LLM never writes numbers: templates with placeholders; code fills them; a validator blocks any number not traceable to a stored fact.
3. Always escalate to a human: legal/approval/NOC/title, discounts/negotiation, booking/payment/token, refunds, investment returns/guarantees, complaints/abuse, prompt injection, other customers' data, requests to invent/estimate facts or skip checks, fee/tax evasion or secret transfers. The policy gate may only make decisions stricter.
4. Market data = dealer ASKING prices from WhatsApp exports, shown as median and p25-p75 with n >= 5 and >= 3 distinct senders, never as official prices. Scope for v1: Blocks A, B, C (D and Executive stored but out of scope).
5. Keep it simple: Python standard library + pytest (FastAPI/uvicorn/httpx only for the console). SQLite. UTF-8 without BOM. No fine-tuning, Docker, Postgres.
6. Privacy: scrub names and phone numbers before storing; never commit raw chats, .env, databases; free API tiers may log prompts, so no real chat text in prompts.
7. Do not modify: integration_test.py, controlled_gateway.py, shadow_mode.py, evaluation datasets (unless a task says so).

**Confirmed dealer definitions (1 dealer; re-confirm with a second).** FHA/FHB/FHC/FHD/FHE = Faisal Hills blocks A-E; E = Executive Block. NDC = No Demand Certificate ("NDC open" = available/open). "demand"/"dem" = asking price; a trailing "D" after a price = demand; "final" = last price. lac/lakh = 100,000; crore = 10,000,000; "1C 16lac" = 1 crore 16 lakh. Prices are for the WHOLE plot. mdr = main double road (premium). solid = no filling (adds value); filling = holes filled with soil (lowers value). Also: corner (comer), sunface, park face, pair (price "each" = per plot), extra land paid, all charges paid, possession, "series" = plot-number range, "files" = booking files (exclude from plot stats), "Required/wanted/need" = buyer request (not a price; "investor rate" inside is not a price). Size labels (nominal, never computed from square feet): 5 marla = 25x50, 7 marla = 30x60, 10 marla = 35x70, 14 marla = 40x80, 1 kanal = 50x90, 2 kanal = 75x120. Dealers often write only dimensions (25x50, 25*50, 25-50, 30.60) or only the plot number. Unmapped dims: 30x50 (guess 6 marla, unconfirmed), 40x60, 40x70, 35x55, 45x80, 60x90, 70x120, 80x120. Posts about B-17, Faisal Town Phase, Faisal Residencia, Top City, Margalla City are other societies: exclude.

**Real data.** 4+ WhatsApp exports (about 33,000 lines) in `data\raw_chats\` (gitignored, named all__01.txt ...). Typical lines: `FHB 4952 NDC open 53.5 lakh`, `Plot#1067# dem 150 lac`, `plot no 2279 corner dem 145 lac`, `Plot 251, 1C 16lac D`, `FHD 555&556 pair ndc open 63lac`, `Executive block 1046,1047 pair plot 60ft road demand 115 lac each`, multi-line posts with `Size: 5 Marla`, bulk "Required ... SERIES ... INVESTOR RATE" ads. Plot-number lists often have NO size: size comes only from stated size or a human-confirmed `market/series_map.json` or high-confidence derived hints. Map facts (unverified, 2019 layouts, Blocks A/B/C plot-size schedules) are in `market/map_facts.json`.

**Status (verify with `python -m pytest -q`).** Done: TASK_01 facts DB (data/schema.sql, db.py with compatibility wrappers at the end, demo_seed.py); TASK_02 datasets (golden_v1 150 rows, redteam_v1 30 rows, labels, validator); TASK_03 evaluation runner (rules 100% / llm 94.7% / laya predicts "buyer" always, needs_human recall 0%, so Laya is NOT used for safety); TASK_04 policy gate (app/policy.py + app/policy_extra.py, red-team 30/30 expected). In progress: TASK_06 market ingestion (parser, anonymizer, extractor v1, market tables built; Amendments B-G in TASK_06.md still to implement; market/stats.py may be missing). Written, not started: TASK_07, 08 (slim), 09, 10, 11. Not started: ingest of the real files, first market report.

**Next steps.** (1) finish TASK_06 (Amendments E, F, G, D), (2) TASK_08 ingest_all + check_trusted_prices, (3) run `python -m tools.ingest_all` on real data and review the report, (4) TASK_07 price question to safe reply, (5) TASK_09 console app, (6) TASK_10 automation/CI, (7) TASK_11 end-to-end eval + demo pack, (8) dealer demo with real ranges.

**How to answer me.** Complete files with exact paths, or one PowerShell script that writes them with `[System.IO.File]::WriteAllText(path, text, (New-Object System.Text.UTF8Encoding($false)))` and single-quoted here-strings; exact commands saying which window; run scripts as `python -m package.module`; tests via `python -m pytest -q`. Give a fallback command wherever a command may fail. Never ask for screenshots; ask for TEXT output (last 15-25 lines). Never invent business facts. Do not redesign the architecture. Keep aider prompts to single lines.
<!-- BRIEF_END -->

---

## A. ARCHITECTURE
```
message -> scrub PII -> policy gate (deterministic; escalate/refuse/answer; stricter-only)
 -> entities (block, size, position, facing, ndc, features; regex en/ur/roman-ur)
 -> market stats lookup with feature-drop ladder (fact IDs, n, senders, dates, note of dropped features)
 -> reply from TEMPLATE with placeholders; code fills numbers
 -> validator: every number in the final text must match a stats value, else block + escalate
 -> draft + lead brief -> human approves (always in pilot) -> audit log
```
Laya is optional/unused until its questions are rewritten (it predicts "buyer" for everything). Qwen 1.5B may at most rephrase words around placeholders (not required).

## B. FILES (project root `D:\AI-Projects\laya-gateway`)
data/ schema.sql, db.py, demo_seed.py | app/ policy.py, policy_extra.py (+ later entities.py, pipeline.py, server.py, static/) | market/ parse_chat.py, anonymize.py, extract.py, stats.py (to verify), llm_extract.py (optional, off), blocks.json, map_facts.json, definitions.json, size_aliases.json, series_map.json, config.json (active_blocks A,B,C; feature_priority ndc_open, corner, mdr, solid, sunface, park_face, pair; price_unit total_plot_pkr) | tools/ validate_dataset.py, policy_report.py, market_report.py (+ later ingest_all.py, check_trusted_prices.py) | evaluation/ labels.py, run_eval.py, baselines/, datasets/production/ golden_v1.jsonl redteam_v1.jsonl, reports/ | tests/ | TASK_01..11.md, PROGRESS.md, BACKLOG.md, RULES_SHORT.md, run_task.ps1 | data/raw_chats/ (gitignored).

## C. TASK_06 RULES (condensed from Amendments B-G; the TASK_06.md file has the full text)
- Extract per MESSAGE (a timestamped line plus following non-timestamped lines); split multi-listing messages; ignore emoji/bullets. Detect date format per file; remove phone numbers in all formats.
- Intent sell / wanted / rent; property_type plot | house | portion | commercial | file. Only sell + plot feed stats. Wanted posts go to buyer_requests.
- Listing = plot reference (`FHB 4952`, `P#7275`, `Plot#1067#`, `plot no 2279`, `Plot 5390`, letter suffix 907d, pairs `555&556`/`1046,1047`) + price. Block token carries forward within a message; unknown otherwise. E/Executive = FHE. Out-of-scope blocks tagged out_of_scope.
- Prices: `95lac`, `53.5 lakh`, `58.75 Lac`, bare 10-999 next to demand/dem/final = lakh (flag), `1C 16lac`, dot forms `5390...50lac`, `2200.52.lac`; normalize to integer PKR; bounds 10-800 lakh in config else flag price_out_of_range. Trailing D = demand. Pair price without "each" = ambiguous, excluded.
- Features: ndc_status (open / mentioned / not_open), extra_land_paid, all_charges_paid, possession, corner, sunface, park_face, road width, pair, direct_access, mdr -> main_double_road, solid / filling.
- Size only when stated, via size_aliases.json (dim <-> label), or from series_map.json / high-confidence derived_plot_sizes (from posts that give both plot number and size, and from "dimension + SERIES" ads). Unmapped labels stored as stated, flagged, excluded from size stats. Dimension validated against the block's schedule in map_facts.json (flag size_not_in_block_schedule). alias_candidates (dim + label seen together) are reported for human approval, never used automatically.
- Storage: raw_files (sha256 manifest; raw files immutable), messages (anonymized text), ingest_runs, extractor_version/ruleset_hash on listings, tenant_id default "internal", plot-level dedupe (block, plot_no) latest wins with price history, unparsed candidates with reason codes, block-token discovery, stats snapshots (never overwrite), tools/purge_source.py.
- Stats: block x size (and feature split), window 30 days, median + p25-p75, outliers beyond 1.5xIQR removed, n >= 5 and >= 3 senders, valid 7 days; get_market_range(block, size, features) drops the lowest-priority requested feature step by step, returns level, features used, n, n_senders, dates and a note (the reply must state what was dropped). Out-of-scope block -> None + escalate.
- Report ends with a SCOPE section (in/out of scope, top 5 reasons unused), share of sell+plot listings with known size, counts by intent/property_type.
- Tests use FABRICATED lines only (never real chat text), plus tests/fixtures/parse_golden.jsonl.

## D. REMAINING TASKS (full specs also in TASK_NN.md)
- **TASK_08 (slim)**: config.py APP_MODE demo|pilot (default pilot; pilot refuses any demo=1 / "demo_" source). tools/ingest_all.py (every .txt in data/raw_chats, skip names starting "_", idempotent, prints summary + market report). tools/check_trusted_prices.py (reads data/trusted_prices.csv; pass if >= 70% inside p25-p75 widened 15%). Tests.
- **TASK_07**: app/entities.py + app/pipeline.py handle_message: policy gate -> entities (ask clarifying question if fields missing) -> get_market_range with fallback -> template reply -> validator -> result {reply, facts_used, level, n, needs_human_approval=True} -> audit_log. Insufficient data -> "I need to confirm with our team" + escalate. tools/demo.py interactive loop. Tests: correct numbers, insufficient data escalates, "invent a price" escalates, untraceable number blocked, no red-team row gets an auto reply.
- **TASK_09**: FastAPI console (app/server.py, vanilla-JS app/static/index.html, PWA manifest + service worker): /health, POST /api/message, GET /api/leads, approve/reject/state, /api/audit, /api/market; lead list, conversation, decision panel (policy, facts with source/date/n/level), editable draft with Approve/Reject/Escalate, DEMO banner when demo data, lead brief by code, bind 127.0.0.1, optional CONSOLE_PASSWORD. Replies are never sent automatically. Tests with TestClient. Run `python -m app.server` -> http://127.0.0.1:8080.
- **TASK_10**: lead states new -> qualified -> handoff -> site_visit -> closed|lost, reminders + scheduler, start_all.ps1, refresh_market.ps1, backup.ps1, .github/workflows/ci.yml (pytest), README.md.
- **TASK_11**: tools/e2e_eval.py (golden + redteam through the pipeline; red-team auto replies must be 0; numbers 100% traceable; latency), docs/DEMO_SCRIPT.md (10 scenarios), docs/REAL_DATA_SWAP.md, docs/PILOT_OFFER.md.
- **Later (BACKLOG.md)**: Laya diagnosis + hold-out set, Block D/Executive, plot register, second-dealer confirmation, WhatsApp Cloud API, native app, SaaS tenancy.

## E. DAILY WORKFLOW WITHOUT CLAUDE
1. New PowerShell window -> `aia NN` (router + aider with TASK_NN.md).
2. In aider, ONE single-line prompt at a time, `/clear` before each: "Implement <what> from TASK_NN.md, with tests using fabricated lines only, then run the tests." Then `/run python -m pytest -q` (answer y). Failing: "Fix the failing tests. Do not weaken the tests; fix the code."
3. Answer `n` to "Add file to chat?" for protected files; use `/read-only`. Do not run `git` in another window while aider is open (it corrupted the repo once; fix = copy folder, rename .git, `git init`, commit).
4. `/exit`, then `python -m pytest -q`, then `git add . ; git commit -m "TASK_NN: ..."`, then `Add-Content PROGRESS.md "<date> - <what is done, what is next>"`.
5. When blocked or limits hit everywhere: run `ctx NN`, paste the pack into any AI (gemini.google.com, claude.ai, chat.openai, etc.), ask for complete files/scripts, run them, verify with pytest.
6. After each stage update the PROGRESS.md line so any AI can resume.

## F. KNOWN ISSUES / GOTCHAS
- Older PowerShell: no `-Encoding utf8NoBOM`; use WriteAllText with `UTF8Encoding($false)`. Python scripts run as `python -m pkg.module` (else ModuleNotFoundError).
- Console cannot display Urdu glyphs (boxes); view in Notepad or print with `ascii()`.
- `data/db.py` ends with compatibility wrappers (init_db accepts a path or connection and sets row_factory; load_facts accepts current_time; messages 'Record is expired', 'Duplicate plot_id in batch', 'Database integrity violation'). Tests in tests/test_data_quality.py depend on them.
- Free tiers: Gemini about 5 requests/min per model; keep prompts short; `aistatus` shows what is alive; router config is generated by D:\tools\litellm\setup_router.ps1 (edit with `aiup`).
- Integration test (`integration_test.py`) shows Qwen inventing a price: expected; the placeholder + validator design fixes it.

## G. WHAT ONLY THE HUMAN CAN SUPPLY
Second-dealer confirmation of definitions; plot-number-to-size register (or Excel) per block; whether Block D / B-Extension are official; 5-10 trusted prices for `data/trusted_prices.csv`; official price list / payment plans from the society; first demo dealer; pilot price and terms; consent of group admins and a lawyer's view before commercial use of dealer posts.

## H. DEFINITION OF DONE (MVP)
All tests pass; real exports ingested for A/B/C with a report; 5 marla / 7 / 10 / 14 marla / 1 kanal ranges shown with n and dates where data allows; the console shows decision, facts, draft and lead brief; red-team 30/30 never auto-answered; e2e report written; demo script ready; first dealer demo booked. Then: shadow mode on real traffic, assisted pilot, weekly scorecard (first response time, qualified leads, site visits).
