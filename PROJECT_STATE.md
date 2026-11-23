# FAISAL HILLS AI LEAD DESK — MASTER HANDOFF & EXECUTION FILE

**Version:** 1.0 (created 2026-10-04) — **Owner:** Muhammad Hanzala
**Purpose:** Paste this whole file at the start of any AI session (Claude, OpenRouter models, AnythingLLM, aider, Cline, etc.). It states what exists, what is being built, the rules, the plan, and where work stopped. **Update Section 12 (Progress Log) at the end of every session.**

> **Never put API keys, passwords, or customer phone numbers in this file.** Keys live in environment variables only.

---

## 1. MISSION

Build a **controlled lead-conversion system ("24/7 Faisal Hills AI Lead Desk")** for a property dealer/agency selling Faisal Hills plots/units.

It answers customer messages (English / Urdu / Roman Urdu), qualifies the lead, retrieves **only verified property facts**, drafts a reply, produces a compact **lead brief** for a human agent, and logs everything.

- **Sell:** speed, qualification, consistency, follow-up discipline, qualified handoffs.
- **Do NOT sell:** autonomous closing, guaranteed returns, "generic AI chatbot".
- **Business ambition:** build a company that reaches 100 crore. Path: win one paid pilot → prove measurable lift (site visits/bookings) → repeat across dealers → expand to more societies. (See Section 10.)
- **Time goal:** working MVP in 3–4 days at ~10 h/day. (Realistic scope defined in Section 7.)

---

## 2. TERMINOLOGY (do not mix up)

| Component | Role |
|---|---|
| **Laya** | Decision engine (classification/probabilities). Does NOT write text. |
| **llama.cpp** | Local inference server that serves a GGUF model over HTTP. |
| **Qwen 2.5 1.5B Instruct Q4_K_M** | The local language model (writes text). |
| **Application code** | Owns policy, retrieval, validation, logging. |
| **Database** | Source of truth for facts, with provenance. |
| **Human agent** | Handles exceptions, approvals, negotiation. |
| **Ollama** | Installed at `D:\Ollama` but NOT part of this architecture. Ignore it. |
| **OpenRouter** | Cloud API gateway used for (a) AI coding help and (b) optional baselines/drafting. NOT a replacement for the local stack. |

---

## 3. CURRENT VERIFIED STATE (as of this file)

**Machine:** Windows, PowerShell, ~4 GB RAM, CPU only, ~51 GB free on D:. Page file on D: (16384 MB initial / 24576 MB max) fixed error 1455.

