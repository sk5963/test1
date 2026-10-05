@echo off
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe exit /b 1
.venv\Scripts\python.exe -m CODE_Controller.cli demo
if errorlevel 1 exit /b 1
cd CODE_UI
call npm start
exit /b %errorlevel%
