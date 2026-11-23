"""Apply a verified exact-string edit to a file.

Fails loudly if the anchor is not found exactly once, so a stale anchor can
never silently corrupt a file. Reports "ALREADY APPLIED" when the anchor
is gone but the replacement is present.

Used during the M4 closeout to make each edit auditable.
"""
import sys
from pathlib import Path


def apply(path, before, after, expected_count=1):
    p = Path(path)
    src = p.read_text(encoding="utf-8")
    n = src.count(before)

    if n == 0:
        if after and after in src:
            raise SystemExit(
                "ALREADY APPLIED (anchor gone, replacement present) in %s" % path
            )
        raise SystemExit(
            "ANCHOR NOT FOUND in %s\n---\n%r" % (path, before[:200])
        )

    if n != expected_count:
        raise SystemExit(
            "ANCHOR ERROR in %s: found %d occurrences, expected %d\n---\n%r"
            % (path, n, expected_count, before[:200])
        )

    p.write_text(src.replace(before, after), encoding="utf-8", newline="")
    print("OK %s (replaced %d)" % (path, n))
