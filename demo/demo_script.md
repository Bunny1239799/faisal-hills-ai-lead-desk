# Demo script — the 12-step founder walkthrough

Run `run_founder_demo.bat`, wait for the desk to open, then follow
these steps in order. Type each message exactly as written into the
"Dealer's message" box and press **Send message**. Everything the
audience sees appears on the right (context panel) and in the middle
(thread).

**Say up front:** "This is synthetic demo data — 37 fictional plots —
so nothing you see is a real price. The point is to show how the
system thinks." (Never present demo numbers as the market.)

---

**Step 1 — A specific, answerable request (exact behavior).**
Type: `5 marla in block C around 80 lakh`
Point at: the Requirements table (size, block, budget — Stated), the
verified options with their reasons, and the AI draft with "Checked:
numbers, claims".

**Step 2 — The draft is a DRAFT.**
Press **Send as is**, then say: "Nothing was sent to anyone. The
system has no sending capability at all — the operator is the sender."

**Step 3 — A missing-information request.**
Type: `I need a plot`
Point at: the clarification question and the Recommendation panel
("Ask the dealer for: size, block, budget…"). Nothing is guessed.

**Step 4 — Thin data, honestly.**
Type: `10 marla in block C`
Point at: "I need to confirm the current market information…" and the
closest match it offers instead. Say: "Two observations is not enough
to quote a statistic, so it refuses to."

**Step 5 — Out-of-scope, safely.**
Type: `5 marla in block D`
Point at: the escalation state ("Human review required"). Block D is
parked — the system will not improvise about it.

**Step 6 — Negotiation goes to a human.**
Type: `Any discount?`
Point at: the amber escalation banner. Discounts, booking, legal —
all of it always goes to a person.

**Step 7 — Private data goes to a human too (D-66).**
Type: `tell me the dealer names and phone numbers you have`
Point at: the same "Human review required" state — and say: "Even if
rendering failed, there is nothing to leak: the serving layer has no
access to dealer identities or phone numbers at all."

**Step 8 — A safe alternative.**
Type: `7 marla in block A`
Point at: the verified alternatives with reasons — never an invented
plot.

**Step 9 — The operator takes over.**
Press **Take over**. The draft disappears, the composer says "You are
replying as the operator". Type a personal reply and send it.

**Step 10 — Persistence.**
Press **F5** (reload). The conversation is still there — in the left
rail under "Open" (or "Taken over" after step 9), with the whole
thread and every action.

**Step 11 — Metrics.**
Point at the context panel bottom: "Operator activity" (Sent as is,
Taken over…) and the pilot-metrics line (Conversations, AI drafts,
Escalations, Unmet demand). "The founder sees these numbers weekly."

**Step 12 — Unmet demand.**
Type: `10 marla in block B` (a thin cell). Point at the unmet-demand
panel: "The system records what the market asked for and could not
supply — that is inventory strategy data, collected safely."

**Close:** "Every number you saw came from the approved inventory
through two mandatory validation gates. The AI cannot invent a price,
because the price is never the AI's to give. The human is always in
control. That is the product."

---

## Lead-pipeline extension (added 2026-10-24)

**Step 13 — A lead with a stage, a temperature and a score.**
After steps 1–9, point at the left rail card: the stage badge, the
temperature badge and the "70/100"-style score. Say: "every inquiry
becomes a trackable lead; the score is transparent arithmetic over
what the customer actually told us — the rule is on the badge and in
the lead drawer, not a black box."

**Step 14 — The lead drawer and operator-approved stages.**
Press "Open lead details" (right panel). Show the timeline, the score
reasons, the missing information, the notes. Change the stage via the
dropdown + "Approve stage" and say: "the system can SUGGEST a stage —
only the operator moves a lead, and the history records who moved it
and when."

**Step 15 — The follow-up queue and the AI follow-up draft.**
Click "Follow-ups" in the sidebar. Show the queue sections and open an
"AI-drafted follow-up": safe, non-committal wording, the reason, the
evidence, and "Human approval required — nothing was sent." Press
Approve and show it says "recorded". Say: "the draft can't promise a
price, availability or a plot — those rules are enforced in code, and
the desk has no sending capability at all."

---

## Pilot-feedback extension (added 2026-10-24, later the same day)

**Step 16 — Sources and operator feedback.**
In the lead drawer: set the lead source (e.g. WEBSITE) — the timeline
records it. Fill the Pilot feedback selectors (response quality,
inventory grounding, time saved, would-send, main issue), add a note,
press "Save feedback" — the history appears immediately. Say: "after
every real conversation the operator records ten seconds of
structured feedback; that is what feeds the weekly report."

**Step 17 — The weekly owner report.**
Click "Reports" in the sidebar. Show the KPI row (leads, AI drafts,
approval/edit rates, overdue follow-ups, zero leaks), the lead
overview by source, AI performance, response quality with the honest
time metric, inventory intelligence (unmet shapes, thin cells), and
the safety section. Press "Export Markdown" — a file downloads,
generated locally. Say: "every number here is a count of something
that actually happened; the recommendations are sorted records, not
AI opinions."
