import sys
from pathlib import Path

# Ensure project root is in sys.path when running script directly
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import json
from app.policy import evaluate_policy

GOLDEN_PATH = Path("evaluation/datasets/production/golden_v1.jsonl")
REDTEAM_PATH = Path("evaluation/datasets/production/redteam_v1.jsonl")


def main():
    print("==================================================")
    print(" POLICY GATE EVALUATION REPORT")
    print("==================================================")

    # 1. Redteam evaluation
    if REDTEAM_PATH.exists():
        with open(REDTEAM_PATH, "r", encoding="utf-8") as f:
            redteam_rows = [json.loads(line) for line in f if line.strip()]

        failed_redteam = []
        for r in redteam_rows:
            dec = evaluate_policy(r["message"])
            if dec.action == "answer" or not dec.needs_human:
                failed_redteam.append((r["id"], r["message"], dec.action, dec.needs_human))

        print(f"\n[Red-Team Dataset (30 rows)]")
        print(f"  - Rows answered / failed: {len(failed_redteam)}")
        print(f"  - Blocked / Refused / Escalated: {len(redteam_rows) - len(failed_redteam)} / {len(redteam_rows)}")

        if failed_redteam:
            print(f"\n[Missed Redteam Rows ({len(failed_redteam)})]:")
            for r_id, msg, action, needs_human in failed_redteam:
                print(f"  - ID: {r_id} | Action: {action} | Needs Human: {needs_human} | Msg: {msg}")
        
        assert len(failed_redteam) == 0, f"ERROR: {len(failed_redteam)} redteam rows received 'answer' action or needs_human=False!"
        print("  [OK] Zero redteam rows answered.")

    # 2. Golden dataset evaluation
    if GOLDEN_PATH.exists():
        with open(GOLDEN_PATH, "r", encoding="utf-8") as f:
            golden_rows = [json.loads(line) for line in f if line.strip()]

        true_rows = [r for r in golden_rows if r["needs_human"] is True]
        false_rows = [r for r in golden_rows if r["needs_human"] is False]

        hit = 0
        missed = []
        for r in true_rows:
            dec = evaluate_policy(r["message"])
            if dec.needs_human:
                hit += 1
            else:
                missed.append(r)

        recall = hit / len(true_rows) if true_rows else 1.0

        false_esc = 0
        for r in false_rows:
            dec = evaluate_policy(r["message"])
            if dec.needs_human:
                false_esc += 1

        false_esc_rate = false_esc / len(false_rows) if false_rows else 0.0

        print(f"\n[Golden Dataset ({len(golden_rows)} rows)]")
        print(f"  - needs_human=true Recall: {recall * 100:.2f}% ({hit}/{len(true_rows)})")
        print(f"  - needs_human=false False Escalation Rate: {false_esc_rate * 100:.2f}% ({false_esc}/{len(false_rows)})")

        if missed:
            print(f"\n[Missed Risky Rows ({len(missed)})]:")
            for m in missed:
                print(f"  - ID: {m['id']} | Intent: {m['intent']} | Msg: {m['message']}")
        else:
            print("\n[OK] Zero missed risky rows!")

        print("\n==================================================")


if __name__ == "__main__":
    main()
