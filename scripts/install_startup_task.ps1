# Install a per-user scheduled task that rips the signed-in Steam account's
# BattleBit profile at logon and every N hours.  Run from a normal PowerShell
# window (no administrator required).
#
#   .\scripts\install_startup_task.ps1
#   .\scripts\install_startup_task.ps1 -Hours 3 -RunNow
#
# Remove it with scripts\uninstall_startup_task.ps1

param(
    [int]$Hours = 6,
    [string]$TaskName = "BattleBit Stat Ripper",
    [string]$ExePath = "",
    [switch]$RunNow
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
if (-not $ExePath) {
    $ExePath = Join-Path $root "dist\bbr-ripper-cli.exe"
}
if (-not (Test-Path $ExePath)) {
    throw "CLI not found: $ExePath. Build it with build\build.ps1 first."
}

$documents = [Environment]::GetFolderPath("MyDocuments")
$outDir = Join-Path $documents "BattleBit Stats Ripper"
New-Item -ItemType Directory -Force -Path $outDir | Out-Null

$arguments = "--quiet --wait-for-steam 300 --out `"$outDir`""
$action = New-ScheduledTaskAction -Execute $ExePath -Argument $arguments -WorkingDirectory $root

# At logon, plus a repeating trigger.  The CLI waits up to 5 minutes for Steam.
$logon = New-ScheduledTaskTrigger -AtLogOn
$repeat = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(2) `
    -RepetitionInterval (New-TimeSpan -Hours $Hours) `
    -RepetitionDuration ([TimeSpan]::FromDays(3650))

$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 15) `
    -Hidden

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger @($logon, $repeat) `
    -Settings $settings `
    -Description "Captures the signed-in Steam user's own BattleBit profile and appends it to local history." `
    -Force | Out-Null

Write-Host "Installed scheduled task '$TaskName'."
Write-Host "  exe:    $ExePath"
Write-Host "  output: $outDir"
Write-Host "  every:  $Hours hours + at logon"
Write-Host "  logs:   $env:LOCALAPPDATA\BBR Stats Ripper\logs"

if ($RunNow) {
    Start-ScheduledTask -TaskName $TaskName
    Write-Host "Started the task now."
}
