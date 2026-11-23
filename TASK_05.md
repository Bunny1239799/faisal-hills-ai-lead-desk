# TASK 05: Diagnose Laya and build a held-out test set

Follow PROJECT_STATE.md HARD RULES and read PROGRESS.md. Standard library plus pytest only. UTF-8 without BOM. ASCII-safe console output.

PART A - Laya diagnosis (Laya server must be running on 127.0.0.1:8000)
1. Add a --debug flag to evaluation/run_eval.py that, for method laya, prints the raw request and raw response for the first 10 messages.
2. Report the distribution of Laya's needs_human and high_intent probabilities, separately for rows where the true label is true versus false.
3. Add a threshold sweep (0.05 to 0.95 step 0.05) for needs_human and high_intent that prints recall and precision at each threshold.
4. Check whether lead_type ever returns anything other than "buyer". Show the label probabilities.
5. Rewrite Laya's questions per the Laya guide: meaningful option labels (not true/false), clear criteria in each noul question, and fewer choices (split lead_type into two questions if needed). Rerun and report whether Laya ever beats rules or llm on any question.
6. Write findings to evaluation/reports/laya_diagnosis.md.

PART B - held-out set
1. Add a --dataset argument to run_eval.py (default golden_v1.jsonl).
2. Create tools/validate_dataset.py compatibility for evaluation/datasets/production/holdout_v1.jsonl (100 new rows, ids h001 to h100, same format as golden_v1, source "synthetic_holdout"). IMPORTANT: this file must be written WITHOUT reading rules.py or policy.py, ideally by a different model, then reviewed by the human.
3. Run rules, laya and llm on holdout_v1 and report the drop compared with golden_v1.

Finish by listing the exact commands to run everything.