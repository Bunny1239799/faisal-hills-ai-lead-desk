@echo off
rem M12.2 - the one-click operator desk launcher.
rem Starts the application on 127.0.0.1:8080, waits for /health, then
rem opens the desk in the default browser. No new dependency: it uses
rem the project's own virtualenv and Windows' built-in tools.
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo The project virtualenv was not found at .venv\Scripts\python.exe.
  echo Run this file from the repository root.
  pause
  exit /b 1
)

start "Faisal Hills Lead Desk server" cmd /c ".venv\Scripts\python.exe -m uvicorn app.server:app --host 127.0.0.1 --port 8080"

powershell -NoProfile -Command "$u='http://127.0.0.1:8080/health'; for($i=0; $i -lt 60; $i++){ try { Invoke-WebRequest -UseBasicParsing $u | Out-Null; exit 0 } catch { Start-Sleep -Milliseconds 500 } }; exit 1"

start "" "http://127.0.0.1:8080/operator"
endlocal
