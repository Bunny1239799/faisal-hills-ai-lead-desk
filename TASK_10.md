# TASK 10: Automation, lead workflow, CI

Follow PROJECT_STATE.md HARD RULES. Read PROGRESS.md and TASK_09. Standard library plus pytest. UTF-8 without BOM.

1. app/leads.py: lead state machine new -> qualified -> handoff -> site_visit -> closed or lost; reject invalid transitions; reminders table (lead_id, due_at, reason, done); a simple scheduler thread started by the server that marks overdue reminders; GET /api/reminders; show an overdue badge in the console.
2. start_all.ps1: path variables at the top (Laya at D:\laya\.venv\Scripts\laya-serve.exe with the known environment variables, llama-server at D:\llama\llama-server.exe with D:\qwen2.5-1.5b-instruct-q4_k_m.gguf, project root). Parameters -WithLaya and -WithLlama (both optional). Starts each in its own window, waits for health checks, starts the console and opens the browser. Skips anything already running on its port.
3. refresh_market.ps1: runs tools/ingest_all.py then the market report; safe to schedule. Document a Windows Task Scheduler (schtasks) command for a daily run in README.md.
4. backup.ps1: copies the SQLite database and data/raw_chats to a timestamped folder under a path parameter (default D:\backups\laya-gateway) and keeps the last 14.
5. .github/workflows/ci.yml: Python 3.11, pip install -r requirements.txt, pytest -q. No secrets.
6. README.md: how to run everything, the two modes, how to swap in real data, how to start each script (mention powershell -ExecutionPolicy Bypass -File).
7. Tests for the state machine and reminders.

Finish by listing exact commands.