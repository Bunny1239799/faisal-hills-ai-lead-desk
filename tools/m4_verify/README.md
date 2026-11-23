# M4 verification tools

Standalone verification scripts for the M4 closeout. They are **not**
pytest modules — they are run by hand and print a report. The regression
tests that enforce the same properties live in `tests/test_m4_closeout.py`.

Every script uses its own throwaway SQLite file and never writes to the
owner's `faisal_hills.db` or to the approved master.

```powershell
cd D:\AI-Projects\laya-gateway
.venv\Scripts\python.exe tools\m4_verify\verify_no_price_leak.py
.venv\Scripts\python.exe tools\m4_verify\verify_robustness.py
.venv\Scripts\python.exe tools\m4_verify\verify_scope_authority.py
.venv\Scripts\python.exe tools\m4_verify\verify_adapter_scope.py
.venv\Scripts\python.exe tools\m4_verify\verify_ci_portability.py
```

| Script | What it proves | Expected |
|---|---|---|
| `verify_no_price_leak.py` | The customer-facing path never puts a price figure into a reply the lookup could not support (escalate / refuse / thin data) | `LEAKS: 0` |
| `verify_robustness.py` | 21 question shapes — no size, `1 kanal`, `0 marla`, `7.5 marla`, Roman-Urdu, injection, privacy — never crash the pipeline | `CRASHES: 0`, `LEAKS: 0` |
| `verify_scope_authority.py` | `config/policies.json` → `active_blocks` is the **single** authority: the lookup, the policy gate and the customer-facing path all follow it | `FOLLOWS` |
| `verify_adapter_scope.py` | `get_verified_market_facts()` no longer prices a parked block (defect D-02) | `block E -> matched=0` |
| `verify_ci_portability.py` | The suite passes with `FH_MASTER_PATH` set, exactly as GitHub Actions runs it | `EXIT: 0` |

`verify_scope_authority.py` copies `config/` into a temporary directory
and points the lookup at the copy. The repository's own
`config/policies.json` is **never modified**.

`verify_ci_portability.py` derives a JSONL master from the in-repo
`market/master_inventory.csv` into a temporary directory and runs the
whole suite with `FH_MASTER_PATH` pointing at it.
