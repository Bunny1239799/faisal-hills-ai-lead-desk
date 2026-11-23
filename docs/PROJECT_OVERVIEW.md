# Faisal Hills AI Lead Desk — Project Overview

**One line:** an operator-first lead desk that answers real-estate buyers
strictly from a versioned, fingerprinted master inventory, drafts every reply
for human approval, and refuses — by construction — to serve a number it
cannot trace.

- **Founder:** Muhammad Hanzala
- **Stage:** production pilot on the owner machine (real dealer workflow,
  shadow mode: the application drafts, humans send)
- **Stack:** Python (stdlib core + SQLite), FastAPI/uvicorn console, plain
  HTML/CSS/JS front end (no build step), pytest (1,189 offline tests)
- **Cost to run:** zero — no LLM API, no cloud dependency, fully offline

## The problem

Real-estate agencies lose deals and trust the same way: someone answers a
buyer from memory, quotes a price that is no longer true, or an AI bot
hallucinates one. WhatsApp is the medium, so the damage is instant and
visible. Existing AI assistants either need a paid LLM (and still invent
numbers) or are too dumb to qualify a buyer.

## The solution

A desk where the application, not a person, does the heavy lifting:

1. **Qualify** — every turn extracts and tracks size / block / budget /
   purpose / timeline, with corrections handled mid-conversation
   (Roman-Urdu amounts like "budget 80 lakh hai" included).
2. **Answer only from the approved master** — prices come from one
   fingerprinted master inventory with per-cell observation counts and date
   ranges; the desk shows exactly which master it is serving.
3. **Guard every word** — fact guard + claim guard trace each number and
   claim in a draft back to the master; anything untraceable is detached and
   the turn escalates to a human. A permanent test walks **every** API route
   to prove each one is guarded.
4. **Draft, never send** — the operator sees the draft, its evidence and its
   options; sending is a human action. No send capability exists in the code.
5. **Escalate what matters** — discounts, out-of-scope blocks, availability
   claims and booking requests route to a human, with take-over recorded.
6. **Learn the market** — requests the master cannot satisfy land in an
   unmet-demand log; the weekly owner report turns them into inventory
   decisions.

## What an evaluator can check (not just believe)

- 1,189 offline tests, including a surface-completeness test that proves
  every serving route is guard-covered.
- A live **System status** view whose numbers are computed at request time
  from the running server — and a test that proves it cannot carry market
  figures or private fields.
- A verification matrix with per-component evidence: `docs/VERIFICATION.md`.
- The transcript replays exactly what was served — including each turn's
  verified options — so the demo is reproducible.

## Architecture in one paragraph

The turn pipeline (`app/turn_pipeline.py`) normalises the dealer's words,
updates the lead state, routes via the policy engine (exact / alternative /
clarify / escalate), looks up the approved master (`market/fh_query.py`,
`market/price_lookup.py`), guards the draft (`market/fact_guard.py`,
`market/fact_validator.py`), and persists the turn for replay
(`market/conversation_log.py`) alongside lead state, pipeline, unmet demand
and pilot feedback stores — each an isolated SQLite file that fails closed.
The console (`app/server.py`) serves ~50 routes, each guard-checked, to a
zero-build front end. An inventory workspace adds a versioned lifecycle
(upload → validate → review → approve → activate → rollback) with an audit
trail.

## Metrics that matter

| Metric | Value |
|---|---|
| Offline tests passing | 1,189 (see evidence file) |
| Serving routes guard-covered | all (enforced by test) |
| Auto-sent messages | 0 — no send capability exists |
| Runtime dependencies | Python stdlib + SQLite (fastapi/uvicorn for the console, pytest for tests) |
| Master fingerprint served | `b77b3cb5 · 374 rows · 2026-09-22→2026-10-07` |
| Private data in the share package | none — databases, logs and backups are excluded by the packaging script |

## Roadmap

Shipped: operator desk, qualification, guarded pricing, verified
alternatives, take-over, follow-ups, lead pipeline + scores, site-visit
requests, unmet demand, pilot feedback, weekly reports, inventory workspace,
system status. Planned (marked "Soon" in the UI): 3D block visualization,
voice intake, sales intelligence, settings.
