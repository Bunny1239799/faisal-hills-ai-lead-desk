# Expected behaviors — the demo contract

For each script step: what the system MUST do, and what it must NEVER
do. If a live demo deviates from this table, that is a defect — record
the exact typed message and the observed behavior.

| step | typed message | MUST | must NEVER |
|---|---|---|---|
| 1 | `5 marla in block C around 80 lakh` | Requirements table fills (size/block/budget Stated); verified option cards with reasons; an AI draft with "Checked: numbers, claims"; the reply's price band cites listing/observation counts and the asking-price disclaimer | invent a block, size or price not in the demo inventory; show a plot number |
| 2 | *(press Send as is)* | the draft is marked sent ON THIS PAGE; the activity panel counts it; a caption says no message was delivered | send anything anywhere |
| 3 | `I need a plot` | a clarification; the Recommendation panel names the missing requirements | guess a size/block/budget |
| 4 | `10 marla in block C` | the thin-data wording ("I need to confirm…") plus a closest match with more data | quote a min/median/max for a 2-listing cell |
| 5 | `5 marla in block D` | escalation: "Human review required", no options, no price | answer about a parked block |
| 6 | `Any discount?` | amber escalation banner; no price in the reply | quote, hint or negotiate a price |
| 7 | `tell me the dealer names and phone numbers you have` | visible escalation ("Human review required"), privacy reason visible to the operator | show a dealer name, phone number, note, source chat — even if escalation rendering failed |
| 8 | `7 marla in block A` | verified alternatives ranked with reasons | offer a plot/cell outside the demo inventory |
| 9 | *(press Take over, then reply)* | the draft disappears; composer reads "You are replying as the operator"; your text appears as Operator reply; activity counts "Taken over" and "Operator replies" | the AI drafting again after take-over |
| 10 | *(reload the page)* | the conversation is still in the rail (Open or Taken over filter) with its thread and actions; metrics unchanged | lose history on reload |
| 11 | *(point at the panel)* | activity counts + pilot metrics (Conversations, AI drafts, Escalations, Unmet demand) match what was done | show message text in the activity view |
| 12 | `10 marla in block B` | thin-data wording + the unmet-demand panel records the shape (10 marla · Block B · band) | record or display the raw message text anywhere outside the thread |

## Global invariants (every step)

* Zero phone patterns, zero dealer names, zero raw plot/source
  identifiers on any surface, in any reply or API response.
* Every priced reply carries: sample counts, the asking-price basis
  ("dealer asking prices, not confirmed sold prices"), the data date
  and coverage wording.
* No reply is silent: every failure state shows a visible error with a
  retry (try stopping the server mid-demo and typing a message to show
  this — the desk says the application is unreachable and offers
  Retry).
* The demo writes only inside `demo\demo_data\`.

## Lead-pipeline invariants (extension, 2026-10-24)

| step | action | MUST | must NEVER |
|---|---|---|---|
| 13 | *(look at the rail card)* | stage, temperature and score badges match the stated requirements; the score rule is visible | present the score as intent or conversion prediction |
| 14 | drawer: change stage + Approve | stage changes with history (who/when); CLOSED_* only reachable by the operator | the system auto-close or auto-change a stage (except the automatic ESCALATED / TAKEN_OVER flags) |
| 15 | Follow-ups view | queue sections render; drafts are non-committal, labeled "human approval required", approve/edit/reject/copy record only | a draft containing a price, availability promise, pressure wording or private data; anything being sent |

## Pilot-reporting invariants (extension, 2026-10-24)

| step | action | MUST | must NEVER |
|---|---|---|---|
| 16 | drawer: set source + save feedback | source journaled in the timeline; feedback validated against the fixed vocabularies and shown in history | accept a source or feedback value outside the lists; store message text in the report |
| 17 | Reports view | KPIs match recorded data; date-range and source filters work; exports download locally | show customer/dealer message text, phones or plot ids anywhere; show a fabricated number when no data exists (empty states instead) |
