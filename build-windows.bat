@echo off
setlocal EnableExtensions
cd /d "%~dp0"
set "PYTHONUTF8=1"
set "PY=.venv\Scripts\python.exe"
if not exist "%PY%" (
  echo [FocusMic] Missing .venv\Scripts\python.exe
  exit /b 1
)
echo [FocusMic] Building one-folder app with PyInstaller...
"%PY%" -m PyInstaller --noconfirm --clean FocusMic.spec
if errorlevel 1 (
  echo [FocusMic] Collect failed; retrying once after pre-seeding PySide6 MSVCP140.dll...
  if not exist "dist\FocusMic\_internal\PySide6" mkdir "dist\FocusMic\_internal\PySide6"
  copy /Y ".venv\Lib\site-packages\PySide6\MSVCP140.dll" "dist\FocusMic\_internal\PySide6\MSVCP140.dll" >nul
  "%PY%" -m PyInstaller --noconfirm FocusMic.spec
)
if errorlevel 1 goto :fail
copy /Y "README.md" "dist\FocusMic\" >nul
copy /Y "LICENSE" "dist\FocusMic\" >nul
copy /Y "NOTICE" "dist\FocusMic\" >nul
copy /Y "THIRD_PARTY_LICENSES.md" "dist\FocusMic\" >nul

set "ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" (
  echo [FocusMic] Inno Setup 6 ISCC.exe not found.
  echo Install it with: winget install --id JRSoftware.InnoSetup --exact
  goto :fail
)
echo [FocusMic] Building installer with Inno Setup...
"%ISCC%" "packaging\FocusMic.iss"
if errorlevel 1 goto :fail
echo.
echo [FocusMic] Done.
echo   App:       dist\FocusMic\FocusMic.exe
echo   Installer: dist\installer\FocusMic-Setup-0.1.0.exe
echo   Runtime:   dist\installer\FocusMic-Runtime-2.9.1-cu128.exe (run build-runtime.bat)
if /I "%~1"=="--pause" pause
exit /b 0

:fail
echo.
echo [FocusMic] Build failed.
if /I "%~1"=="--pause" pause
exit /b 1
