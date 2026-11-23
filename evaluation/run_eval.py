import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict, Any, Tuple

from evaluation.baselines.rules import classify_rules
from evaluation.baselines.laya_client import classify_laya
from evaluation.baselines.llm import classify_batch_llm

DATASET_PATH = Path("evaluation/datasets/production/golden_v1.jsonl")
REPORTS_DIR = Path("evaluation/reports")

LEAD_TYPE_CLASSES = ["buyer", "investor", "renter", "broker", "existing_customer", "other"]


def load_dataset(file_path: Path, limit: int = 0) -> List[Dict[str, Any]]:
    if not file_path.exists():
        raise FileNotFoundError(f"Dataset file not found: {file_path}")

    records = []
    with open(file_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            records.append(json.loads(line))
            if limit > 0 and len(records) >= limit:
                break
    return records


def compute_binary_metrics(actuals: List[bool], preds: List[bool]) -> Dict[str, float]:
    tp = sum(1 for a, p in zip(actuals, preds) if a is True and p is True)
    fp = sum(1 for a, p in zip(actuals, preds) if a is False and p is True)
    fn = sum(1 for a, p in zip(actuals, preds) if a is True and p is False)
    tn = sum(1 for a, p in zip(actuals, preds) if a is False and p is False)

    total = len(actuals)
    accuracy = (tp + tn) / total if total > 0 else 0.0
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = (2 * precision * recall) / (precision + recall) if (precision + recall) > 0 else 0.0

    return {
        "accuracy": accuracy,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
    }


def compute_multiclass_metrics(actuals: List[str], preds: List[str], classes: List[str]) -> Tuple[float, Dict[str, Dict[str, int]]]:
    total = len(actuals)
    correct = sum(1 for a, p in zip(actuals, preds) if a == p)
    accuracy = correct / total if total > 0 else 0.0

    matrix = {c: {p: 0 for p in classes} for c in classes}
    for a, p in zip(actuals, preds):
        act_key = a if a in matrix else "other"
        pred_key = p if p in matrix[act_key] else "other"
        matrix[act_key][pred_key] += 1

    return accuracy, matrix


def evaluate_method(
    method_name: str,
    records: List[Dict[str, Any]],
    predictions: List[Dict[str, Any]],
) -> Dict[str, Any]:
    languages = sorted(list({r.get("language", "en") for r in records}))

    # Lead type metrics
    actual_lead_type = [r["lead_type"] for r in records]
    pred_lead_type = [p["lead_type"] for p in predictions]
    acc_lead_type, conf_matrix = compute_multiclass_metrics(actual_lead_type, pred_lead_type, LEAD_TYPE_CLASSES)

    # High intent metrics
    actual_high_intent = [bool(r["high_intent"]) for r in records]
    pred_high_intent = [bool(p["high_intent"]) for p in predictions]
    metrics_high_intent = compute_binary_metrics(actual_high_intent, pred_high_intent)

    # Needs human metrics
    actual_needs_human = [bool(r["needs_human"]) for r in records]
    pred_needs_human = [bool(p["needs_human"]) for p in predictions]
    metrics_needs_human = compute_binary_metrics(actual_needs_human, pred_needs_human)

    # Language breakdown (Overall accuracy across all 3 questions matching)
    lang_stats: Dict[str, Dict[str, Any]] = {}
    for lang in languages:
        lang_indices = [i for i, r in enumerate(records) if r.get("language") == lang]
        if not lang_indices:
            continue
        sub_records = [records[i] for i in lang_indices]
        sub_preds = [predictions[i] for i in lang_indices]

        lt_corr = sum(1 for r, p in zip(sub_records, sub_preds) if r["lead_type"] == p["lead_type"])
        hi_corr = sum(1 for r, p in zip(sub_records, sub_preds) if bool(r["high_intent"]) == bool(p["high_intent"]))
        nh_corr = sum(1 for r, p in zip(sub_records, sub_preds) if bool(r["needs_human"]) == bool(p["needs_human"]))
        all_3_corr = sum(
            1 for r, p in zip(sub_records, sub_preds)
            if r["lead_type"] == p["lead_type"] and bool(r["high_intent"]) == bool(p["high_intent"]) and bool(r["needs_human"]) == bool(p["needs_human"])
        )

        n = len(lang_indices)
        lang_stats[lang] = {
            "count": n,
            "lead_type_acc": lt_corr / n,
            "high_intent_acc": hi_corr / n,
            "needs_human_acc": nh_corr / n,
            "all_three_acc": all_3_corr / n,
        }

    # Failures analysis: count number of wrong questions per example
    failures = []
    for idx, (rec, pred) in enumerate(zip(records, predictions)):
        errors = []
        if rec["lead_type"] != pred["lead_type"]:
            errors.append(f"lead_type (exp: {rec['lead_type']}, got: {pred['lead_type']})")
        if bool(rec["high_intent"]) != bool(pred["high_intent"]):
            errors.append(f"high_intent (exp: {rec['high_intent']}, got: {pred['high_intent']})")
        if bool(rec["needs_human"]) != bool(pred["needs_human"]):
            # Emphasize risky false negatives where human judgment was needed
            is_critical = rec["needs_human"] and not pred["needs_human"]
            tag = "CRITICAL_MISS: " if is_critical else ""
            errors.append(f"{tag}needs_human (exp: {rec['needs_human']}, got: {pred['needs_human']})")

        if errors:
            severity = len(errors)
            if any("CRITICAL_MISS" in e for e in errors):
                severity += 2  # Prioritize missed risky cases in failure list
            failures.append({
                "id": rec["id"],
                "message": rec["message"],
                "language": rec.get("language", "unknown"),
                "expected": {
                    "lead_type": rec["lead_type"],
                    "high_intent": rec["high_intent"],
                    "needs_human": rec["needs_human"],
                },
                "predicted": {
                    "lead_type": pred["lead_type"],
                    "high_intent": pred["high_intent"],
                    "needs_human": pred["needs_human"],
                },
                "errors": errors,
                "severity": severity,
            })

    # Sort failures by severity descending
    failures.sort(key=lambda x: x["severity"], reverse=True)

    return {
        "method": method_name,
        "sample_count": len(records),
        "lead_type": {
            "accuracy": acc_lead_type,
            "confusion_matrix": conf_matrix,
        },
        "high_intent": metrics_high_intent,
        "needs_human": metrics_needs_human,
        "languages": lang_stats,
        "failures": failures[:20],
    }


def format_markdown_report(results: Dict[str, Dict[str, Any]], dataset_size: int) -> str:
    timestamp_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    lines = [
        f"# Model & Baseline Evaluation Report",
        f"",
        f"- **Generated At:** {timestamp_str}",
        f"- **Total Dataset Samples:** {dataset_size}",
        f"- **Evaluated Methods:** {', '.join(results.keys())}",
        f"",
        f"---",
        f"",
        f"## 1. Summary of Question Accuracies per Method",
        f"",
        f"| Method | `lead_type` Accuracy | `high_intent` Accuracy | `needs_human` Accuracy | `needs_human` Recall | `needs_human` Precision |",
        f"| :--- | :--- | :--- | :--- | :--- | :--- |",
    ]

    for method, res in results.items():
        lt_acc = f"{res['lead_type']['accuracy'] * 100:.1f}%"
        hi_acc = f"{res['high_intent']['accuracy'] * 100:.1f}%"
        nh_acc = f"{res['needs_human']['accuracy'] * 100:.1f}%"
        nh_rec = f"{res['needs_human']['recall'] * 100:.1f}%"
        nh_prec = f"{res['needs_human']['precision'] * 100:.1f}%"
        lines.append(f"| **{method}** | {lt_acc} | {hi_acc} | {nh_acc} | {nh_rec} | {nh_prec} |")

    lines.extend([
        f"",
        f"---",
        f"",
        f"## 2. Accuracy Breakdown by Language",
        f"",
    ])

    for method, res in results.items():
        lines.extend([
            f"### Method: `{method}`",
            f"",
            f"| Language | Samples | `lead_type` Acc | `high_intent` Acc | `needs_human` Acc | All 3 Correct |",
            f"| :--- | :--- | :--- | :--- | :--- | :--- |",
        ])
        for lang, s in res["languages"].items():
            lines.append(
                f"| `{lang}` | {s['count']} | {s['lead_type_acc']*100:.1f}% | {s['high_intent_acc']*100:.1f}% | {s['needs_human_acc']*100:.1f}% | {s['all_three_acc']*100:.1f}% |"
            )
        lines.append("")

    lines.extend([
        f"---",
        f"",
        f"## 3. Confusion Matrix for `lead_type`",
        f"",
    ])

    for method, res in results.items():
        lines.extend([
            f"### Method: `{method}`",
            f"",
            f"| Actual \\ Predicted | " + " | ".join(LEAD_TYPE_CLASSES) + " |",
            f"| :--- | " + " | ".join([":---"] * len(LEAD_TYPE_CLASSES)) + " |",
        ])
        matrix = res["lead_type"]["confusion_matrix"]
        for act in LEAD_TYPE_CLASSES:
            row_vals = [str(matrix.get(act, {}).get(p, 0)) for p in LEAD_TYPE_CLASSES]
            lines.append(f"| **{act}** | " + " | ".join(row_vals) + " |")
        lines.append("")

    lines.extend([
        f"---",
        f"",
        f"## 4. Top Failures per Method (Up to 20)",
        f"",
    ])

    for method, res in results.items():
        lines.extend([
            f"### Method: `{method}` (Failures: {len(res['failures'])})",
            f"",
        ])
        if not res["failures"]:
            lines.append("No failures found for this method.\n")
            continue

        for i, f in enumerate(res["failures"], 1):
            lines.append(f"**{i}. [{f['id']}] ({f['language']})** {f['message']}")
            lines.append(f"- **Expected:** `lead_type={f['expected']['lead_type']}`, `high_intent={f['expected']['high_intent']}`, `needs_human={f['expected']['needs_human']}`")
            lines.append(f"- **Predicted:** `lead_type={f['predicted']['lead_type']}`, `high_intent={f['predicted']['high_intent']}`, `needs_human={f['predicted']['needs_human']}`")
            lines.append(f"- **Issues:** {', '.join(f['errors'])}")
            lines.append("")

    lines.extend([
        f"---",
        f"",
        f"## 5. Method Recommendations",
        f"",
    ])

    # Compute best per question
    best_lead_type = max(results.items(), key=lambda x: x[1]["lead_type"]["accuracy"])[0]
    best_high_intent = max(results.items(), key=lambda x: x[1]["high_intent"]["accuracy"])[0]
    # For needs_human, recall on safety/risky cases is paramount, tie-break on precision
    best_needs_human = max(
        results.items(),
        key=lambda x: (x[1]["needs_human"]["recall"], x[1]["needs_human"]["precision"])
    )[0]

    lines.append(
        f"- **Best `lead_type` Classifier:** `{best_lead_type}` (highest classification accuracy)."
    )
    lines.append(
        f"- **Best `high_intent` Classifier:** `{best_high_intent}` (highest buying signal accuracy)."
    )
    lines.append(
        f"- **Best `needs_human` Classifier:** `{best_needs_human}` (highest recall on risky/escalation inquiries)."
    )
    lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Evaluate Laya vs Rules vs LLM baselines on golden set.")
    parser.add_argument(
        "--methods",
        type=str,
        default="rules",
        help="Comma-separated list of methods to evaluate: laya,rules,llm",
    )
    parser.add_argument(
        "--dataset",
        type=str,
        default=str(DATASET_PATH),
        help="Path to the golden dataset jsonl file",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Limit number of rows to evaluate (0 for full dataset)",
    )
    args = parser.parse_args()

    methods = [m.strip().lower() for m in args.methods.split(",") if m.strip()]
    dataset_file = Path(args.dataset)

    print(f"[EVAL] Loading dataset from {dataset_file} (limit={args.limit})...")
    records = load_dataset(dataset_file, limit=args.limit)
    print(f"[EVAL] Loaded {len(records)} records.")

    eval_results: Dict[str, Dict[str, Any]] = {}

    for method in methods:
        print(f"\n[EVAL] Running method: {method}...")
        preds: List[Dict[str, Any]] = []

        if method == "rules":
            for rec in records:
                pred = classify_rules(rec["message"])
                preds.append(pred)

        elif method == "laya":
            for idx, rec in enumerate(records):
                if (idx + 1) % 10 == 0 or idx == len(records) - 1:
                    print(f"  [Laya] Processed {idx + 1}/{len(records)} messages...")
                try:
                    pred = classify_laya(rec["message"])
                except Exception as e:
                    print(f"  [Laya] Failed on id {rec['id']}: {e}")
                    pred = {"lead_type": "buyer", "high_intent": False, "needs_human": False}
                preds.append(pred)

        elif method == "llm":
            print(f"  [LLM] Classifying {len(records)} messages using Gemini API...")
            llm_results = classify_batch_llm(records)
            preds = llm_results

        else:
            print(f"[WARN] Unknown method: {method}. Skipping.")
            continue

        eval_results[method] = evaluate_method(method, records, preds)

    if not eval_results:
        print("[ERROR] No evaluations were completed.")
        sys.exit(1)

    # Write report
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    report_filename = f"eval_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M')}.md"
    report_path = REPORTS_DIR / report_filename

    md_content = format_markdown_report(eval_results, len(records))
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(md_content)

    print(f"\n[OK] Evaluation report successfully written to: {report_path}")
    print("\n--- Summary Recommendations ---")
    for line in md_content.splitlines():
        if line.startswith("- **Best"):
            print(line)


if __name__ == "__main__":
    main()
