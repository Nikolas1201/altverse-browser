@echo off
setlocal
cd /d "%~dp0"

:: model choice written by the installer (line1 = model id, line2 = ctx size)
if not exist model.txt (
  echo Qwen3-4B-Instruct-2507-GGUF>model.txt
  echo 4096>>model.txt
)
<model.txt (set /p ALTVERSE_MODEL=&set /p ALTVERSE_CTX=)
echo [AltVerse] model=%ALTVERSE_MODEL% ctx=%ALTVERSE_CTX%

:: 1. Python: prefer 3.11 (known-good module set), else default 3.x
py -3.11 --version >nul 2>&1
if errorlevel 1 (set PY=py -3) else (set PY=py -3.11)
%PY% --version
if errorlevel 1 (
  echo [AltVerse] Install Python 3.10+ from https://www.python.org/downloads/
  echo [AltVerse] tick "Add python.exe to PATH", then run this again.
  pause
  exit /b 1
)
%PY% -m pip install --quiet flask requests

:: 2. Lemonade Server: use it, or install it with winget, or point at docs
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

:: 3. CUDA backend + model (each step skips fast when already done)
%LEMONADE% backends install llamacpp:cuda
if errorlevel 1 (
  echo [AltVerse] CUDA backend install failed. Windows 11 22H2+ is required.
  pause
  exit /b 1
)
%LEMONADE% pull %ALTVERSE_MODEL%
%LEMONADE% load %ALTVERSE_MODEL% --llamacpp cuda --ctx-size %ALTVERSE_CTX% --llamacpp-args "--flash-attn on --parallel 1 --cache-type-k q8_0 --cache-type-v q8_0" --save-options --pinned

:: 4. start the app minimized
start "AltVerse Server" /min %PY% app.py

:: 5. wait until it answers
:wait
%SystemRoot%\System32\timeout.exe /t 2 /nobreak >nul
powershell -NoProfile -Command "try{(Invoke-WebRequest -Uri http://127.0.0.1:5057/ -TimeoutSec 2).StatusCode|Out-Null;exit 0}catch{exit 1}"
if errorlevel 1 goto wait

:: 6. open it: Chrome, else Edge, else default browser
set BROWSER=
if exist "C:\Program Files\Google\Chrome\Application\chrome.exe" set BROWSER="C:\Program Files\Google\Chrome\Application\chrome.exe"
if not defined BROWSER if exist "C:\Program Files (x86)\Google\Chrome\Application\chrome.exe" set BROWSER="C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"
if not defined BROWSER if exist "C:\Program Files\Microsoft\Edge\Application\msedge.exe" set BROWSER="C:\Program Files\Microsoft\Edge\Application\msedge.exe"
if not defined BROWSER if exist "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe" set BROWSER="C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
if defined BROWSER (
  start "" /wait %BROWSER% --app=http://127.0.0.1:5057 --user-data-dir="%TEMP%\altverse-chrome"
  call :killserver
  echo [AltVerse] server stopped. Bye!
) else (
  start http://127.0.0.1:5057
  echo [AltVerse] no Chrome or Edge found, opened your default browser instead.
  echo [AltVerse] running at http://127.0.0.1:5057 - close this window to stop it.
  pause >nul
)
exit /b 0

:killserver
powershell -NoProfile -Command "$c=Get-NetTCPConnection -LocalPort 5057 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1; if($c){Stop-Process -Id $c.OwningProcess -Force}"
exit /b
