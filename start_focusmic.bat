@echo off
setlocal
cd /d C:\ms12667\MSDev\FalconProbe
set PYTHONUTF8=1
echo Starting FocusMic (Falcon-Small, 0.2 s hop)...
start "FocusMic server" /min .venv\Scripts\python.exe run_studio_local.py --device cuda --no-browser --port 7860
timeout /t 4 /nobreak >nul
if exist "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe" (
  start "" "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe" http://127.0.0.1:7860
) else (
  start "" http://127.0.0.1:7860
)
endlocal
