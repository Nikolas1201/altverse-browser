@echo off
setlocal
cd /d "%~dp0"

REM AltVerse fallback launcher. Normally the desktop shortcut runs desktop.py
REM under pythonw (no console). This script is the console fallback / repair path.

REM 1. Python
set PY=py -3.11
set PYW=pyw -3.11
py -3.11 --version >nul 2>&1
if errorlevel 1 (set PY=py -3 & set PYW=pyw -3)
%PY% --version >nul 2>&1
if errorlevel 1 (
  echo [AltVerse] Install Python 3.10+ from https://www.python.org/downloads/
  echo [AltVerse] tick "Add python.exe to PATH", then run this again.
  pause
  exit /b 1
)

REM 2. Lemonade Server: use it, or install it with winget, or point at docs
set LEMONADE=lemonade
where lemonade >nul 2>&1
if errorlevel 1 (
  if exist "%LOCALAPPDATA%\lemonade_server\bin\lemonade.exe" (
    set LEMONADE="%LOCALAPPDATA%\lemonade_server\bin\lemonade.exe"
  ) else (
    if exist "%ProgramFiles%\lemonade_server\bin\lemonade.exe" (
      set LEMONADE="%ProgramFiles%\lemonade_server\bin\lemonade.exe"
    ) else (
      echo [AltVerse] Lemonade Server not found - installing it now.
      echo [AltVerse] Approve the admin prompt if one appears.
      winget install --id AMD.LemonadeServer -e --accept-source-agreements --accept-package-agreements
      if exist "%LOCALAPPDATA%\lemonade_server\bin\lemonade.exe" (
        set LEMONADE="%LOCALAPPDATA%\lemonade_server\bin\lemonade.exe"
      ) else (
        where lemonade >nul 2>&1
        if errorlevel 1 (
          echo [AltVerse] automatic install failed. Install manually, then run again:
          echo [AltVerse] https://lemonade-server.ai/docs/guide/install/
          pause
          exit /b 1
        )
      )
    )
  )
)

REM 3. Make sure the Lemonade server is up (CLI commands hang without it)
call "%~dp0EnsureLemonade.bat"
if errorlevel 1 (
  echo [AltVerse] Lemonade Server is not reachable.
  pause
  exit /b 1
)

REM 4. GPU backend (one-time; skips fast afterwards)
nvidia-smi --query-gpu=name --format=csv,noheader,nounits > "%TEMP%\altverse-gpu.txt" 2>nul
set GPUINFO=none
if exist "%TEMP%\altverse-gpu.txt" set /p GPUINFO=<"%TEMP%\altverse-gpu.txt"
del "%TEMP%\altverse-gpu.txt" 2>nul
if "%GPUINFO%"=="none" (set BACKEND=vulkan) else (set BACKEND=cuda)
echo [AltVerse] gpu=%GPUINFO% backend=%BACKEND%
call "%~dp0CudaWin10.bat"
if errorlevel 1 (
  echo [AltVerse] automatic CUDA setup failed, see above.
  pause
  exit /b 1
)
%LEMONADE% backends install llamacpp:%BACKEND%

REM 5. Python packages (fast if already there)
%PY% -m pip install --quiet --disable-pip-version-check flask requests pywebview waitress

REM 6. Open the native AltVerse window (no browser). Handles the model + server.
echo [AltVerse] launching AltVerse Browser...
start "" %PYW% desktop.py
exit /b 0
