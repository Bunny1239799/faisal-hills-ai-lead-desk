# M11 PLAN - the multi-turn conversation and the operator desk, in ONE application

**Date:** 2026-10-22
**Status:** **APPROVED (self-approval under owner authorization A4)** - approved because it (a) reuses the existing components unchanged, (b) introduces no second intelligence engine, (c) loosens no threshold, no privacy rule, no price rule and no claim rule, (d) creates every new file under this repository, and (e) can be rolled back file by file.
**Goal:** a dealer conversation builds a qualification state, reaches the existing decision engine, and shows the operator everything - in one application, with no live model call.

---

## 0. The one rule that governs everything below

> The application owns truth. The model only phrases. **No new decision logic.**

M11 adds a **lead-state record**, a **normalizer**, a **turn pipeline**, an
**endpoint**, an **operator page** and **golden conversations**. It does not
add a decision rule, a price rule, a policy rule or a qualification rule. Every
decision still comes from `market\qualify.py`, `market\decision.py`,
`market\recommend.py`, `market\price_lookup.py`, `market\fact_validator.py` and
`market\reply_guard.py`, exactly as before.

---

## 1. Files to add or change

### New (all under this repository)

| file | purpose | M11 step |
|---|---|---|
| `market\lead_state.py` | the lead-state schema: five fields, each with value, status and source turn, plus the change log | M11.1 |
| `market\normalize.py` | the input normalizer: lakh/crore/M, marla spellings, dimension names, block names, Roman Urdu basics | M11.2 |
| `app\turn_pipeline.py` | the turn pipeline: message + state -> decision -> approved lookup -> verified facts -> recommendation -> optional phrasing -> numeric validation -> claim guard -> reply -> new state | M11.3 |
| `market\unmet_demand.py` | the unmet-demand record: size, block, budget band - and nothing else | M11.4 |
| `app\static\operator.html` | the operator page: conversation / qualification state / verified options / next action / take-over | M11.5 |
| `tests\golden\*.json` | 15 scripted multi-turn conversations with the expected lead state and route after every turn | M11.6 |
| `tests\test_m11_lead_state.py` | M11.1 tests | M11.1 |
| `tests\test_m11_normalizer.py` | M11.2 tests | M11.2 |
| `tests\test_m11_turn_pipeline.py` | M11.3 tests | M11.3 |
| `tests\test_m11_conversation_endpoint.py` | M11.4 tests | M11.4 |
| `tests\test_m11_operator_page.py` | M11.5 tests | M11.5 |
| `tests\test_m11_golden_conversations.py` | M11.6 - replays all 15 golden conversations | M11.6 |
| `docs\reports\m11_*.md` | one report per sub-step, with the raw output | every step |

### Changed

| file | change | why |
|---|---|---|
| `app\server.py` | **one** new route `POST /api/conversation`, **one** `GET /api/conversation/{session_id}`, **one** `GET /api/unmet-demand`, and a `GET /operator` that serves the operator page | M11.4, M11.5 |
| `docs\M11_PLAN.md` | this plan | Phase 4 |
| `DEFECTS.md`, `PROGRESS.md`, `CHECKPOINT.md`, `DECISIONS.md` | the M11 record, after each sub-step verifies | A3 |

### NOT changed

`app\policy.py`, `app\policy_extra.py`, `market\qualify.py`, `market\decision.py`,
`market\recommend.py`, `market\price_lookup.py`, `market\fact_validator.py`,
`market\reply_guard.py`, `market\evidence.py`, `market\conversation.py`,
`config\policies.json`, `config\questions.json`, `data\schema.sql`,
`data\db.py`, the protected files, the approved master, the owner's database.

---

## 2. The lead-state schema (M11.1)

`market\lead_state.py`, stdlib-only.

```python
FIELDS = ("size", "block", "budget", "purpose", "timeline")

STATUS_UNKNOWN   = "unknown"     # never stated
STATUS_STATED    = "stated"      # stated by the dealer
STATUS_CORRECTED = "corrected"   # stated, then changed by the dealer
```

Each field is a record:

