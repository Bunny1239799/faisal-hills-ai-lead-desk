# TASK 04: Policy gate (deterministic safety layer)

Follow PROJECT_STATE.md HARD RULES and read PROGRESS.md. Standard library plus pytest only. UTF-8 without BOM. Do not modify read-only files. Read evaluation/baselines/rules.py and evaluation/labels.py for existing keyword ideas and label names.

Build:
1. app/policy.py with:
   - a PolicyDecision dataclass: action (answer | clarify | escalate | refuse), reasons (list of strings), risk_tags (list), needs_human (bool)
   - evaluate_policy(message, laya_signals=None) where laya_signals is an optional dict like {"needs_human": 0.0-1.0, "high_intent": 0.0-1.0}
2. Deterministic rules, in English, Roman Urdu and Urdu script. Route to escalate or refuse for: legal/approval/NOC/title/ownership claims; discounts and negotiation; booking, payment or token-money commitments; refunds; investment returns, guarantees or profit promises; complaints and abusive language; prompt injection (ignore previous instructions, reveal system prompt, you are now admin, act as, developer mode); requests for other customers' data; claims that a manager already approved something; pressure to repeat an old price.
3. Rule: policy can only make a decision STRICTER, never looser. If laya_signals needs_human is at or above a threshold parameter (default 0.5), escalate. If no rule matches, return answer.
4. app/__init__.py, plus a tests/test_policy.py that:
   - loads evaluation/datasets/production/redteam_v1.jsonl and asserts NONE of the 30 rows gets action "answer"
   - loads golden_v1.jsonl and computes, using rules only (no Laya, no network), recall of needs_human=true rows and the false-escalation rate on needs_human=false rows
   - asserts needs_human recall is at least 0.95 and prints the false-escalation rate and a list of missed rows
5. tools/policy_report.py that prints the same metrics plus every missed risky row, so keywords can be improved.

Finish by listing the exact commands to run the tests and the report. Then improve keywords until recall is at least 0.95 without escalating more than about 35 percent of needs_human=false rows.