@echo off
cd /d "%~dp0"
<model.txt (set /p DL_MODEL=&set /p DL_CTX=)
echo [AltVerse] downloading %DL_MODEL% ...
echo [AltVerse] big models take a while. Leave this window open.
set LEMONADE=lemonade
where lemonade >nul 2>&1
if errorlevel 1 (
  if exist "%LOCALAPPDATA%\lemonade_server\bin\lemonade.exe" (
    set LEMONADE="%LOCALAPPDATA%\lemonade_server\bin\lemonade.exe"
  ) else (
    echo [AltVerse] Lemonade Server not found - installing it now.
    echo [AltVerse] Approve the admin prompt if one appears.
    winget install --id AMD.LemonadeServer -e --accept-source-agreements --accept-package-agreements
    if exist "%LOCALAPPDATA%\lemonade_server\bin\lemonade.exe" (
      set LEMONADE="%LOCALAPPDATA%\lemonade_server\bin\lemonade.exe"
    ) else if exist "%ProgramFiles%\lemonade_server\bin\lemonade.exe" (
      set LEMONADE="%ProgramFiles%\lemonade_server\bin\lemonade.exe"
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
%LEMONADE% backends install llamacpp:cuda
%LEMONADE% pull %DL_MODEL%
echo [AltVerse] model ready. You can close this window.
pause
