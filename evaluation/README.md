# Evaluation Dataset Documentation & Taxonomy

This document describes the schema, label categories, and validation rules for the Faisal Hills AI Lead Desk evaluation sets (`golden_v1.jsonl`, `redteam_v1.jsonl`, etc.).

## Dataset Schema

Each row in the JSONL dataset must be a valid UTF-8 encoded JSON object (without BOM) containing the following fields:

| Field | Type | Description |
|---|---|---|
| `id` | `string` | Unique identifier (e.g. `g001`, `r001`). |
| `message` | `string` | Customer query/message text. |
| `language` | `string` | Language code: `en`, `ur`, `roman_ur`, `mixed`. |
| `lead_type` | `string` | Category of the lead: `buyer`, `investor`, `renter`, `broker`, `existing_customer`, `other`. |
| `high_intent` | `boolean` | `true` if concrete buying signals are present (visit, book/pay, budget + timeline, next steps); else `false`. |
| `needs_human` | `boolean` | `true` if query involves legal/approval/NOC/title, discount/negotiation, booking/payment commitment, refunds, investment returns, complaints, abusive language, or prompt injections; else `false`. |
| `intent` | `string` | Primary intent: `price_inquiry`, `availability`, `payment_plan`, `location`, `site_visit`, `legal_approval`, `discount`, `booking`, `returns`, `complaint`, `smalltalk`, `other`, `prompt_injection`. |
| `facts_needed` | `list[string]` | Facts required from DB: `pricing`, `inventory`, `payment_plans`, `blocks`, `legal_facts`, `society_master`, `faqs`, `none`. |
| `expected_action`| `string` | Action policy: `answer_with_facts`, `ask_clarifying`, `escalate_human`, `refuse`, `smalltalk`. |
| `risk_tags` | `list[string]` | Risk markers: `negation`, `short`, `typo`, `mixed_intent`, `injection`, `legal`, `discount`, `abusive`, `ambiguous`, `long`. |
| `source` | `string` | Origin of row (e.g. `synthetic`, `human`, `dealer`). |

## Validation & Rules

All dataset files must pass the validation checks in `tools/validate_dataset.py`:
- Valid UTF-8 without BOM.
- Unique non-empty IDs.
- All required fields present with correct data types.
- Values strictly adhering to the defined enum constants in `evaluation/labels.py`.
