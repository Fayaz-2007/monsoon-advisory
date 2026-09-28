@echo off
rem One-click, no-admin setup of PostgreSQL 16 + PostGIS for monsoon-advisory.
rem Double-click it, or run from cmd. Optional arguments are passed to setup_db.ps1, e.g.
rem   setup_db.bat -Port 5440 -DataDir D:\pg\data -ToolsDir D:\pg\tools -EnvFile D:\pg\.env
rem Set SETUP_NO_PAUSE=1 to skip the final "press any key" (for scripted use).

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup_db.ps1" %*
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" echo. & echo [setup_db] FAILED with exit code %RC% - see the messages above.
if not defined SETUP_NO_PAUSE pause
exit /b %RC%
