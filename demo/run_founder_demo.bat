@echo off
rem =====================================================================
rem  FAISAL HILLS AI LEAD DESK - FOUNDER DEMO LAUNCHER
rem  SYNTHETIC_DEMO_DATA: 37 fictional plots. No real dealer data, no
rem  real customer data, no real phone numbers, no WhatsApp messages.
rem  Runs 100%% locally on 127.0.0.1. Sends nothing anywhere. Touches
rem  neither the protected master data nor the owner database.
rem =====================================================================
setlocal
cd /d "%~dp0.."

if not exist ".venv\Scripts\python.exe" (
  echo The project virtualenv was not found at .venv\Scripts\python.exe.
  echo Run this file from the demo folder of the repository.
  pause
  exit /b 1
)

set "FH_MASTER_PATH=%~dp0sample_inventory.jsonl"
set "M11_STATE_DB=%~dp0demo_data\state.db"
set "M11_DEMAND_DB=%~dp0demo_data\demand.db"
set "M12_LOG_DB=%~dp0demo_data\log.db"
set "DB_PATH=%~dp0demo_data\faisal_demo.db"

echo ====================================================================
echo   FAISAL HILLS AI LEAD DESK  -  FOUNDER DEMO
echo   Inventory : SYNTHETIC_DEMO_DATA (37 fictional Faisal Hills plots)
echo   Safety    : the REAL deterministic architecture - same gates,
echo                same privacy rules, same escalation policy
echo   Boundary  : localhost only, nothing is sent to anyone
echo   Stop      : close the server window titled "Lead desk demo server"
echo ====================================================================
echo.

rem create the demo database (fresh on first run; safe to re-run)
".venv\Scripts\python.exe" -c "import app.server as s; s.init_app_db()" >nul 2>&1

start "Lead desk demo server" cmd /c ".venv\Scripts\python.exe -m uvicorn app.server:app --host 127.0.0.1 --port 8090"

powershell -NoProfile -Command "$u='http://127.0.0.1:8090/health'; for($i=0; $i -lt 60; $i++){ try { Invoke-WebRequest -UseBasicParsing $u | Out-Null; exit 0 } catch { Start-Sleep -Milliseconds 500 } }; exit 1"

start "" "http://127.0.0.1:8090/operator"
endlocal
