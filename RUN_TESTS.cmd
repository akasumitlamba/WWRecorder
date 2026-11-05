@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0tests\windows_e2e\run_all.ps1" -InstallDeps
set "test_exit=%ERRORLEVEL%"
if exist "%~dp0artifacts\windows_e2e\summary.html" start "" "%~dp0artifacts\windows_e2e\summary.html"
exit /b %test_exit%
