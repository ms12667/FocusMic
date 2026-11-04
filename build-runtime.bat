@echo off
setlocal EnableExtensions
cd /d "%~dp0"
set "PYTHONUTF8=1"
set "PY=.venv\Scripts\python.exe"
if not exist "%PY%" (
  echo [FocusMic] Missing .venv\Scripts\python.exe
  exit /b 1
)
echo [FocusMic] Staging external AI runtime (PyTorch + CUDA)...
"%PY%" packaging\build_runtime.py
if errorlevel 1 goto :fail

set "ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" (
  echo [FocusMic] Inno Setup 6 ISCC.exe not found.
  echo Install it with: winget install --id JRSoftware.InnoSetup --exact
  goto :fail
)
echo [FocusMic] Building runtime installer with Inno Setup...
"%ISCC%" "packaging\FocusMic-Runtime.iss"
if errorlevel 1 goto :fail
echo.
echo [FocusMic] Done.
echo   Runtime installer: dist\installer\FocusMic-Runtime-2.9.1-cu128.exe
if /I "%~1"=="--pause" pause
exit /b 0

:fail
echo.
echo [FocusMic] Runtime build failed.
if /I "%~1"=="--pause" pause
exit /b 1
