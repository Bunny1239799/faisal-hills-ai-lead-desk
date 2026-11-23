# Upload guide — Faisal Hills AI Lead Desk

How to put this project in front of AI evaluation programs, hackathons,
incubators and portfolio reviewers — safely, in order, with the exact
materials each channel needs.

## 0. What is safe to share (read first)

The share package is built by an explicit include-list, so private data
**cannot** leak:

```powershell
cd D:\AI-Projects\laya-gateway
.\tools\build_upload_package.ps1
# -> D:\FaisalHillsAILeadDesk\showcase_package\faisal-hills-ai-lead-desk-v1.0.0-<date>.zip
```

Excluded by design: every `*.db` (demo DB, conversation/lead stores, raw
archive), `market\master_inventory.csv` (business pricing data), backups,
logs, `.venv`, caches, internal working notes. The zip contains a
`MANIFEST.txt` listing exactly what is inside and what was left out.
Add `-IncludeMasterData` only if *you* decide the pricing dataset may be
shared with that specific program.

## 1. GitHub — the primary artifact

1. Create the repository (private first, public when you are ready):
   `gh repo create faisal-hills-ai-lead-desk --private` or via github.com.
2. Push the clean snapshot:

   ```powershell
   cd D:\AI-Projects\laya-gateway
   git add -A
   git commit -m "Faisal Hills AI Lead Desk v1.0.0 — showcase release"
   git branch -M main
   git remote add origin https://github.com/<your-user>/faisal-hills-ai-lead-desk.git
   git push -u origin main
   ```

3. Repository settings: description = the tagline below; topics =
   `fastapi`, `sqlite`, `real-estate`, `lead-qualification`,
   `human-in-the-loop`, `pytest`, `offline-first`.
4. Tag the release: `git tag -a v1.0.0 -m "Showcase release"` and
   `git push origin v1.0.0`; attach the share zip as a release asset.
5. GitHub Actions note: `.github/workflows/ci.yml` exists, but the
   master-dependent tests need `FH_MASTER_PATH` (the approved master is
   business data, not in the repo). Either leave Actions disabled, add a
   repository secret with a master file URL, or remove the workflow before
   making the repo public.

## 2. AI-assistant evaluation programs (ChatGPT Projects, Claude Projects, Gemini)

Upload these files only — they are written for exactly this:

1. `README.md` — the full story with screenshots.
2. `docs/PROJECT_OVERVIEW.md` — the one-page pitch + checkable metrics.
3. `docs/VERIFICATION.md` — the verification matrix (evidence per component).
4. Two or three screenshots: `docs/screenshots/01-desk.png`,
   `03-desk-exact-match.png`, `04-system-status.png`.
5. Optionally 3–5 source files if the program reviews code:
   `app/server.py`, `app/turn_pipeline.py`, `market/fact_guard.py`,
   `tests/test_m5_surface_completeness.py`, `tools/reset_demo_state.py`.

Do **not** upload databases, the master CSV, or internal notes
(CHECKPOINT/DECISIONS/DEFECTS/PROGRESS). The guides above already say why.

## 3. Hackathon / incubator / grant forms (Devpost-style)

Typical fields, ready to paste:

**Tagline (≤ 60 chars):**
> The lead desk that refuses to invent a number.

**Short description (≤ 280 chars):**
> Faisal Hills AI Lead Desk qualifies real-estate buyers over WhatsApp-style
> chat and drafts every reply from one fingerprinted master inventory. Fact
> and claim guards trace each number to the approved data; anything
> untraceable escalates to a human. Human-in-the-loop by construction:
> the application drafts, a person sends.

**Long description:** paste `docs/PROJECT_OVERVIEW.md`.

**Tech stack:** Python (stdlib core + SQLite), FastAPI/uvicorn, plain
HTML/CSS/JS (no build step), pytest (1,189 offline tests), Leaflet with
bundled offline tiles.

**Metrics bullets:**
- 1,189 offline tests passing; every serving API route guard-covered (enforced by test)
- 0 auto-sent messages — no send capability exists in the code
- Master fingerprint shown on every page: `b77b3cb5 · 374 rows · 2026-09-22→2026-10-07`
- 0 bytes of private data in the share package (explicit packaging script)

**Screenshots:** from `docs/screenshots/` (desk, exact match, system status).

## 4. Video demo (2–3 minutes)

Follow `docs/DEMO_SCRIPT.md` and record the desk at 1600×900:
1. Open the desk; read the master chip aloud (the desk serves a fingerprinted master).
2. Send "What is the price of a 7 marla plot in Block C?" — show the draft with its traceability banner and the Verified options panel.
3. Send a discount request — show the escalation and Take over.
4. Open a restored conversation — the transcript replays with the same verified options.
5. Open **System status** — every component labelled from live truth.
6. Close with the packaging line: "the share package excludes all private data by construction."

## 5. Order of operations (recommended)

1. Verify: `.\.venv\Scripts\python.exe -m pytest -q` — green.
2. Rebuild the package: `.\tools\build_upload_package.ps1`.
3. Push to GitHub (private), tag v1.0.0.
4. Upload the doc set to the AI evaluation programs (section 2).
5. Submit to hackathons/incubators with the form copy (section 3).
6. Record the video once and reuse it everywhere.

## 6. If a program asks to RUN the project

The demo needs the founder's approved master (business data). Two options:
- point `FH_MASTER_PATH` at a master file in the same JSONL schema and run
  `.\start_operator_desk.bat`; or
- share the screen recording + screenshots instead, and keep the master
  private. The System status view is designed to make the running system
  auditable without exposing the data.
