@echo off
REM Shared Win10 CUDA workaround for AltVerse.
REM Contract: caller sets BACKEND and LEMONADE. No-op unless Win10 + cuda.
REM Mirrors what Lemonade does on Win11: download the sm_XX .7z asset,
REM extract to cuda.staging, write version.txt, swap into place.

if not "%BACKEND%"=="cuda" exit /b 0

for /f %%B in ('powershell -NoProfile -Command "[System.Environment]::OSVersion.Version.Build"') do set BUILD=%%B
if not defined BUILD exit /b 0
if %BUILD% GEQ 22000 exit /b 0

if not defined LEMONADE set LEMONADE=lemonade
if defined LEMONADE_CACHE_DIR set LCACHE=%LEMONADE_CACHE_DIR%\bin\llamacpp
if not defined LEMONADE_CACHE_DIR set LCACHE=%USERPROFILE%\.cache\lemonade\bin\llamacpp
set "LCBJSON=%LOCALAPPDATA%\lemonade_server\bin\resources\backend_versions.json"
if not exist "%LCBJSON%" set "LCBJSON=%ProgramFiles%\lemonade_server\bin\resources\backend_versions.json"
if not exist "%LCBJSON%" echo [AltVerse] WARNING: Lemonade resources not found, skipping Win10 CUDA workaround.
if not exist "%LCBJSON%" exit /b 0

for /f "delims=" %%V in ('powershell -NoProfile -Command "Get-Content '%LCBJSON%' -Raw | ConvertFrom-Json | ForEach-Object { $_.llamacpp.cuda }"') do set CUDAVER=%%V
powershell -NoProfile -Command "nvidia-smi --query-gpu=compute_cap --format=csv,noheader,nounits | Select-Object -First 1 | Out-File -Encoding ascii '%TEMP%\altverse-ccap.txt'"
set /p CCAP=<"%TEMP%\altverse-ccap.txt"
del "%TEMP%\altverse-ccap.txt" 2>nul
set SM=sm_%CCAP:.=%

echo [AltVerse] Windows 10 build %BUILD% - setting up CUDA %CUDAVER% for %SM% with 7-Zip.

set INSTVER=none
if exist "%LCACHE%\cuda\version.txt" set /p INSTVER=<"%LCACHE%\cuda\version.txt"
if "%INSTVER%"=="%CUDAVER%" echo [AltVerse] CUDA backend %CUDAVER% already installed.
if "%INSTVER%"=="%CUDAVER%" exit /b 0

set "SEVENZIP=C:\Program Files\7-Zip\7z.exe"
if not exist "%SEVENZIP%" set "SEVENZIP=C:\Program Files (x86)\7-Zip\7z.exe"
if not exist "%SEVENZIP%" echo [AltVerse] installing 7-Zip for the Win10 workaround...
if not exist "%SEVENZIP%" winget install --id 7zip.7zip -e --accept-source-agreements --accept-package-agreements
if not exist "%SEVENZIP%" echo [AltVerse] 7-Zip install failed, cannot set up CUDA on Windows 10.
if not exist "%SEVENZIP%" exit /b 1

echo [AltVerse] downloading CUDA runtime %CUDAVER% for %SM%, about 550 MB...
curl.exe -L --fail -o "%TEMP%\altverse-cuda.7z" "https://github.com/lemonade-sdk/llama.cpp/releases/download/%CUDAVER%/llama-%CUDAVER%-windows-cuda-%SM%-x64.7z"
if errorlevel 1 echo [AltVerse] download failed, check internet and try again.
if errorlevel 1 exit /b 1

if exist "%LCACHE%\cuda.staging" rmdir /s /q "%LCACHE%\cuda.staging"
mkdir "%LCACHE%\cuda.staging" 2>nul
"%SEVENZIP%" x "%TEMP%\altverse-cuda.7z" -o"%LCACHE%\cuda.staging" -y
if errorlevel 1 echo [AltVerse] extraction failed.
if errorlevel 1 exit /b 1
echo %CUDAVER%>"%LCACHE%\cuda.staging\version.txt"

if exist "%LCACHE%\cuda.old" rmdir /s /q "%LCACHE%\cuda.old"
if exist "%LCACHE%\cuda" move "%LCACHE%\cuda" "%LCACHE%\cuda.old" >nul
move "%LCACHE%\cuda.staging" "%LCACHE%\cuda" >nul
if exist "%LCACHE%\cuda.old" rmdir /s /q "%LCACHE%\cuda.old"
del "%TEMP%\altverse-cuda.7z"
%LEMONADE% backends install llamacpp:cuda
echo [AltVerse] CUDA backend ready.
exit /b 0
