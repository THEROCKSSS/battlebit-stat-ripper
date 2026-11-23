# Serve the BattleBit profile site on loopback. Used by the "BBR Stats Site"
# scheduled task so the site survives reboots and Hermes sessions.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$server = Join-Path $root "server"
$exe = Join-Path $server ".venv\Scripts\waitress-serve.exe"
if (-not (Test-Path $exe)) { throw "waitress not found at $exe" }
[Environment]::SetEnvironmentVariable("BBR_PUBLIC_URL", "https://owens-pc-vpn.tailff2683.ts.net:8552", "Process")
Set-Location $server
& $exe --host=127.0.0.1 --port=8099 app:app
