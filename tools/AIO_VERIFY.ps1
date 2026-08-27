param(
    [string]$ProjectRoot = (Split-Path -Parent $PSScriptRoot),
    [string]$PersistentRoot = "C:\KRTC\NotificationHost_AIO_Test"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path $ProjectRoot).Path
$python = Join-Path $ProjectRoot "venv\Scripts\python.exe"
if (-not (Test-Path $python)) { throw "AIO venv not found. Run tools\AIO_SETUP.ps1 first." }

$env:KRTC_PERSISTENT_ROOT = $PersistentRoot
$env:INFERENCE_POLL_AUTOSTART = "False"
$env:INFERENCE_WS_AUTOSTART = "False"
$env:BROADCAST_SCHEDULER_AUTOSTART = "False"

Push-Location $ProjectRoot
try {
    & $python manage.py check
    if ($LASTEXITCODE -ne 0) { throw "manage.py check failed" }

    & $python manage.py makemigrations --check --dry-run
    if ($LASTEXITCODE -ne 0) { throw "migration drift detected" }

    & $python manage.py test `
        apps.cameras.tests_rtsp_auth `
        apps.dashboard.tests.test_inference_host_summary `
        apps.dashboard.tests.test_v662_dashboard_status `
        apps.settings_app.tests.test_v662_adjustments `
        --verbosity 1
    if ($LASTEXITCODE -ne 0) { throw "V6.6.2 regression tests failed" }

    & $python manage.py test_configuration_backup_foundation
    if ($LASTEXITCODE -ne 0) { throw "configuration backup foundation test failed" }
}
finally {
    Pop-Location
}

Write-Host "KRTC V6.6.2 AIO verification PASSED." -ForegroundColor Green
