import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

c = sqlite3.connect(str(ROOT / "faisal_hills.db"))
print("root DB residue rows: leads=%d messages=%d audit_log=%d market_listings=%d" % (
    c.execute("SELECT COUNT(*) FROM leads").fetchone()[0],
    c.execute("SELECT COUNT(*) FROM messages").fetchone()[0],
    c.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0],
    c.execute("SELECT COUNT(*) FROM market_listings").fetchone()[0],
))
c.close()

print()
print("=== D-02: the adapter still bypasses scope ===")
from app.market_adapter import get_verified_market_facts as g  # noqa: E402

for b in ("E", "D", "C"):
    r = g(block=b, size_marla=5)
    f = r["facts"]
    print("  adapter block %-2s -> matched=%-3d median=%-12s answerable=%s"
          % (b, f["matched_plots"], f["price_median_pkr"], f["answerable_for_demo"]))
