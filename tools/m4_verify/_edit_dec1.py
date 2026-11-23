import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _edit_helper import apply  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent.parent

# --- DECISIONS.md: the index -------------------------------------------
BEFORE = '''| DEC-37 | M3 changed **no application source file**; all changes are harness, dependencies and CI | M3 | — |
'''

AFTER = '''| DEC-37 | M3 changed **no application source file**; all changes are harness, dependencies and CI | M3 | — |
| DEC-38 | The root `faisal_hills.db` is **not** a demo, seed or API source; the approved master is the only property source of truth | M4 (D-10) | owner changes the demo source |
| DEC-39 | `config/policies.json` is the **single authority** for the v1 scope; the hard-coded fallbacks in the policy gate and the pipeline are fallbacks only | M4 (D-26) | owner changes the scope |
| DEC-40 | One block-alias table (`market/price_lookup.py` → `canonical_block()`); "E", "EXECUTIVE", "Executive", "EXEC" and "FHE" are the same block everywhere | M4 (D-27) | a new block spelling is added |
| DEC-41 | The lookup has **one implementation** (`market/price_lookup.py`) plus a **thin wrapper** at the handoff's path; the two are asserted to agree | M4 (D-08) | owner decides repository ownership (FH-02 Q1) |
| DEC-42 | A feature filter is applied only when the customer asks for that feature; an entity extractor's `False` default means "not specified", never "exclude" | M4 (D-25) | the master starts storing explicit `False` |
| DEC-43 | Every number in a customer-facing reply comes from the lookup result and a template; the LLM never supplies one (unchanged in spirit, now enforced end-to-end) | M4 + DEC-03/DEC-06 | M5 validator lands |
'''

apply(ROOT / "DECISIONS.md", BEFORE, AFTER)