**Services (all verified working):**
- Laya: `http://127.0.0.1:8000` — multilingual checkpoint (322M), CPU, threads=2, 1 resident checkpoint. Venv `D:\laya\.venv`, server `D:\laya\.venv\Scripts\laya-serve.exe`, env: `HF_HOME=D:\laya\hf_cache`, `TEMP/TMP=D:\laya\tmp`, `LAYA_MODELS=multilingual`, `LAYA_DEVICE=cpu`. Decision API: `POST /v1/systemone`. Health: `/health`.
- llama.cpp: `http://127.0.0.1:1337`, `D:\llama\...\llama-server.exe` (find exact path, don't guess), model `D:\qwen2.5-1.5b-instruct-q4_k_m.gguf` (~1.04 GB). Health OK; real generation tested.
- Integration test (message → Laya → decision → Qwen → reply) passed.

**Project root:** `D:\AI-Projects\laya-gateway`
- `integration_test.py` — checks both services and runs the pipeline.
- `controlled_gateway.py` — blocks Qwen when required property data is missing.
- `shadow_mode.py` — logs Laya decisions, no customer-facing action.
- `evaluation\datasets\phase28_smoke.jsonl` — 6 examples, 3 questions (`lead_type`, `high_intent`, `needs_human`); validated after fixing a UTF-8 BOM issue. `evaluation\reports\` has a smoke report from `laya-evals`.

**What is NOT done (honest status):**
- No real evaluation (6 examples = pipeline smoke test only; says nothing about accuracy).
- No approved property database. No retrieval. No factual validator. No audit DB.
- No agent workflow/UI. No channel integration. No CI. No paid pilot. No baseline metrics.
- Laya confidence is **uncalibrated** — never treat it as proof.

**Key lesson already learned:** when asked for a plot price with no data, Qwen invented details. Therefore the LLM must never be the source of facts.

---

## 4. TARGET ARCHITECTURE

```
Customer message
  → ingestion (MVP: agent console paste-in; later WhatsApp/web)
  → PII scrub + language detect
  → Laya (lead_type, high_intent, needs_human, intent, facts_needed)
  → POLICY GATE (deterministic code; can override Laya)
        legal/approval/NOC, discounts, booking, refunds, investment returns,
        prompt-injection, abusive, stale/conflicting facts → HUMAN
  → entity extraction (size in marla, block/series, budget, timeline)
  → approved-data retrieval (SQLite → fact IDs + provenance + freshness)
  → response generator (Qwen local, or cloud model if eval proves needed)
        writes TEMPLATE WITH FACT PLACEHOLDERS, e.g. "{fact:price_5m_blockA}"
  → code fills placeholders from DB  (LLM never types numbers itself)
  → VALIDATOR: any digit/currency/size/date in final text must trace to a fact ID
  → send / revise / human
  → audit log (every step, model version, prompt version, fact IDs)
  → lead record + lead brief + follow-up reminder
```

**Principle:** Laya decides, Qwen writes, llama.cpp serves, application controls, database proves, validator checks, human handles exceptions.

---

## 5. HARD RULES (every AI must follow)

1. The LLM never invents prices, availability, payment plans, locations, legal status, booking terms, or returns. Those come from the DB or the answer is "let me confirm with our team".
2. No production factual answer without `source_id`, `verified_by`, `verified_at`, `valid_until`.
3. Legal/approval/NOC/title, discounts, booking, refunds, and investment-return questions always route to a human.
4. Do not market or treat smoke-test results as reliability evidence.
5. Preserve the Laya + llama.cpp + Qwen architecture; keep each component behind an interface so it can be swapped *after* evaluation shows a need. No fine-tuning, ONNX, MCP, or new models before measured failures justify them.
6. Prefer boring tools: SQLite, FastAPI, pytest, GitHub Actions. No Postgres/Docker/Terraform/OpenTelemetry/Vault until a pilot is signed.
7. Give exact Windows/PowerShell commands, and say which PowerShell window each belongs in. Don't assume paths; use the known ones above.
8. Anonymize customer data (names, phone numbers) before sending any text to a cloud API.
9. No secrets in files, chats, or Git.

---

## 6. REVIEW FINDINGS — MISTAKES, RISKS, AND FASTER PATHS

**A. Timeline conflict.** The roadmap is a 90-day plan; the goal is 3–4 days. Both are right for different scopes: 3–4 days delivers a working **assisted-mode MVP** passing gates G0–G2 (data, offline eval, safety) and ready to enter shadow mode (G3). Gates G3–G7 depend on real traffic and a paying dealer and cannot be compressed into 4 days of coding.

**B. Paid pilot is scheduled last (day 90). Move it to day 1.** Commercial proof is the real bottleneck. Start dealer conversations now, in parallel, with a demo; try to get a written pilot/LOI by day 4–10.

**C. Laya is assumed to be the right decision engine without evidence.** Its own guide warns base checkpoints aren't reliably accurate, `score` is weakest, negation is hard, and non-English needs care. "Freeze the architecture" is right for avoiding churn, but **benchmark Laya against two baselines** on the same golden set: (1) keyword/regex rules, (2) an LLM classifier via OpenRouter with JSON output. Use whichever wins per question; Laya stays if it earns its place (speed, offline, cost).

**D. Qwen 1.5B is weak at Urdu/Roman Urdu and at following constraints.** Mitigation: placeholder-template generation + validator (Section 4). Test Qwen vs. a cheap cloud model on the golden set; if Qwen fails on language quality, use a cloud model for drafting only (with anonymized input and the same validator).

**E. WhatsApp-first is the wrong first integration.** Fastest valuable pilot: a **web "Agent Console"** where the agent pastes the customer message and instantly gets classification, retrieved facts, draft reply, and a lead brief. That skips WhatsApp API approval/ban risk (avoid unofficial WhatsApp libraries) and still proves response-time and qualification value. Add Meta WhatsApp Cloud API after the pilot is real.

**F. Roadmap's infrastructure is overbuilt for week 1** (Postgres, Terraform, Vault, OTel, Grafana, Celery). The roadmap itself lists "overbuilding" as a failure mode. MVP stack: SQLite + FastAPI + pytest + GitHub Actions + a simple scheduler. Migrate when a pilot is signed.

**G. Evaluation-set numbers differ between documents** (50–100 in the handoff vs 150+ in the roadmap). Resolve: start with 60 to unblock, grow to 150+ within the week. Bootstrap fast: have a strong model generate ~200 *synthetic* messages (English/Urdu/Roman Urdu, typos, negation, mixed intent, injection attempts), then the human corrects labels in 1–2 hours. Replace/augment with real anonymized messages from the dealer as soon as available. Mark synthetic rows `source: synthetic`.

**H. Hardware reality.** 4 GB RAM + a 16–24 GB page file means paging, slow latency, and instability if too many apps run. Don't run AnythingLLM, Ollama, a heavy IDE, and both servers at once. Verify the page file is on the fastest drive available; measure end-to-end latency early. A cheap VPS can host the pilot later.

**I. Data authority is the true moat and the true risk.** Without an owner-approved Faisal Hills fact pack, nothing is production-safe. Never use public web pages as truth. Seed the DB with clearly flagged `demo=1` rows so the pipeline can be built now; swap in real verified rows when the dealer supplies them.

**J. Privacy/security.** Customer messages contain PII. Scrub before cloud calls, store minimal data, keep audit logs, restrict access. Keys only in env vars.

**K. Do not rely on Laya confidence thresholds** until calibrated on labeled data (Phase D in the handoff).

---

## 7. THE 3–4 DAY PLAN (≈10 h/day)

**Definition of done for the 4-day MVP:**
- Agent Console runs locally; paste message → decision, facts, draft, lead brief, audit log.
- ≥150 labeled eval examples + a 30-case red-team set; automated eval report.
- Policy gate + retrieval + placeholder generation + validator working.
- Unsupported-claim leakage on the red-team set = 0 in tests.
- CI runs tests on every change. Demo script + one-page pilot offer ready.

### Day 0 — Setup (1–1.5 h)
1. `git init` in `D:\AI-Projects\laya-gateway`; add `.gitignore` (`.env`, logs, `hf_cache`, DB files); commit current scripts. Put this file in the repo root as `PROJECT_STATE.md`.
2. Start Laya and llama.cpp; run `integration_test.py`; note latency.
3. Set up OpenRouter + a coding assistant (Section 9).
4. Message the dealer: request the official document pack, named data owners, and 20 minutes to demo (Section 10).

### Day 1 — Data + evaluation foundation
- (1 h) SQLite schema with provenance columns: `society_master, blocks, inventory, pricing, payment_plans, legal_facts, faqs, lead_examples, agent_roster, leads, audit_log, fact_sources`. Every fact row: `fact_id, value, source_id, verified_by, verified_at, valid_until, demo`.
- (1 h) Seed demo rows (clearly flagged); loader that **rejects** rows missing provenance/stale dates/duplicates/invalid prices (pandera or plain checks).
- (2.5 h) Golden set: generate synthetic, human-correct, save to `evaluation\datasets\production\golden_v1.jsonl`. Fields: `id, message, language, lead_type, high_intent, needs_human, intent, facts_needed, expected_action, risk_tags, source`. Use UTF-8 **without BOM**.
- (2.5 h) Eval runner: runs Laya, rules baseline, LLM baseline; reports per-question accuracy, confusion matrix, failures by category (negation, short, mixed, Roman Urdu, injection).
- (1 h) Review failures; pick the decision method per question; commit.
- *Exit:* report exists; decision method chosen per question with evidence.

### Day 2 — Control pipeline
- (2 h) Policy gate (deterministic rules + Laya signals) with refusal/escalation tests.
- (2 h) Entity extraction (size/marla, block/series, budget, timeline) with JSON-schema output; tests.
- (1.5 h) Retrieval by entities → fact IDs + freshness + conflict flags.
- (2 h) Generation with fact placeholders → substitution → **validator** (every number/currency/size/date must trace to a fact ID; otherwise block/revise/human).
- (1.5 h) Audit logging for every step. Red-team set (30 cases: price invention, legal asks, discount pressure, prompt injection, stale data, abusive text).
- *Exit:* zero unsupported-claim leaks on red-team tests.

### Day 3 — Workflow, Agent Console, CI
- (3 h) FastAPI + minimal HTML console: paste message → decision, facts used, draft, edit/approve/reject, lead brief.
- (2 h) Lead record states (new → qualified → handoff → site-visit → closed/lost), agent assignment from roster, follow-up reminders, CSV export.
- (1.5 h) GitHub Actions: lint, pytest, data-quality checks, golden-set regression; fail on metric drop.
- (2 h) End-to-end evaluation on the golden set: grounding accuracy, escalation recall on risky intents, language quality, latency per step on the 4 GB machine.
- (1.5 h) Fix top failure categories.

### Day 4 — Hardening, demo, pilot pitch
- (2 h) Fix remaining top failures; confirm latency acceptable; rollback switch ("AI off, human only").
- (1.5 h) Demo script: 10 scenarios incl. a refusal, an escalation, a stale-fact block.
- (1 h) One-page pilot offer + weekly scorecard template (Section 10).
- (2 h) Demo to 3–5 dealers; collect objections and data access.
- (1.5 h) Update this file (Progress Log, decisions, next steps); tag release `v0.1-assisted-mvp`.
- *Exit:* demo-ready MVP; at least one dealer conversation moving toward a written pilot.

**After day 4:** run **shadow mode** on real traffic (G3), capture baseline metrics, then **assisted pilot** (G4) with weekly error review. Limited auto-replies only after G5.

---

## 8. REPO LAYOUT (target)

```
D:\AI-Projects\laya-gateway\
  PROJECT_STATE.md            (this file)
  app\                        FastAPI app, console, policy, retrieval, validator
  clients\                    laya_client.py, llama_client.py, openrouter_client.py (swappable interfaces)
  data\                       schema.sql, loaders, demo seed, quality checks
  evaluation\datasets\production\golden_v1.jsonl, redteam_v1.jsonl
  evaluation\reports\
  tests\
  logs\
  .github\workflows\ci.yml
  .env.example                (names only, no values)
```

---

## 9. KEEP WORKING WHEN CLAUDE LIMITS HIT — OPENROUTER SETUP

**OpenRouter basics (OpenAI-compatible):** base URL `https://openrouter.ai/api/v1`, one API key, many models. Free models have IDs ending in `:free`. As documented by OpenRouter: free variants allow 20 requests/minute; 50 requests/day if you've purchased under $10 of credits, 1,000/day after buying at least $10 once. A negative balance returns 402 even on free models. Free models rotate, so check the current list at openrouter.ai/models. Agentic coding tools can burn through 50 requests quickly, so **buy $10 of credits** (also gives you paid-model access for harder tasks) and keep a positive balance.

**Setup steps**
1. Create an account at openrouter.ai → Keys → create a key. Set it as an environment variable (PowerShell): `setx OPENROUTER_API_KEY "your-key"` then open a new window.
2. Check usage/limits anytime: `GET https://openrouter.ai/api/v1/key`.
3. Use a **fallback list** of models in requests so rate limits or outages don't stop work.

**Tools to link to OpenRouter (pick one primary for coding)**
- **aider** (terminal; lightest on 4 GB RAM): `pip install aider-chat`, then e.g. `aider --model openrouter/<provider>/<model>`. Works well with Git repos.
- **Cline or Roo Code** (VS Code extensions): choose "OpenRouter" as provider and paste the key (heavier on RAM).
- **AnythingLLM**: Settings → LLM Preference → OpenRouter → key + model. Good for chatting with your documents, not for editing code. (Menu labels may change.)
- Choose models by task: a strong reasoning/coding model for architecture and debugging; a cheaper/free model for boilerplate and tests. Sort openrouter.ai/models by programming rankings and pick current leaders rather than trusting any fixed list.

**Context discipline (this is what makes switching AIs painless)**
- Start every session by pasting `PROJECT_STATE.md`.
- End every session by asking the AI to update Section 12 and to list the next 3 tasks; commit.
- Small commits; one task per prompt; ask for exact files changed.

**Handoff prompt to paste at the start of any new AI session**
```
You are my senior engineer on the Faisal Hills AI Lead Desk. Read PROJECT_STATE.md fully
and follow its HARD RULES. Do not redesign the architecture. Work only on the next task in
the Progress Log. Give exact Windows/PowerShell commands and name the window each belongs in.
Never invent business facts. When done, update the Progress Log and list the next 3 tasks.
```

---

## 10. COMMERCIAL PLAN

**Offer:** managed "24/7 Faisal Hills AI Lead Desk" for one dealer/agency. Human approval on every reply during the pilot.

**Pre-sell now:** the demo (Day 4) plus a short written pilot: duration (e.g., 30 days), what dealer provides (official data pack, named owner, access to message history), success metrics, price, and data-handling terms. Don't wait for the product to be "finished".

**Weekly scorecard (vs. pre-AI baseline):** first-response time, response coverage, qualification completion, qualified-lead rate, human handoff rate, site-visit booking and show-up rates, booking rate, AI-attributable revenue, cost per qualified lead/site visit, agent hours saved, opt-out rate, factual correction rate, escalation rate.

**Path to the 100 crore ambition (illustrative arithmetic, not a forecast):** PKR 100 crore = 1,000,000,000. If a managed desk were priced at PKR 150,000/month (PKR 1.8M/year per client), 100 crore of *annual revenue* would need roughly 555 clients; a *company valuation* of 100 crore at a typical 5–10× revenue multiple would need about 10–20 crore annual revenue, i.e. roughly 55–110 such clients. That implies: win one dealer → productize repeatable workflow → multi-tenant → many societies/cities, and consider performance-based pricing (per qualified lead or site visit) which scales with dealer results. Re-do this math with real pilot pricing.

**Gates (from roadmap):** G0 Data · G1 Offline · G2 Safety · G3 Shadow · G4 Assisted · G5 Limited automation · G6 Paid pilot · G7 Scale. Do not skip.

---

## 11. WHAT THE HUMAN OWNER MUST SUPPLY (AI cannot invent these)

1. Named owners: property-truth owner, sales/ops owner, product owner.
2. Official Faisal Hills document pack (maps, block info, price lists, payment plans, approval/legal documents) with dates.
3. 50–100 real inventory records (plot ID, size, block, status, price source, date).
4. Real customer messages (anonymized) for the golden set.
5. Agent roster (names, territories, availability) and the dealer's handoff process.
6. A decision on pilot price and terms.

---

## 12. PROGRESS LOG (update every session)

| Date | Done | Decisions | Next 3 tasks |
|---|---|---|---|
| 2026-10-04 | Handoff + roadmap reviewed; this master file created | 4-day MVP scope = assisted mode through G2; Agent Console before WhatsApp; SQLite+FastAPI; benchmark Laya vs baselines; placeholder-based generation with validator | 1) Day 0 setup (git, OpenRouter, tooling) 2) SQLite schema + provenance checks 3) Golden set v1 + eval runner |

**Open questions:** exact `llama-server.exe` path; page file drive speed (SSD vs HDD); current end-to-end latency; which dealer is the pilot target.

---

## 13. SOURCE DOCUMENTS (summarized above)

- `Laya_Local_AI_System_Handoff.md` — technical setup and verified state.
- `Faisal_Hills_AI_Next_Actions_and_Production_Roadmap.docx` — production gates, 90-day plan, data package, automation blueprint, commercial scorecard, failure modes.
