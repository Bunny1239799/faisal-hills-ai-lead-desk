# Contributing

This repository is the public showcase of a privately maintained product.
Issues, questions and small documentation corrections are welcome. Larger
changes are decided with the maintainer first, because several guarantees
below are enforced by tests on purpose.

## Guarantees that must survive any change

- **Tests are the specification.** Do not change a test to fit a change.
  Change the code until the existing assertion passes, or open an issue
  explaining why the guarantee itself should change.
- **Every serving route is guarded.** A new API route is not done until it
  is registered in `tests/test_m5_surface_completeness.py` and covered by
  a check that proves it cannot serve an untraceable figure.
- **No sending capability.** Nothing may send, forward or schedule a
  message to a dealer. The application drafts; a human sends.
- **No private data.** Dealer names, phone numbers, plot numbers, raw chat
  text, every database file and the approved master inventory stay out of
  the repository and out of anything it produces.
- **Truthful counters.** The System status page and `/api/system-status`
  are computed at request time. Never hardcode a number there.

## Development setup

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m data.demo_seed
.\.venv\Scripts\python.exe -m pytest -q
```

The suite is fully offline. Price-pipeline tests read the approved master
inventory: point `FH_MASTER_PATH` at a master file in the same JSONL schema
to run them on another machine.

## Pull requests

- Fork, create a branch, keep the change focused.
- Run the full suite; a green run on your machine is the minimum evidence.
- Describe what changed and why; link the issue if there is one.
- Documentation fixes are merged quickly. Behaviour changes need the
  guarantees above to stay green and will be discussed first.

## Questions

Open a discussion or an issue with the `question` label. For security
reports, see [SECURITY.md](SECURITY.md).
