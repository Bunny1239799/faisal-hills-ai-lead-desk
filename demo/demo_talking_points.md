# Demo talking points — what to say (and what never to say)

## The one-sentence pitch

"Your inventory becomes the source of truth; the AI turns inquiries
into qualified, trustworthy, operator-controlled conversations."

## The five things to emphasize

1. **It checks before it answers.** Every number in a reply comes
   from the approved inventory through two mandatory gates (numeric
   traceability + claim shape). If the data is not there, it says so.
2. **It cannot leak what it does not have.** Dealer identities,
   notes, phone numbers and raw sources are not on any serving path —
   the operator surface is a whitelist, not a filter.
3. **The human is the sender.** The system drafts; the operator
   reviews, edits, rejects or takes over. There is no sending
   integration at all.
4. **It escalates honestly.** Discounts, booking, legal, out-of-scope
   blocks and private-data requests all land on a person — visibly.
5. **It learns what the market wants.** Unmet demand is recorded as
   anonymous shapes (size, block, budget band) — never message text.

## Honest answers to likely questions

* "Is this the live market?" — No. This demo runs on clearly labeled
  SYNTHETIC_DEMO_DATA. The production system runs on your approved
  inventory through the same pipeline you are watching.
* "Can it send WhatsApp messages?" — No. Drafts are copied and sent by
  your operator, on purpose. Automation is a later, separate decision.
* "What if the AI makes up a price?" — It can't reach the customer: an
  invented number fails the traceability gate and the reply is held
  for a human. This is enforced in code, not in instructions.
* "What does it cost / can I have it?" — The next step after this demo
  is a controlled pilot with your real inventory, then we talk
  commercial setup. (Do not invent pricing on the spot.)

## Never say

* Anything that presents the demo numbers as real market prices.
* "It's fully automated" / "the AI replaces an operator".
* User counts, revenue claims, or "other agencies are using it".
* Anything about real dealer data being "inside" the system.

(Calibrated to the presentation constraints in the project handoff:
controlled AI workspace, human in control, honest alternatives.)
