@echo off
cd /d "%~dp0"
.venv\Scripts\python.exe -m CODE_Controller.cli run %*
exit /b %errorlevel%
