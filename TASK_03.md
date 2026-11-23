# TASK 03: Evaluation runner (Laya vs rules vs LLM)

Follow PROJECT_STATE.md HARD RULES. Standard library plus pytest only. UTF-8 without BOM. Do not modify existing scripts. Read integration_test.py and shadow_mode.py (read-only) to copy the exact request and response format for the Laya POST /v1/systemone call.

Build:
1. evaluation/baselines/rules.py: keyword/regex baseline for the three questions lead_type, high_intent and needs_human. Cover English, Urdu script and Roman Urdu keywords (legal, NOC, approval, discount, return, guarantee, refund, site visit, booking, etc.).
2. evaluation/baselines/llm.py: LLM classifier using the Gemini REST API via urllib, key from env GEMINI_API_KEY (never hardcode), model gemini-3.5-flash-lite. BATCH 10 messages per request and ask for strict JSON, to save free-tier quota. Scrub phone numbers and emails before sending. Pace requests with sleep and retry on HTTP 429. Cache results in evaluation/cache/llm_cache.json so a message is never sent twice.
3. evaluation/baselines/laya_client.py: calls Laya at http://127.0.0.1:8000 for the same three questions. lead_type is a choice question; high_intent and needs_human are noul questions with threshold 0.5 (make thresholds a parameter).
4. evaluation/run_eval.py: reads golden_v1.jsonl, supports --methods laya,rules,llm and --limit N, and writes evaluation/reports/eval_YYYYMMDD_HHMM.md containing: accuracy per question per method; accuracy per language; precision/recall for needs_human (recall on risky cases matters most); a confusion matrix for lead_type; a list of the 20 worst failures per method with message, expected and predicted; and a one-line recommendation of the best method per question.
5. tests/test_eval_metrics.py: tests for the metric functions and the rules baseline (no network, no Laya needed).

Finish by listing exact commands to run the tests and a full evaluation.