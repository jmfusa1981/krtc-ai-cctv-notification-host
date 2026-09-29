param(
    [string]$ProjectRoot = $PSScriptRoot,
    [string]$OutputDirectory = (Join-Path $PSScriptRoot "_release_packages")
)

$ErrorActionPreference = "Stop"
$Version = "V6_6_2"
$VersionLabel = "V6.6.2"
$BuildDate = Get-Date -Format "yyyyMMdd"
$BuildStamp = Get-Date -Format "yyyyMMdd_HHmmss"
$PackageName = "KRTC_NOTIFICATION_HOST_${Version}_AIO_TEST_${BuildStamp}"

function Write-Step([string]$Message) {
    Write-Host "[KRTC AIO BUILD] $Message" -ForegroundColor Cyan
}

$ProjectRoot = (Resolve-Path $ProjectRoot).Path
if (-not (Test-Path (Join-Path $ProjectRoot "manage.py"))) {
    throw "manage.py not found under: $ProjectRoot"
}

$python = Join-Path $ProjectRoot "venv\Scripts\python.exe"
if (-not (Test-Path $python)) { $python = "python" }

$oldPoll = $env:INFERENCE_POLL_AUTOSTART
$oldWs = $env:INFERENCE_WS_AUTOSTART
$oldScheduler = $env:BROADCAST_SCHEDULER_AUTOSTART
$env:INFERENCE_POLL_AUTOSTART = "False"
$env:INFERENCE_WS_AUTOSTART = "False"
$env:BROADCAST_SCHEDULER_AUTOSTART = "False"

Push-Location $ProjectRoot
try {
    Write-Step "Running pre-build validation"
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
    $env:INFERENCE_POLL_AUTOSTART = $oldPoll
    $env:INFERENCE_WS_AUTOSTART = $oldWs
    $env:BROADCAST_SCHEDULER_AUTOSTART = $oldScheduler
}

New-Item -ItemType Directory -Force -Path $OutputDirectory | Out-Null
$tempRoot = Join-Path $env:TEMP $PackageName
$stageRoot = Join-Path $tempRoot "krtc_notification_host_v6"
if (Test-Path $tempRoot) { Remove-Item -Recurse -Force $tempRoot }
New-Item -ItemType Directory -Force -Path $stageRoot | Out-Null

$excludedDirs = @(
    ".git", "venv", ".venv", "media", "logs", "backups", "runtime",
    "staticfiles", "_update_backups", "_release_packages", "__pycache__"
)
$excludedExactFiles = @(".env", "db.sqlite3")
$excludedExtensions = @(".pyc", ".pyo", ".log", ".key", ".sqlite3")

Write-Step "Staging clean AIO source snapshot"
Get-ChildItem -Path $ProjectRoot -Recurse -Force -File | ForEach-Object {
    $relative = $_.FullName.Substring($ProjectRoot.Length) -replace '^[\\/]+', ''
    $segments = $relative -split "[\\/]"
    $skipDir = $false
    foreach ($segment in $segments[0..([Math]::Max(0, $segments.Count - 2))]) {
        if ($excludedDirs -contains $segment -or $segment -like "venv_old_*") { $skipDir = $true; break }
    }
    if ($skipDir) { return }
    if ($excludedExactFiles -contains $_.Name) { return }
    if ($excludedExtensions -contains $_.Extension.ToLowerInvariant()) { return }

    $destination = Join-Path $stageRoot $relative
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $destination) | Out-Null
    Copy-Item -LiteralPath $_.FullName -Destination $destination -Force
}

if (Test-Path (Join-Path $stageRoot ".env")) { throw "Security check failed: .env included" }
if (Test-Path (Join-Path $stageRoot "db.sqlite3")) { throw "Security check failed: db.sqlite3 included" }
if (-not (Test-Path (Join-Path $stageRoot ".env.example"))) { throw ".env.example missing" }

@"
KRTC AI CCTV Notification Host $VersionLabel - AIO TEST PACKAGE
Build time: $(Get-Date -Format "yyyy-MM-dd HH:mm:ss")
Source baseline: 2026-08-26 V6 development snapshot
Recommended local test port: 8010
Recommended LAN/SIT port: 8000 (only when production service is not occupying it)
Persistent AIO root: C:\KRTC\NotificationHost_AIO_Test

This package contains source code only. It intentionally excludes station secrets,
database, media, logs, backups, Git metadata and Python virtual environments.
"@ | Set-Content -Path (Join-Path $stageRoot "AIO_TEST_PACKAGE_INFO.txt") -Encoding UTF8

"$VersionLabel`r`n" | Set-Content -Path (Join-Path $stageRoot "VERSION.txt") -Encoding ASCII
Copy-Item (Join-Path $ProjectRoot "CHANGELOG_V6_6_2_FULL_ADJUSTMENT_20260827.md") (Join-Path $stageRoot "CHANGELOG_THIS_BUILD.md") -Force

$manifestPath = Join-Path $stageRoot "SHA256SUMS.txt"
Get-ChildItem -Path $stageRoot -Recurse -File | Where-Object { $_.FullName -ne $manifestPath } | Sort-Object FullName | ForEach-Object {
    $relative = ($_.FullName.Substring($stageRoot.Length) -replace '^[\\/]+', '') -replace '\\', '/'
    $hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $_.FullName).Hash.ToLowerInvariant()
    "$hash  $relative"
} | Set-Content -Path $manifestPath -Encoding ASCII

$zipPath = Join-Path $OutputDirectory "$PackageName.zip"
if (Test-Path $zipPath) { Remove-Item -Force $zipPath }
Write-Step "Creating AIO ZIP"
Compress-Archive -Path $stageRoot -DestinationPath $zipPath -CompressionLevel Optimal
$zipHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $zipPath).Hash.ToLowerInvariant()
"$zipHash  $(Split-Path -Leaf $zipPath)" | Set-Content -Path "$zipPath.sha256.txt" -Encoding ASCII

Remove-Item -Recurse -Force $tempRoot
Write-Host "AIO package created:" -ForegroundColor Green
Write-Host $zipPath
Write-Host "SHA256: $zipHash"
