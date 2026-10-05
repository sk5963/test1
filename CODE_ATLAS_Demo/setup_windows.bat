@echo off
setlocal
cd /d "%~dp0"
py -3 -m venv .venv
if errorlevel 1 goto fail
.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 goto fail
cd CODE_UI
call npm ci --ignore-scripts
if errorlevel 1 goto fail
node node_modules\electron\install.js
if errorlevel 1 goto fail
exit /b 0
:fail
exit /b 1
