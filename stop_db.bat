@echo off
rem Stop the local PostgreSQL server started by start_db.bat (fast shutdown, data is kept).

setlocal
set "ROOT=%~dp0"
if not defined PGBIN set "PGBIN=%ROOT%..\tools\pgsql\bin"
for %%I in ("%PGBIN%") do set "PGBIN=%%~fI"

if not exist "%PGBIN%\pg_ctl.exe" (
  echo [stop_db] PostgreSQL binaries not found in "%PGBIN%". Set PGBIN to the pgsql\bin folder.
  exit /b 1
)
"%PGBIN%\pg_ctl.exe" -D "%ROOT%.pgdata" status >nul 2>&1
if errorlevel 1 (
  echo [stop_db] PostgreSQL is not running.
  exit /b 0
)
"%PGBIN%\pg_ctl.exe" -D "%ROOT%.pgdata" -m fast -w stop
exit /b %ERRORLEVEL%
