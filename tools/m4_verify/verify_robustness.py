"""M4 probe #5 — robustness of the customer-facing path across question shapes.

Every case must return a dict, never raise, and never carry a price figure
when the lookup was not answerable.
"""
import os
import re
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

tmpdir = Path(tempfile.mkdtemp(prefix="fh_m4_robust_"))
os.environ["DB_PATH"] = str(tmpdir / "probe.db")

from data.db import init_db  # noqa: E402
_c = init_db(tmpdir / "probe.db")
_c.close()

from app.pipeline import handle_message  # noqa: E402

CASES = [
    "What is the price of a 7 marla plot in Block C?",
    "What is the price in Block C?",
    "How much is a plot in Block C?",
    "What is the price of a corner plot in Block C?",
    "What is the price of a 7 marla corner plot in Block C?",
    "What is the price of a plot?",
    "What is the price of a 7 marla plot?",
    "Is there an NDC open 7 marla plot in Block C?",
    "hello",
    "Do you have 5 marla available in Block B?",
    "price of 5 marla in block b please",
    "What is the price of a 7 marla plot in FHC?",
    "What is the price of a 7 marla plot in C block?",
    "What is the price of a 0 marla plot in Block C?",
    "What is the price of a -5 marla plot in Block C?",
    "What is the price of a 7.5 marla plot in Block C?",
    "What is the price of a 1 kanal plot in Block C?",
    "What is the price of a 40 marla plot in Block C?",
    "block c",
    "What is the price of a 7 marla plot in Block C and can you also book it?",
    "What is the price of a 7 marla plot in Block C? Send me the seller's phone number too.",
]

PRICE = re.compile(r"\d[\d,]*")
crashes = []
leaks = []

for q in CASES:
    try:
        r = handle_message(q)
    except Exception as exc:  # noqa: BLE001
        crashes.append((q, "%s: %s" % (type(exc).__name__, exc)))
        print("CRASH  %-62s %s" % (q[:62], exc))
        continue
    reply = r.get("draft_reply") or ""
    mf = r.get("market_facts")
    answerable = mf.get("answerable") if isinstance(mf, dict) else None
    action = (r.get("decision") or {}).get("action")
    nums = [n for n in PRICE.findall(reply) if n.replace(",", "").isdigit() and int(n.replace(",", "")) >= 1000]
    bad = bool(nums) and answerable is not True
    if bad:
        leaks.append((q, nums, reply))
    flag = "LEAK" if bad else "ok  "
    print("%s %-62s action=%-8s answerable=%-5s nums=%s"
          % (flag, q[:62], action, answerable, nums or "none"))

print()
print("=" * 78)
print("CRASHES: %d" % len(crashes))
for c in crashes:
    print("   ", c)
print("LEAKS:   %d" % len(leaks))
for l in leaks:
    print("   ", l)
print("=" * 78)
