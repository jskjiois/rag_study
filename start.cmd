@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1"
set "launch_status=%errorlevel%"
if not "%launch_status%"=="0" pause
exit /b %launch_status%
