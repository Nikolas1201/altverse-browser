@echo off
setlocal
cd /d "C:\Users\Nikolas\Documents\Default Project\altverse"

REM 1. clear any stale server on 5057
powershell -NoProfile -Command "$c=Get-NetTCPConnection -LocalPort 5057 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1; if($c){Stop-Process -Id $c.OwningProcess -Force}"

REM 2. make sure the 4B model is loaded (instant if already resident)
lemonade load Qwen3-4B-Instruct-2507-GGUF --llamacpp cuda --ctx-size 4096 --llamacpp-args "--flash-attn on --parallel 1 --cache-type-k q8_0 --cache-type-v q8_0 --threads 5 --threads-batch 5" --save-options

REM 3. start the app minimized
start "AltVerse Server" /min py -V:3.11 app.py

REM 4. wait until it answers
:wait
%SystemRoot%\System32\timeout.exe /t 2 /nobreak >nul
powershell -NoProfile -Command "try{(Invoke-WebRequest -Uri http://127.0.0.1:5057/ -TimeoutSec 2).StatusCode|Out-Null;exit 0}catch{exit 1}"
if errorlevel 1 goto wait

REM 5. dedicated window (separate Chrome profile so THIS process ends on close)
start "" /wait "C:\Program Files\Google\Chrome\Application\chrome.exe" --app=http://127.0.0.1:5057 --user-data-dir="%TEMP%\altverse-chrome"

REM 6. window closed -> quit the server
powershell -NoProfile -Command "$c=Get-NetTCPConnection -LocalPort 5057 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1; if($c){Stop-Process -Id $c.OwningProcess -Force}"
