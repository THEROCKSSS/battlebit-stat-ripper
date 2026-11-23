# Remove the BattleBit Stat Ripper scheduled task.
#   .\scripts\uninstall_startup_task.ps1

param([string]$TaskName = "BattleBit Stat Ripper")

$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if (-not $task) {
    Write-Host "Task '$TaskName' is not installed."
    exit 0
}
Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
Write-Host "Removed scheduled task '$TaskName'."
