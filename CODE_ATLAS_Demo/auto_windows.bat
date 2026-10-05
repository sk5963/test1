@echo off
cd /d "%~dp0"
.venv\Scripts\python.exe -m CODE_Controller.cli watch
exit /b %errorlevel%
