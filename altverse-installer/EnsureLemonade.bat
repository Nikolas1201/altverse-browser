@echo off
REM Ensures the Lemonade server is reachable before CLI commands (backends/pull/load).
REM Caller has LEMONADE set. Starts LemonadeServer.exe --silent if the port is dead.

powershell -NoProfile -Command "try{(Invoke-WebRequest -Uri http://127.0.0.1:13305/api/version -TimeoutSec 3).StatusCode|Out-Null;exit 0}catch{exit 1}"
if not errorlevel 1 exit /b 0

set LSRV=
if exist "%LOCALAPPDATA%\lemonade_server\bin\LemonadeServer.exe" set LSRV="%LOCALAPPDATA%\lemonade_server\bin\LemonadeServer.exe"
if not defined LSRV if exist "%ProgramFiles%\lemonade_server\bin\LemonadeServer.exe" set LSRV="%ProgramFiles%\lemonade_server\bin\LemonadeServer.exe"
if not defined LSRV exit /b 0

echo [AltVerse] starting Lemonade Server...
start "" /min %LSRV% --silent

set TRIES=0
:waitlemonade
%SystemRoot%\System32\timeout.exe /t 3 /nobreak >nul
powershell -NoProfile -Command "try{(Invoke-WebRequest -Uri http://127.0.0.1:13305/api/version -TimeoutSec 3).StatusCode|Out-Null;exit 0}catch{exit 1}"
if not errorlevel 1 echo [AltVerse] Lemonade Server ready.
if not errorlevel 1 exit /b 0
set /a TRIES+=1
if %TRIES% LSS 20 goto waitlemonade
echo [AltVerse] Lemonade Server did not come up in time.
exit /b 1
