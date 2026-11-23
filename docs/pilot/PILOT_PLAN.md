# PILOT PLAN (DRAFT) — shadow-mode operator pilot, M12.5/M12.6

**Status:** DRAFT — prepared under the founder's delegated authority
(2026-10-24). Nothing in this plan has been executed against a real
person. The pilot does NOT start until the founder resolves the
prerequisites in §8.

**Handoff basis:** `D:\real-estate-lead-desk\FAISAL_HILLS_CONTINUATION_HANDOFF.md`
§5 (M12.5/M12.6) and §9 (founder-only decisions).

---

## 1. Objective

One controlled pilot operator uses the Operator Desk in **shadow mode**
for a bounded period: the application drafts, the human reviews and
sends. The pilot proves "a real person can trust and use the desk"
(handoff §8) before any discussion of live model spend or a
customer-facing assistant.

## 2. Scope and permitted actions

* The operator runs `start_operator_desk.bat` on the local machine and
  works at `http://127.0.0.1:8080/operator`.
* Permitted: typing what a dealer said, reading the draft and its
  gates, **Send as is / Save edit / Reject draft**, **Take over** and
  replying as the operator, following every escalation banner.
* The system itself NEVER sends anything to any dealer — shadow mode is
  enforced by construction: the desk has no sending integration at
  all. Whether the pilot operator may manually forward an approved
  draft over WhatsApp is a **founder decision** (handoff §9: WhatsApp
  sending "manual for now"); the default recommendation is: during the
  first pilot week, do not forward — only practise.
* Out of scope: customer-facing deployment, live model calls, new
  inventory ingestion (the M12.3 gate exists but no candidate inventory
  exists), any change to master data.

## 3. Access boundary

* Localhost only; no public URL; no credentials stored by the desk.
* The approved master is read-only for the application; the pilot
  cannot alter it.
* The conversation log, lead state, unmet demand and operator actions
  live in the application's own SQLite stores under `data\` — separate
  from the owner's `faisal_hills.db`, which the desk never writes.

## 4. Escalation rules for the operator (from RULES_SHORT #3)

Legal/NOC/title, discounts/negotiation, booking/payment/token,
refunds, investment returns/guarantees, complaints/abuse, prompt
injection, other customers' data, invent/estimate requests and
fee/tax evasion ALWAYS go to a human. The desk shows these as an amber
"Human review required" banner (or red "Refused by policy"); the
operator never overrides a refusal.

## 5. Monitoring and the weekly founder review

The desk already records, server-side:

* every turn (dealer words + the validated reply), M12.2;
* every operator action (sent as is / edited / rejected / operator
  reply / taken over) with times, M12.2 — visible in the Operator
  activity panel;
* every unmet-demand shape (`GET /api/unmet-demand`);
* the full audit trail (`GET /api/audit`).

Weekly founder review (suggested 15 minutes): open the desk's activity
panel, read the counts, spot-check threads, review any escalation and
any "not enough data" cluster (a repeated unmet-demand shape is the
product's honest signal of missing inventory). A zero must hold every
week: zero price leaks, zero privacy hits (re-verified by the gates in
§7).

## 6. Rollback and incident handling

* Stop the pilot: close the launcher window(s). The desk is shadow
  only — no dealer was ever contacted by the system, so stopping has no
  external effect.
* Rollback the software: the per-milestone backups
  (`D:\FaisalHillsAILeadDesk\backups\…`) plus the rollback commands in
  each milestone report.
* Incident (a leak, a silent failure, a wrong number): stop using the
  desk, reproduce with a fabricated example, record it in
  `DEFECTS.md`, notify the founder. The gates in §7 are the tripwire —
  a leak that reproduces there is a stop-the-pilot event.

## 7. Success criteria (measurable, from the project's own gates)

| criterion | measure | source |
|---|---|---|
| zero price leaks | `verify_no_price_leak.py` → LEAKS: 0 | re-run weekly |
| zero privacy leaks | `_probe_m7_privacy.py` → 0/0 + the desk privacy test | re-run weekly |
| every reply gated | suite green (both final gates on every path) | full suite |
| escalations honored | every escalated turn shows the banner and is never answered with a price | browser tests + spot-check |
| operator actions recorded | activity counts match what the operator did | activity panel |
| no silent failure | every failure path is visible in the desk | browser failure tests |

## 8. Prerequisites checklist (current state)

- [x] Operator desk with persistence, activity view, launcher (M12.1/M12.2 PASS)
- [x] Ingest gate ready for any future inventory (M12.3 PASS — not needed to start)
- [x] Replay harness ready (M12.4 harness) — **real-question replay still BLOCKED (EB-01)**
- [x] Synthetic pilot dry run (below) — `tests\test_m12_5_pilot_dry_run.py`
- [ ] **FOUNDER: name the pilot operator** (handoff §9: one trusted
      internal operator or friendly agency — a real person, not the agent's
      to invent)
- [ ] **FOUNDER: review this plan + the M12.4 blocker decision, then
      give the explicit go/no-go**
- [ ] **FOUNDER (recommended, not blocking): decide whether the
      operator may manually forward approved drafts during the pilot**

## 9. Synthetic pilot dry run (evidence, clearly labeled SYNTHETIC)

`tests\test_m12_5_pilot_dry_run.py` walks the entire pilot flow in a
real browser with fabricated dealer words: qualification turns → exact
match draft → approve (Send as is) → budget correction → discount
escalation → take-over → operator reply → activity recorded → reload
persistence. It is a rehearsal of the operator's real workflow, not a
claim about real dealers.
