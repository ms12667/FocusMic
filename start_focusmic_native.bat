@echo off
setlocal
cd /d C:\ms12667\MSDev\FalconProbe
set PYTHONUTF8=1
start "" .venv\Scripts\pythonw.exe native_ui.py
endlocal
