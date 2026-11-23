"""M4 probe #4 — CI portability: does the suite pass with FH_MASTER_PATH set?

This reproduces what GitHub Actions does: derive a JSONL master from the
in-repo CSV and point FH_MASTER_PATH at it, then run the suite.
"""
import csv
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
csv_path = ROOT / "market" / "master_inventory.csv"
out_path = Path(tempfile.mkdtemp(prefix="fh_m4_ci_")) / "master_inventory.jsonl"

rows = list(csv.DictReader(csv_path.open(encoding="utf-8-sig")))
with out_path.open("w", encoding="utf-8", newline="\n") as fh:
    for row in rows:
        record = {k: ("" if v is None else v) for k, v in row.items() if k}
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")
print("derived master rows:", len(rows))

env = dict(os.environ)
env["FH_MASTER_PATH"] = str(out_path)
proc = subprocess.run(
    [str(ROOT / ".venv" / "Scripts" / "python.exe"), "-m", "pytest", "-q", "--tb=line", "-p", "no:cacheprovider"],
    cwd=str(ROOT), env=env, capture_output=True, text=True,
)
print("EXIT:", proc.returncode)
print("---- stdout tail ----")
print("\n".join(proc.stdout.splitlines()[-40:]))
print("---- stderr tail ----")
print("\n".join(proc.stderr.splitlines()[-20:]))
