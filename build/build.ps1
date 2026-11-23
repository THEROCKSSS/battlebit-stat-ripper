# Build the Windows executables and a release zip.
# Run from PowerShell:  .\build\build.ps1

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

if (-not (Test-Path "buildvenv\Scripts\python.exe")) {
    uv venv --python 3.11 buildvenv
    uv pip install --python buildvenv\Scripts\python.exe pyinstaller
}

Write-Host "Building GUI..."
.\buildvenv\Scripts\pyinstaller.exe --noconfirm --clean --onefile --windowed `
    --name BattleBitStatRipper --paths src --distpath dist `
    --workpath build\work --specpath build run_gui.py | Out-Null

Write-Host "Building CLI..."
.\buildvenv\Scripts\pyinstaller.exe --noconfirm --clean --onefile --console `
    --name bbr-ripper-cli --paths src --distpath dist `
    --workpath build\work-cli --specpath build run_cli.py | Out-Null

$stage = "build\release"
if (Test-Path $stage) { Remove-Item $stage -Recurse -Force }
New-Item -ItemType Directory -Path $stage | Out-Null
Copy-Item "dist\BattleBitStatRipper.exe" $stage
Copy-Item "dist\bbr-ripper-cli.exe" $stage
Copy-Item "README.md" $stage
Copy-Item "LICENSE" $stage
New-Item -ItemType Directory -Path "$stage\docs" | Out-Null
Copy-Item "docs\PRIVACY.md" "$stage\docs"
Copy-Item "docs\FORMAT.md" "$stage\docs"
Copy-Item "docs\REPLICATION.md" "$stage\docs"
Copy-Item "docs\TROUBLESHOOTING.md" "$stage\docs"

$zip = "dist\BattleBitStatRipper-windows-x64.zip"
if (Test-Path $zip) { Remove-Item $zip -Force }
Compress-Archive -Path "$stage\*" -DestinationPath $zip

Get-ChildItem dist | Select-Object Name, Length
Write-Host "Release zip: $zip"
