# TASK 11: Final evaluation and demo pack

Follow PROJECT_STATE.md HARD RULES. Read PROGRESS.md and all previous TASK files. Standard library plus pytest. UTF-8 without BOM.

1. tools/e2e_eval.py: runs golden_v1.jsonl and redteam_v1.jsonl through app.pipeline.handle_message in demo mode. Reports: red-team rows that got an auto reply (must be 0), needs_human recall, share of price replies whose numbers are all traceable (must be 100%), average and p95 latency per message. Writes evaluation/reports/e2e_YYYYMMDD_HHMM.md and exits non-zero if a gate fails.
2. docs/DEMO_SCRIPT.md: 10 scenarios with exact messages in English, Roman Urdu and Urdu: price with enough data; price with insufficient data; missing fields leading to a clarifying question; discount request; legal or NOC question; investment guarantee; prompt injection; abusive message; stale-price pressure; site-visit request producing a lead brief.
3. docs/REAL_DATA_SWAP.md: steps to go live: put exports in data/raw_chats, fill market/blocks.json from the map, set APP_MODE=pilot, run tools/purge_demo.py, run tools/ingest_all.py, run the market report, compare with data/trusted_prices.csv using tools/check_trusted_prices.py (build this tool), then a go or no-go checklist.
4. docs/PILOT_OFFER.md: one-page pilot terms template (scope, human approval on every reply, data handling and privacy promise, metrics, duration, price placeholder, opt-out).
5. Update README.md and write STATUS_TEMPLATE.md for future handoffs.

Finish by listing exact commands.