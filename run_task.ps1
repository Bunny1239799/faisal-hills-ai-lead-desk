param([string]$n)
$args2 = @("--model","gemini/gemini-3.7-flash","--weak-model","gemini/gemini-3.5-flash-lite","--read","PROJECT_STATE.md","--read","PROGRESS.md","--read","TASK_$n.md")
if (Test-Path STATUS.md) { $args2 += @("--read","STATUS.md") }
& D:\tools\aider-venv\Scripts\aider @args2