```python
{
  "value": <the value or None>,
  "status": "unknown" | "stated" | "corrected",
  "source_turn": <int, the 1-based turn the current value came from> | None,
}
```

| field | value form | source of truth |
|---|---|---|
| `size` | marla as a float (`7.0`), or `None` | the dealer's own words, via `market\qualify.extract_requirements` |
| `block` | `"A"`, `"B"` or `"C"`, or `None` | the dealer's own words, via `market\qualify.extract_requirements` |
| `budget` | `{"min_pkr": <int|None>, "max_pkr": <int|None>}`, or `None` | the dealer's own words, via `market\qualify.extract_requirements` |
| `purpose` | a short string, or `None` | the dealer's own words |
| `timeline` | a short string, or `None` | the dealer's own words |

**Unknown stays explicitly unknown.** A field that was never stated is
`{"value": None, "status": "unknown", "source_turn": None}` - never `None`,
never a guess, never a default. The operator page shows the unknown fields
explicitly, because "the dealer never said" is the reason to ask.

**A correction replaces the old value and records the change.** When a field
is stated again with a *different* value:

* the old value is **replaced**;
* the status becomes `corrected`;
* `source_turn` becomes the turn that produced the new value;
* a change record is appended to `state.changes`:
  `{"field": ..., "old": ..., "new": ..., "turn": ...}`.

Stating the *same* value again is not a correction: the status stays `stated`,
`source_turn` moves to the latest turn, and no change is recorded.

**The state is a record, not a second authority.** The values come from
`market\qualify.extract_requirements` (the M9 extractor) and from the
conversation's own re-derived requirements (`market\conversation`), so M11
never invents a requirement. The pipeline's own state is a **cache with
provenance**; where they disagree, the M9 values win.

**Storage.** The state is stored in a **separate** SQLite file
(`data/m11_lead_state.db`, path overridable by the `M11_STATE_DB` environment
variable, and by an argument in the tests), with one table:

```sql
CREATE TABLE IF NOT EXISTS lead_state (
    session_id TEXT PRIMARY KEY,
    state_json TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
```

The owner's `faisal_hills.db` is **not** touched: no new table is added to it
and no residue is removed from it. The existing `leads` / `messages` /
`audit_log` rows the pipeline already writes are left exactly as they are.

---

## 3. The input normalizer (M11.2)

`market\normalize.py`, stdlib-only.

```python
def normalize_message(text: str) -> NormalizedMessage
# NormalizedMessage(text=<canonical text>, changes=[("amount", "80 lakh", "80000000"), ...])
```

What it does, and only these things:

| what | example | result |
|---|---|---|
| amounts | "80 lakh", "80 lac", "1 crore", "1.2 crore", "8M", "8 million", "8 mn" | `80000000`, `12000000`... written as a plain PKR figure |
| marla spellings | "5 marla", "5 marlas", "5marla", "5-marla", "5 marla ka plot" | `5 marla` |
| dimension names | "30x60", "35 x 70", "40x80", "50x90" | the marla size **from DEC-10's approved table only** (5m=25x50, 7m=30x60, 10m=35x70, 14m=40x80, 1 kanal=50x90 -> 20 marla, 2 kanal=75x120 -> 40 marla) |
| block names | "block c", "c block", "fhc", "block a mein" | `Block C` |
| Roman Urdu basics | "mein", "ka", "ki", "ke", "chahiye", "chahye", "walay" | dropped or ignored as filler |
| simple typos | "marala" -> marla, "blok" -> block | corrected, **only** for a fixed, tested list |

**Only the approved dealer terms already in the repo are used.** The amount
units (`lakh`, `lac`, `crore`, `M`, `million`, `mn`) are the units
`market\qualify` already understands; the dimension table is **DEC-10's**,
which is the only dimension table the repo has; the block aliases are
`market\price_lookup`'s own alias table. **No new dealer term and no new
business definition is introduced.** Anything the normalizer does not
recognise is **left exactly as it is** - the normalizer never guesses.

