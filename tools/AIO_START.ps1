param(
    [string]$ProjectRoot = (Split-Path -Parent $PSScriptRoot),
    [string]$PersistentRoot = "C:\KRTC\NotificationHost_AIO_Test",
    [int]$Port = 8010,
    [switch]$Lan
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path $ProjectRoot).Path
$python = Join-Path $ProjectRoot "venv\Scripts\python.exe"
if (-not (Test-Path $python)) { throw "AIO venv not found. Run tools\AIO_SETUP.ps1 first." }

$env:KRTC_PERSISTENT_ROOT = $PersistentRoot
$bind = if ($Lan) { "0.0.0.0:$Port" } else { "127.0.0.1:$Port" }

Push-Location $ProjectRoot
try {
    Write-Host "Starting KRTC PAO V6.6.2 AIO test host on $bind" -ForegroundColor Green
    Write-Host "Persistent root: $PersistentRoot"
    & $python manage.py runserver $bind
}
finally {
    Pop-Location
}
