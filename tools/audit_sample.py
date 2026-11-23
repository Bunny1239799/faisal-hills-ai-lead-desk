"""tools/audit_sample.py
Generate a random sample of real listings for human audit.
Output: data/audit_sheet.csv with columns ready for scoring.
Usage: python -m tools.audit_sample [--seed N] [--n 40]
"""
from __future__ import annotations
import argparse, csv, random, sqlite3, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "market.db"
OUT = ROOT / "data" / "audit_sheet.csv"

def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--n", type=int, default=40)
    args = p.parse_args()
    random.seed(args.seed)

    if not DB.exists():
        print(f"ERROR: {DB} not found. Run ingest first.", file=sys.stderr)
        return 1

    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        """
        SELECT id, block, plot_no, size_label, price_pkr, ndc_status,
               features, raw_snippet, source_file, extracted_at
        FROM listings
        WHERE intent = 'sell' AND property_type = 'plot'
          AND block IN ('A','B','C')
          AND price_pkr IS NOT NULL
        ORDER BY id
        """
    ).fetchall()
    con.close()

    if len(rows) < 10:
        print(f"ERROR: only {len(rows)} candidate rows. Ingest more data.", file=sys.stderr)
        return 1

    sample = random.sample(list(rows), min(args.n, len(rows)))
    OUT.parent.mkdir(parents=True, exist_ok=True)

    with OUT.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow([
            "id", "block", "plot_no", "size_label", "price_pkr",
            "ndc_status", "features", "raw_snippet", "source_file",
            "block_ok", "plot_ok", "size_ok", "price_ok", "notes"
        ])
        for r in sample:
            w.writerow([
                r["id"], r["block"], r["plot_no"], r["size_label"], r["price_pkr"],
                r["ndc_status"], r["features"], (r["raw_snippet"] or "")[:120],
                r["source_file"], "", "", "", "", ""
            ])

    print(f"Wrote {len(sample)} rows to {OUT}")
    print("Open the CSV in Excel, fill block_ok/plot_ok/size_ok/price_ok with 1 or 0, save, then run:")
    print("  python -m tools.audit_score")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())