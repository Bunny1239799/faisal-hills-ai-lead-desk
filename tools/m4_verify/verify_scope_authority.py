"""M4 probe #3 — is config/policies.json the single authority for scope?

Uses the 'Executive' block, which has 9 rows in the approved master, so
the result is decisive. The repository's own config/policies.json is never
modified: a copy in a temp dir is used and the lookup is pointed at it.
"""
import json
import os
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

tmpdir = Path(tempfile.mkdtemp(prefix="fh_m4_scope_"))
os.environ["DB_PATH"] = str(tmpdir / "probe.db")

from data.db import init_db  # noqa: E402
_c = init_db(tmpdir / "probe.db")
_c.close()

shutil.copytree(ROOT / "config", tmpdir / "config")
pol_path = tmpdir / "config" / "policies.json"
pol = json.loads(pol_path.read_text(encoding="utf-8"))

from market import price_lookup  # noqa: E402

price_lookup.POLICIES_PATH = pol_path
price_lookup.QUESTIONS_PATH = tmpdir / "config" / "questions.json"

# Owner widens the scope to include Executive.
pol["active_blocks"] = ["A", "B", "C", "EXECUTIVE"]
pol_path.write_text(json.dumps(pol, indent=2), encoding="utf-8")

from app.pipeline import handle_message  # noqa: E402

print("=" * 78)
print("SINGLE-AUTHORITY SCOPE PROBE  (policies.json active_blocks = A,B,C,EXECUTIVE)")
print("=" * 78)

direct = price_lookup.lookup_price(block="Executive", size_marla=5)
print("lookup_price(block='Executive', size=5)")
print("   answerable = %s   reason = %r" % (direct["answerable"], direct.get("reason", "")[:70]))
print("   summary    = %s" % json.dumps(direct["summary"]))
print()

r = handle_message("What is the price of a 5 marla plot in the Executive Block?")
action = (r.get("decision") or {}).get("action")
print("handle_message('...Executive Block?')")
print("   policy action   = %s" % action)
print("   market_facts    = %r" % (r.get("market_facts"),))
print("   draft_reply     = %s" % (r.get("draft_reply") or "")[:120])
print()

follows = direct["answerable"] and action == "answer"
print("RESULT: the customer-facing path %s config/policies.json"
      % ("FOLLOWS" if follows else "does NOT follow"))
print("=" * 78)