**The normalizer never changes meaning.** It is *idempotent* (normalizing a
normalized message changes nothing), and a message it does not recognise is
returned unchanged. Its output is what the pipeline stores and what the
extractor reads, so the conversation's re-derived requirements and the
lead-state record agree.

---

## 4. The turn pipeline (M11.3)

`app\turn_pipeline.py`.

```python
def run_turn(
    message: str,
    session_id: str,
    *,
    state: Optional[LeadState] = None,
    store: Optional[LeadStateStore] = None,
) -> TurnResult
```

`TurnResult` is a dict with:

```python
{
  "reply": str,                    # the final, validated, customer-facing text
  "lead_state": {...},             # the five fields, each with value/status/source_turn
  "route": "exact" | "alternative" | "clarify" | "escalate",
  "reason": str,                   # why this route, in the application's own words
  "escalation": bool,              # a human must act now
  "verified_options": [ {...} ],   # the options the application verified, with their reason
  "next_action": {...},            # the application's own next-best-action
  "unmet_demand": {...} | None,    # size, block, budget band - only when nothing was answered
  "turn": int,
  "changes": [ ... ],              # the corrections this turn produced
}
```

**The pipeline, in order - no step is skipped and no step is new:**

```
message
  -> normalizer (market.normalize.normalize_message)      # the canonical text
  -> policy (app.policy.evaluate_policy)                  # UNCHANGED
  -> application pipeline (app.pipeline.handle_message)   # UNCHANGED
       which itself runs: lookup -> facts -> recommendation -> M9 qualification
                -> M9 decision -> M5 numeric validator -> M6.1 claim guard
  -> lead state (market.lead_state)                       # the record with provenance
  -> route (from the M9 decision's action)                # no new decision logic
  -> unmet demand (market.unmet_demand)                   # only when nothing was answered
  -> reply                                                # the pipeline's own validated reply
```

**The route comes from the existing M9 decision**, never from a new rule:

| `market\decision` action | route |
|---|---|
| `quote_exact_match` | `exact` |
| `offer_verified_alternatives` | `alternative` |
| `ask_clarifying_question` | `clarify` |
| `escalate_to_human` | `escalate` |

**No live model call.** The pipeline uses the deterministic template path
(`reply_source == "deterministic_template"`). The phrasing port
(`app\customer_model.py`) stays in place and unchanged; M11 does not switch it
on, and no credential is read (owner default 3, H3).

---

## 5. The conversation endpoint (M11.4)

`POST /api/conversation` on the existing server.

**Request**

```
POST /api/conversation
Content-Type: application/x-www-form-urlencoded   (the server's existing style)
message=<the dealer's message>&session_id=<the session id>
```

`session_id` is optional; when it is missing the server generates one and
returns it.

**Response (200)**

```json
{
  "session_id": "…",
  "turn": 3,
  "reply": "…",
  "lead_state": {
    "size":     {"value": 7.0,  "status": "stated",    "source_turn": 2},
    "block":    {"value": "C",   "status": "stated",    "source_turn": 3},
    "budget":   {"value": {"min_pkr": 8000000, "max_pkr": 8000000},
                 "status": "stated", "source_turn": 4},
    "purpose":  {"value": null,  "status": "unknown",  "source_turn": null},
    "timeline": {"value": null,  "status": "unknown",  "source_turn": null}
  },
  "route": "exact",
  "reason": "the requested cell clears the evidence threshold and satisfies the stated requirements",
  "escalation": false,
  "verified_options": [
    {"block": "C", "size_marla": 7.0, "reason": "…", "verified": true}
  ],
  "next_action": {"action": "quote_exact_match", "label": "…", "reason": "…"},
  "unmet_demand": null,
  "changes": []
}
```

**What the endpoint never returns:** a raw plot number, a dealer name, a
note, a raw size, a sender identity, or a raw dealer message. The reply is the
pipeline's own validated reply, and the fact set behind it is the one the M5
validator and the M6.1 guard already approved.

`GET /api/conversation/{session_id}` returns the same object **without** a new
turn (the current state, the conversation so far, the unmet-demand count) -
this is what the operator page polls.

