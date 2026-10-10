@echo off
REM One-time Python package setup for AltVerse (run by the installer).
cd /d "%~dp0"

set PY=py -3.11
py -3.11 --version >nul 2>&1
if errorlevel 1 set PY=py -3
%PY% --version >nul 2>&1
if errorlevel 1 (
  echo [AltVerse] Python not found. Install Python 3.10+ then run this again.
  exit /b 1
)

echo [AltVerse] Installing Python packages (flask, requests, pywebview)...
%PY% -m pip install --quiet --disable-pip-version-check flask requests pywebview waitress
echo [AltVerse] Python packages ready.
