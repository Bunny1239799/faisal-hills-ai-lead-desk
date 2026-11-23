# Founder demo package — read me first

**The inventory in this folder is `SYNTHETIC_DEMO_DATA`.** It is 37
fictional, plausible Faisal Hills-style plots generated for this demo.
It contains no real dealer names, no customer data, no phone numbers,
no WhatsApp messages, and nothing from the protected master data. It
must never be presented as real market data.

## What this demo is

A one-click, fully local demonstration of the REAL product: the same
deterministic safety architecture (policy gate, approved-inventory
lookup, numeric fact validation, claim guard, privacy whitelist,
escalation rules, operator review) that runs against the approved
master — here pointed, via the documented `FH_MASTER_PATH` variable,
at the synthetic demo inventory instead.

## Run it

Double-click **`run_founder_demo.bat`** (or run it from a terminal).
It starts the application on `http://127.0.0.1:8090/operator` and
opens the Operator Desk in your browser. To stop: close the window
titled *"Lead desk demo server"*.

The demo stores everything (conversations, actions, the demo database)
inside `demo\demo_data\`. It never touches:

* `D:\FaisalHills_Master_Data` (protected master data),
* the project's real `faisal_hills.db` (owner database),
* the approved master inventory,
* or anything outside this machine.

## What to show

Follow `demo_script.md` (the 12-step walkthrough, exact messages to
type), `demo_talking_points.md` (what to say about each step) and
`expected_behaviors.md` (what the system must do at each step — and
what it must never do).

## If something looks wrong during the demo

Close the server window, reopen the demo, and reproduce the step from
`expected_behaviors.md`. If the behavior differs from that document,
that is a defect: note the exact typed message and what happened, and
report it (the project's defect ledger is `DEFECTS.md`).
