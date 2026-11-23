import csv
from pathlib import Path
from collections import Counter
from typing import Optional, Dict, Any

def score_audit_sheet(csv_path: Optional[Path] = None) -> Dict[str, Any]:
    if csv_path is None:
        csv_path = Path("data/audit_sheet.csv")

    if not csv_path.exists():
        raise FileNotFoundError(f"Audit sheet not found at {csv_path}")

    fields = ['block_ok', 'plot_ok', 'size_ok', 'price_ok']
    field_totals = {f: 0 for f in fields}
    field_passes = {f: 0 for f in fields}
    reason_codes = Counter()
    total_rows = 0

    with open(csv_path, mode='r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            total_rows += 1
            for f_name in fields:
                val = row.get(f_name, '').strip()
                if val != '':
                    field_totals[f_name] += 1
                    if val == '1':
                        field_passes[f_name] += 1
            
            rc = row.get('reason_code', '').strip()
            if rc:
                reason_codes[rc] += 1

    accuracies = {}
    for f_name in fields:
        total = field_totals[f_name]
        if total > 0:
            accuracies[f_name] = field_passes[f_name] / total
        else:
            accuracies[f_name] = 0.0

    # Pass condition: price accuracy >= 95% and block accuracy >= 95%
    price_acc = accuracies.get('price_ok', 0.0)
    block_acc = accuracies.get('block_ok', 0.0)
    passed = price_acc >= 0.95 and block_acc >= 0.95

    print("--- Audit Score Report ---")
    for f_name in fields:
        print(f"{f_name} accuracy: {accuracies[f_name] * 100:.2f}% ({field_passes[f_name]}/{field_totals[f_name]})")
    
    print(f"Overall Status: {'PASS' if passed else 'FAIL'}")
    print("Most common error types / reason codes:")
    for rc, count in reason_codes.most_common(5):
        print(f"  {rc}: {count}")

    return {
        "accuracies": accuracies,
        "passed": passed,
        "reason_codes": reason_codes
    }

if __name__ == '__main__':
    score_audit_sheet()
