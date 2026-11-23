# Run the BattleBit collector: capture the signed-in Steam account's profile
# every N hours and upload it to the site. Reads the token from a local config
# file so it never appears on a command line.
#
# Config: %LOCALAPPDATA%\BBR Stats Ripper\collector.json
#   { "url": "http://127.0.0.1:8099", "token": "bbr_...", "interval_hours": 6 }

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$dataDir = Join-Path $env:LOCALAPPDATA "BBR Stats Ripper"
$configPath = Join-Path $dataDir "collector.json"
$logPath = Join-Path $dataDir "collector.log"

if (-not (Test-Path $configPath)) {
    throw "Collector config not found: $configPath"
}
$config = Get-Content $configPath -Raw | ConvertFrom-Json
if (-not $config.token -or -not $config.url) {
    throw "collector.json needs both url and token."
}
$env:BBR_UPLOAD_URL = [string]$config.url
$env:BBR_UPLOAD_TOKEN = [string]$config.token
$env:PYTHONUNBUFFERED = "1"
$interval = if ($config.interval_hours) { [double]$config.interval_hours } else { 6 }

$exe = Join-Path $root "dist\bbr-ripper-cli.exe"
if (Test-Path $exe) {
    & $exe --watch --quiet --wait-for-steam 600 --interval-hours $interval *>> $logPath
} else {
    Set-Location $root
    $env:PYTHONPATH = Join-Path $root "src"
    & python -m bbr_ripper --watch --quiet --wait-for-steam 600 --interval-hours $interval *>> $logPath
}
