@echo off
rem Start the local PostgreSQL 16 + PostGIS server (native Windows, no admin needed).
rem Data folder: .pgdata\ in this repo (git-ignored). Log: .pgdata\server.log
rem Binaries: %PGBIN% (default ..\tools\pgsql\bin next to this repo). Port: %PGPORT% (default 5432).
rem Run from cmd.exe; afterwards psql/pg_ctl are on PATH in that window.

setlocal
set "ROOT=%~dp0"
if not defined PGBIN set "PGBIN=%ROOT%..\tools\pgsql\bin"
if not defined PGPORT set "PGPORT=5432"
for %%I in ("%PGBIN%") do set "PGBIN=%%~fI"

if not exist "%PGBIN%\pg_ctl.exe" (
  echo [start_db] PostgreSQL binaries not found in "%PGBIN%". Run setup_db.bat, or set PGBIN.
  exit /b 1
)
if not exist "%ROOT%.pgdata\PG_VERSION" (
  echo [start_db] No data folder at "%ROOT%.pgdata". Run setup_db.bat first.
  exit /b 1
)

"%PGBIN%\pg_ctl.exe" -D "%ROOT%.pgdata" status >nul 2>&1
if %ERRORLEVEL%==0 (
  echo [start_db] PostgreSQL is already running ^(port %PGPORT%^)
) else (
  "%PGBIN%\pg_ctl.exe" -D "%ROOT%.pgdata" -l "%ROOT%.pgdata\server.log" -w -t 60 start
  if errorlevel 1 (
    echo [start_db] Start failed - see "%ROOT%.pgdata\server.log"
    exit /b 1
  )
  echo [start_db] PostgreSQL started on localhost:%PGPORT%
)

endlocal & set "PATH=%PGBIN%;%PATH%"
exit /b 0
