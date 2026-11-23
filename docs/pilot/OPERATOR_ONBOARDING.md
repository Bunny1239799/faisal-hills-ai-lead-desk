# Operator onboarding — your first hour on the Lead Desk

Welcome. This page explains everything you need to work the desk
safely. It is written in plain language on purpose.

## What the Operator Desk is

A workspace where the application drafts answers to dealer inquiries
and **you** decide what happens to them. The application checks the
approved inventory, follows the business rules, and writes a draft
reply. It never sends anything. You read, improve, approve or reject —
and you can take the conversation over completely at any time.

Three areas on screen: **Leads** (left, your conversations), the
**conversation** (middle, what the dealer said and what was drafted),
and the **context panel** (right: requirements, recommendation,
options, activity).

## What you should do

1. Read what the dealer said (typed into the composer, exactly as they
   said it).
2. Read the **AI draft** on the right side of the thread. If it shows
   "Checked: numbers, claims", both automatic safety gates passed.
3. Check the **Requirements** table (size, block, budget, purpose,
   timeline) and the **Recommendation** — including *why* this route.
4. Choose an action:
   * **Send as is** — the draft is good.
   * **Save edit** — type your improved wording in the composer first,
     then press it.
   * **Reject draft** — the draft is wrong or unnecessary.
   * **Take over** — you will answer personally from here on; the
     application stops drafting this conversation.
5. Send the approved text to the dealer yourself, the way you always
   do (for now, manually — the desk cannot send anything).

## What you must NEVER do

* Never invent a price, a plot, an availability claim or a statistic
  that the draft does not contain. If the draft says "not enough
  data", that is the honest answer — do not fill the gap from memory.
* Never bypass an escalation. If the panel says **Human review
  required** (amber) or **Refused by policy** (red), the conversation
  is for a person — you or your manager — not for an automated answer.
* Never share dealer names, phone numbers, notes or any private
  information you know from outside the system.
* Never tell a dealer the system is "automatic" or "AI decides". The
  truth is better: *the system checks approved data, a human decides.*

## How to start the desk

Double-click **`start_operator_desk.bat`** in the project folder. Your
browser opens at the desk. If it says the application is unreachable,
wait a few seconds and reload. To stop: close the server window.

## Entering a real dealer inquiry

Type (or paste) **exactly what the dealer said** into the "Dealer's
message" box — Roman Urdu or English, numbers like "80 lakh" or "1
crore" are understood. Press **Send message** (or Enter). The
requirements update on the right; corrections the dealer makes later
("actually my budget is 1.2 crore") are recorded and marked
**Corrected**.

## When to escalate

The desk escalates on its own for: discounts/negotiation, booking or
payment steps, legal/NOC/title questions, refunds or complaints,
investment-return promises, anything about **other customers' data or
dealer contact details**, requests to invent information, and anything
outside the approved blocks. When you see the banner, handle it
personally and reply as a human. If you are unsure — escalate. Nobody
is ever blamed for escalating; the system is designed to prefer asking
over guessing.

## If something looks wrong

* A number looks incorrect, a reply looks off, or the page shows an
  error: press **Retry** if offered; if it persists, stop using that
  conversation, leave it open, and note it (below).
* Never "test" suspicious input on a real dealer conversation.
* If you ever see private information (a name, a phone number) in a
  draft — stop using the desk and report it immediately. That should
  be impossible; we treat it as serious.

## Recording feedback

At the end of your shift, fill in `OPERATOR_DAILY_LOG_TEMPLATE.md`
(one copy per day): counts of what you did, the best and worst
replies, inventory gaps, questions the system could not answer, and
any safety concern. It takes five minutes and it is the single most
valuable input the founder receives.

## The metrics that matter

Visible in the panel: conversations, AI drafts, escalations, unmet
demand, and your actions (sent as is / edited / rejected / taken
over). These show whether the drafts are actually useful. Nobody is
measuring your typing speed.

## Stopping the pilot safely

Close the server window. Nothing is sent by the system at any point,
so stopping has no external effect. All conversations and actions are
saved and survive a restart.
