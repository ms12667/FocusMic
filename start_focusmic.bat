@echo off
setlocal
cd /d "%~dp0"
set PYTHONUTF8=1
echo Legacy browser Studio (developer only)...
start "FocusMic browser studio" /min .venv\Scripts\python.exe run_studio_local.py --device cuda --no-browser --port 7860
timeout /t 4 /nobreak >nul
if exist "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe" (
  start "" "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe" http://127.0.0.1:7860
) else (
  start "" http://127.0.0.1:7860
)
endlocal
