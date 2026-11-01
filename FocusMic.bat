@echo off
setlocal
cd /d "%~dp0"
set PYTHONUTF8=1
start "" .venv\Scripts\pythonw.exe -m focusmic
endlocal