`GET /api/unmet-demand` returns the **count** and the distinct demand shapes
(size, block, budget band) - no message text, no lead id.

---

## 6. The operator page (M11.5)

One plain HTML page, `app\static\operator.html`, served by the **existing**
server at `GET /operator`. No framework, no build step, no new dependency.

Three panels, side by side on a wide screen and stacked on a narrow one:

1. **Conversation** - the messages so far (the dealer's words and the draft
   reply), and a box to type the next message. The draft is **not** sent
   automatically: the operator sees the draft and sends it (owner default 1,
   shadow mode).
2. **Qualification state** - the five fields, each with its value, its status
   (`unknown` / `stated` / `corrected`) and the turn it came from. The
   **unknown** fields are shown explicitly and highlighted, because a missing
   requirement is the reason to ask the next question. A correction is shown
   as "was X (turn n) -> now Y (turn m)".
3. **Verified options and next action** - the options the application
   verified, each with its **reason** (the application's own explanation),
   the **next action**, the **escalation flag**, and a **Take over** button.
   The take-over button switches the lead to human handling (it records that
   a human has taken over; it never sends anything to a dealer by itself).
   A small **unmet demand counter** sits at the top.

The page is plain HTML + a little vanilla JavaScript. It calls
`POST /api/conversation` and `GET /api/conversation/{session_id}` and renders
the JSON the endpoint returns. It never renders a raw plot number, because
the endpoint never sends one.

---

## 7. The golden conversations (M11.6)

15 scripted multi-turn conversations in `tests\golden\`, one JSON file each,
in this shape:

```json
{
  "id": "flow-investment",
  "title": "the five-turn investment flow",
  "turns": [
    {
      "message": "I need a plot",
      "expected_route": "clarify",
      "expected_lead_state": {
        "size": {"value": null, "status": "unknown", "source_turn": null},
        "block": {"value": null, "status": "unknown", "source_turn": null},
        "budget": {"value": null, "status": "unknown", "source_turn": null},
        "purpose": {"value": null, "status": "unknown", "source_turn": null},
        "timeline": {"value": null, "status": "unknown", "source_turn": null}
      }
    }
  ]
}
```

**Every expected value comes from the approved data and the existing rules,
never from a guess.** The sizes, blocks and budgets in the golden files are
cells the master covers; the routes are the ones the M9 decision produces for
those cells; the thin cells are the three the master says are thin
(A/14, B/7, C/10 marla - 2 listings each, so the route is `clarify` and the
reply carries no price).

The 15 conversations:

| # | file | what it proves |
|---|---|---|
| 1 | `flow_investment.json` | the five-turn flow: "I need a plot" -> "5 marla" -> "Block C" -> "around 8 million" -> "for investment" |
| 2 | `flow_correction_budget.json` | a mid-conversation correction ("actually 12 million") - the old value is replaced and the change is recorded |
| 3 | `flow_correction_size.json` | a size correction ("actually 7 marla") |
| 4 | `thin_a_14_marla.json` | a thin cell: A/14 -> no price, a clarifying question |
| 5 | `thin_b_7_marla.json` | a thin cell: B/7 -> no price, a clarifying question |
| 6 | `thin_c_10_marla.json` | a thin cell: C/10 -> no price, a clarifying question |
| 7 | `out_of_scope_block_d.json` | a parked block -> escalate, no price |
| 8 | `discount_request.json` | a discount request -> escalate, no price (the D-65 fix, in a conversation) |
| 9 | `booking_request.json` | a booking / legal / availability request -> escalate, no price |
| 10 | `roman_urdu_amount.json` | "80 lakh" / "1 crore" -> the same budget as the English flow |
| 11 | `no_match.json` | a cell the master does not cover at all -> no verified answer, an unmet-demand record |
| 12 | `requirement_only_budget.json` | a requirement-only turn ("my budget is 8 million") -> the decision is still reached |
| 13 | `purpose_and_timeline.json` | purpose and timeline are recorded and narrow nothing |
| 14 | `out_of_scope_executive.json` | the Executive block -> escalate |
| 15 | `partial_then_exact.json` | a partial cell first, then a complete one -> the reply follows the state |

The replay test asserts, for every turn of every conversation: the **route**,
the **lead state** (value, status and source turn of all five fields), that
the reply carries **no price** when the route is `clarify` or `escalate`,
that the reply carries **no price** when the cell is thin, and that the
whole replay leaks **no** dealer name, plot number, note or raw size.

---

## 8. The test list

| sub-step | test module | what it proves |
|---|---|---|
| M11.1 | `tests\test_m11_lead_state.py` | the five fields; unknown stays unknown; a correction replaces the value and records the change; a re-statement is not a correction; the state round-trips through the store; a lead that cannot be read yields an all-unknown state (fail-closed) |
| M11.2 | `tests\test_m11_normalizer.py` | each amount unit; each marla spelling; each DEC-10 dimension; each block alias; the Roman Urdu fillers; idempotence; an unrecognised message is returned unchanged; **the normalizer never invents a size, a block or a budget** |
| M11.3 | `tests\test_m11_turn_pipeline.py` | the turn pipeline reaches the decision layer; the four routes; the reply is the pipeline's own validated reply; the gates still run (traceability + claim guard); no live model call; the state accumulates across turns |
| M11.4 | `tests\test_m11_conversation_endpoint.py` | the endpoint contract; the response carries no plot number, name, note or raw size; the unmet-demand record carries size, block and budget band only; an unknown session yields an all-unknown state |
| M11.5 | `tests\test_m11_operator_page.py` | the page is served by the existing server; it shows the three panels; it shows the unknowns; it shows the recommendation reason, the next action and the take-over control; it contains no plot number |
| M11.6 | `tests\test_m11_golden_conversations.py` | all 15 conversations replay; every route and every lead state matches; the privacy and price-leak checks hold across the whole replay |

---

## 9. Risks

| risk | why it is real | how it is handled |
|---|---|---|
| **A second intelligence engine** | a turn pipeline is exactly where a new decision rule creeps in | the route is read from the M9 decision; M11 adds no decision, price, policy or qualification rule; the M11 modules are checked by the review in section 10 |
| **The normalizer changes meaning** | rewriting a dealer's words can silently change what they asked for | only a fixed, tested list of rewrites; idempotence is tested; anything unrecognised is left alone; the golden conversations replay the real sentences |
| **The lead state drifts from the conversation** | a cached record can disagree with the re-derived requirements | the M9 requirements win; the state records the provenance of what it holds; the change log shows every replacement |
| **A new database in the owner's tree** | the M11 store is a new file | it is a **separate** SQLite file, the owner's `faisal_hills.db` is untouched, and the tests use a temporary file |
| **The endpoint becomes a privacy hole** | a new surface can serve what the old surfaces refused | the endpoint returns only the pipeline's validated reply and the whitelisted state; the tests assert that no plot number, name, note or raw size appears |
| **The operator page becomes a sending machine** | an operator UI can act without a human | the page is a **draft** surface: the draft is shown, the human sends it; the take-over button only records that a human has taken over |
| **The golden conversations encode a guess** | an expected value written by hand can be wrong | every expected value is taken from the approved master and the existing rules, and the replay compares against the **application's own** measured behaviour for the thin and the out-of-scope cases |
| **A regression in the existing suite** | a change in the serving path can break an earlier milestone | every sub-step runs the **full** suite and the eight gates before the next sub-step starts; a failure reverts from the backup (H6) |

---

## 10. The self-approval check for this plan

* the previous step's raw output shows the full suite passing - **775 passed**;
* price-leak 0, privacy 0, robustness 0, scope FOLLOWS, M6.1 0, audit 20/20;
* the master-data hash is unchanged and the protected files are unchanged;
* `git status` shows nothing staged and nothing committed;
* the change is the smallest that solves the problem and **reuses** the
  existing components - M11 adds no rule, only a record, a normalizer, an
  orchestration function, an endpoint, a page and a test corpus;
* every new file is inside this repository, and every changed file has a
  backup and a rollback command.

**Approved. Proceeding to M11.1.**
