# Backup policy — founder-owned safety net

## Why this exists

The project's most valuable state (~140+ files of working code, tests
and reports) exists only as an **uncommitted working tree** on one
laptop disk. That is deliberate (the no-commit rule keeps the agent
out of git history) but it means a disk failure, a bad edit or an
accidental clean would be catastrophic. This policy makes recovery a
one-command action, owned by the founder.

## When to create a backup

Run the backup tool at every milestone boundary — and always before
you personally do anything to the tree (a manual edit, a review, a
git operation you perform yourself):

```
.venv\Scripts\python.exe tools\create_milestone_backup.py --note "what this milestone was"
```

It takes seconds, never modifies the repository, and is safe to run
as often as you like (each run is a new timestamped archive).

## Where backups live

`D:\FaisalHillsAILeadDesk\backups\milestone_backups\` — each backup is
a pair: `laya-gateway_<timestamp>.zip` plus a `.manifest.txt` carrying
the timestamp, the git HEAD at backup time, the file count, sizes, the
**SHA256 checksum of the ZIP**, and the exclusion list.

**Verify a backup matters to you:** compare the manifest's
`zip_sha256` against a fresh hash of the zip (e.g.
`certutil -hashfile <zip> SHA256`). If they differ, the archive is
corrupt — make another.

## What is excluded, and why

* `.venv`, `__pycache__`, `.pytest_cache`, caches — regenerable.
* `.git` — git's own database; copying it half-written can corrupt it.
* `data\` — runtime databases and stores. The owner database
  `faisal_hills.db` is **preserved in place, deliberately untouched**;
  if you want a snapshot of it, copy it manually while the desk is
  stopped.
* Screenshots and large generated artifacts — regenerable by the test
  suite.
* **The protected master data (`D:\FaisalHills_Master_Data`) is never
  read or written by the backup tool.** It lives outside the
  repository, has its own custody and its own integrity hash
  (`b77b3cb5…`); duplicating private dealer data into more places
  would widen its exposure, not protect it.

## How to restore

1. Stop the desk and any test runs.
2. Create a fresh folder and unzip the chosen archive into the
   repository root (it contains paths relative to the project root):
   `tar -xf laya-gateway_<timestamp>.zip -C D:\AI-Projects\laya-gateway`
   — or use Explorer's "Extract all" into the project folder.
3. The restored tree is the complete code/docs/tests state at the
   manifest's timestamp; runtime stores are recreated automatically on
   the next run (and `start_operator_desk.bat` / the demo launcher
   re-initialize their databases).
4. Optionally verify against the manifest: same git HEAD line, file
   count matches.

## Why the agent must never touch git history

The project's rules reserve every history-changing git operation
(`add`, `commit`, `push`, `reset`, `clean`, `stash`) to the founder.
The agent's work must remain inspectable as plain working-tree
changes — nothing hidden inside commits — and the founder must always
be able to diff exactly what changed since the last milestone. The
backup tool honors the same line: it only *reads* `git rev-parse` for
the manifest and changes nothing.
