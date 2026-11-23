"""M12.3 - run the inventory ingest gate from the command line.

Usage (project venv):

    .venv\\Scripts\\python.exe tools\\ingest_gate.py <candidate.jsonl>

Exit code 0 when the candidate was accepted (no rejected rows), 1 when
rows were rejected, 2 on a usage error. The gate writes its reports
under data\\ingest_staging\\<timestamp>\\ and NEVER touches the approved
master - promotion is a founder-only manual step documented in the
generated report.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from market.ingest_gate import run_gate  # noqa: E402


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) < 1 or len(argv) > 2:
        print(__doc__)
        return 2

    candidate = Path(argv[0])
    if not candidate.exists():
        print("candidate file not found: %s" % candidate)
        return 2

    try:
        report = run_gate(candidate)
    except ValueError as exc:
        print("REFUSED: %s" % exc)
        return 2

    print("verdict            : %s" % report.verdict)
    print("rows read          : %d" % report.rows)
    print("accepted           : %d" % report.accepted)
    print("flagged (kept)     : %d" % report.flagged)
    print("rejected           : %d" % report.rejected)
    print("approved master    : %d records, sha256 %s... (unchanged)"
          % (report.approved_records, report.approved_sha256[:12]))
    print("staging folder     : %s" % report.out_dir)
    print("reports            : report.md, report.json, candidate_clean.jsonl")

    for item in report.rejects[:20]:
        print("  REJECT line %-4d %-14s %s"
              % (item["line"], item["identity"],
                 "; ".join(item["reasons"])))
    if len(report.rejects) > 20:
        print("  ... and %d more (see report.md)" % (len(report.rejects) - 20))

    print("promotion is a founder-only manual step - see report.md")
    return 0 if report.verdict == "ACCEPTED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
