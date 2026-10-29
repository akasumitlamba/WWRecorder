@echo off
cd /d "%~dp0"
set "_wwrPython=python"
if exist ".venv\Scripts\python.exe" set "_wwrPython=.venv\Scripts\python.exe"
"%_wwrPython%" "scripts\prepare_media_runtime.py"
if errorlevel 1 exit /b 1
"%_wwrPython%" "app\main.py" %*
exit /b %errorlevel%
