@echo off
rem AgriVarsha demo launcher: database -> backend API -> frontend -> browser.
rem Run from anywhere; double-click works. Close the two server windows to stop.

setlocal
set "ROOT=%~dp0"
set "API=http://127.0.0.1:8000/api/health"
set "WEB=http://localhost:5173/"

echo [demo] 1/4 Starting PostgreSQL...
call "%ROOT%start_db.bat"
if errorlevel 1 (
  echo [demo] Database did not start. See the message above.
  pause
  exit /b 1
)

echo [demo] 2/4 Starting the backend API...
powershell -NoProfile -Command "try { Invoke-WebRequest -UseBasicParsing '%API%' -TimeoutSec 3 | Out-Null; exit 0 } catch { exit 1 }"
if %ERRORLEVEL%==0 (
  echo [demo]     Backend already running on port 8000.
) else (
  if not exist "%ROOT%backend\.venv\Scripts\python.exe" (
    echo [demo] backend\.venv not found. Create it, then run: pip install -r backend\requirements.txt
    pause
    exit /b 1
  )
  start "AgriVarsha API" /D "%ROOT%backend" cmd /k ".venv\Scripts\python.exe -m uvicorn app.main:app --port 8000"
)

echo [demo]     Waiting for the backend (a cold start can take ~90 s)...
powershell -NoProfile -Command "$t=Get-Date; while (((Get-Date)-$t).TotalSeconds -lt 240) { try { Invoke-WebRequest -UseBasicParsing '%API%' -TimeoutSec 5 | Out-Null; exit 0 } catch { Start-Sleep -Seconds 3 } }; exit 1"
if errorlevel 1 (
  echo [demo] Backend did not answer within 4 minutes. Check the "AgriVarsha API" window.
  pause
  exit /b 1
)
echo [demo]     Backend is up.

echo [demo] 3/4 Starting the frontend...
if not exist "%ROOT%frontend\node_modules" (
  echo [demo]     Installing frontend packages, first run only...
  pushd "%ROOT%frontend"
  call npm install
  popd
)
powershell -NoProfile -Command "try { Invoke-WebRequest -UseBasicParsing '%WEB%' -TimeoutSec 3 | Out-Null; exit 0 } catch { exit 1 }"
if not %ERRORLEVEL%==0 (
  start "AgriVarsha Web" /D "%ROOT%frontend" cmd /k "npm run dev"
  powershell -NoProfile -Command "$t=Get-Date; while (((Get-Date)-$t).TotalSeconds -lt 120) { try { Invoke-WebRequest -UseBasicParsing '%WEB%' -TimeoutSec 5 | Out-Null; exit 0 } catch { Start-Sleep -Seconds 2 } }; exit 1"
)

echo [demo] 4/4 Opening %WEB%
start "" "%WEB%"
echo [demo] Ready. Press D in the app for demo controls.
endlocal
exit /b 0
