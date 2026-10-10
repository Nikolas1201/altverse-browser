# AltVerse one-shot setup. Runs every install step silently and writes live
# progress to a status file the installer reads to drive its GUI progress bar.
# Status file format: "<percent>|<message>"  (final: "100|DONE" / "0|ERROR|...")

$ErrorActionPreference = 'Stop'
$status = Join-Path $env:TEMP 'altverse-setup.status'

function Set-Status([int]$pct, [string]$msg) {
    try { Set-Content -Path $status -Value ("{0}|{1}" -f $pct, $msg) -Encoding UTF8 } catch {}
}

function Have($exe) {
    return [bool](Get-Command $exe -ErrorAction SilentlyContinue)
}

function LemonadeExe {
    $c = Join-Path $env:LOCALAPPDATA 'lemonade_server\bin\lemonade.exe'
    if (Test-Path $c) { return $c }
    $c = Join-Path $env:ProgramFiles 'lemonade_server\bin\lemonade.exe'
    if (Test-Path $c) { return $c }
    return 'lemonade'
}

function Winget($id) {
    & winget install --id $id -e --silent --accept-source-agreements --accept-package-agreements | Out-Null
}

try {
    Set-Status 2 'Preparing...'
    $model = 'Qwen3-4B-Instruct-2507-GGUF'
    $mf = Join-Path $PSScriptRoot 'model.txt'
    if (Test-Path $mf) { $model = (Get-Content $mf -TotalCount 1).Trim() }

    # 1. Python
    Set-Status 5 'Checking Python...'
    $py = 'py -3.11'
    py -3.11 --version *> $null
    if ($LASTEXITCODE -ne 0) { $py = 'py -3' }
    py -3 --version *> $null
    if ($LASTEXITCODE -ne 0) {
        Set-Status 8 'Installing Python...'
        Winget 'Python.Python.3.12'
        $py = 'py -3'
    }

    # 2. WebView2 runtime (powers the app window)
    Set-Status 22 'Checking WebView2 runtime...'
    $wv = 'HKLM:\SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}'
    if (-not (Test-Path $wv)) {
        Set-Status 25 'Installing WebView2 runtime...'
        Winget 'Microsoft.EdgeWebView2Runtime'
    }

    # 3. Lemonade Server
    Set-Status 38 'Checking Lemonade Server...'
    $lem = LemonadeExe
    if (($lem -eq 'lemonade') -and (-not (Have 'lemonade'))) {
        Set-Status 42 'Installing Lemonade Server...'
        Winget 'AMD.LemonadeServer'
        $lem = LemonadeExe
    }

    # 4. Python packages
    Set-Status 55 'Installing Python packages...'
    & cmd.exe /c "$py -m pip install --quiet --disable-pip-version-check flask requests pywebview waitress" | Out-Null

    # 5. Make sure the Lemonade server is running
    Set-Status 63 'Starting the AI backend...'
    & "$PSScriptRoot\EnsureLemonade.bat" | Out-Null

    # 6. GPU backend
    $backend = 'vulkan'
    $nsmi = $null
    foreach ($p in @("$env:SystemRoot\System32\nvidia-smi.exe",
                     "$env:ProgramFiles\NVIDIA Corporation\NVSMI\nvidia-smi.exe")) {
        if (Test-Path $p) { $nsmi = $p; break }
    }
    if (-not $nsmi -and (Have 'nvidia-smi')) { $nsmi = 'nvidia-smi' }
    if ($nsmi) {
        $old = $ErrorActionPreference
        $ErrorActionPreference = 'SilentlyContinue'
        $null = & $nsmi -L 2>$null
        if ($LASTEXITCODE -eq 0) { $backend = 'cuda' }
        $ErrorActionPreference = $old
    }
    Set-Status 70 ("Setting up $backend backend...")
    $env:BACKEND = $backend
    $env:LEMONADE = $lem
    & "$PSScriptRoot\CudaWin10.bat" | Out-Null
    & $lem backends install "llamacpp:$backend" | Out-Null

    # 7. The model (the long one) - real percent from lemonade's output
    Set-Status 78 "Downloading $model ..."
    $base = 78
    & $lem pull $model 2>&1 | ForEach-Object {
        $line = "$_"
        if ($line -match '(\d{1,3})%') {
            $pct = [math]::Min(99, $base + [int]([int]$matches[1] * 0.21))
            Set-Status $pct "Downloading $model ... $($matches[1])%"
        }
    }
    if ($LASTEXITCODE -ne 0) { throw "Model download failed for $model" }

    Set-Status 100 'DONE'
}
catch {
    Set-Status 0 ("ERROR|" + $_.Exception.Message)
    exit 1
}
exit 0
