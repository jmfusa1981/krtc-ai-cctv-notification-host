param(
    [string]$ProjectRoot = (Split-Path -Parent $PSScriptRoot),
    [string]$PersistentRoot = "C:\KRTC\NotificationHost_AIO_Test",
    [int]$Port = 8010
)

$ErrorActionPreference = "Stop"

function Write-Step([string]$Message) {
    Write-Host "[KRTC AIO SETUP] $Message" -ForegroundColor Cyan
}

$ProjectRoot = (Resolve-Path $ProjectRoot).Path
if (-not (Test-Path (Join-Path $ProjectRoot "manage.py"))) {
    throw "manage.py not found under: $ProjectRoot"
}

$venvPython = Join-Path $ProjectRoot "venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    Write-Step "Creating virtual environment"
    python -m venv (Join-Path $ProjectRoot "venv")
}

$venvPython = Join-Path $ProjectRoot "venv\Scripts\python.exe"
Write-Step "Installing Python dependencies"
& $venvPython -m pip install --upgrade pip
& $venvPython -m pip install -r (Join-Path $ProjectRoot "requirements.txt")

$configDir = Join-Path $PersistentRoot "config"
$dataDir = Join-Path $PersistentRoot "data"
$mediaDir = Join-Path $PersistentRoot "media"
$logsDir = Join-Path $PersistentRoot "logs"
$backupDir = Join-Path $PersistentRoot "backups"
foreach ($dir in @($configDir, $dataDir, $mediaDir, $logsDir, $backupDir)) {
    New-Item -ItemType Directory -Force -Path $dir | Out-Null
}

$envFile = Join-Path $configDir ".env"
if (-not (Test-Path $envFile)) {
    Write-Step "Creating safe AIO persistent configuration"
    $rng = New-Object System.Security.Cryptography.RNGCryptoServiceProvider
    $bytes = New-Object byte[] 48
    $rng.GetBytes($bytes)
    $rng.Dispose()
    $secret = [Convert]::ToBase64String($bytes)

    @"
DJANGO_SECRET_KEY=$secret
DJANGO_DEBUG=True
DJANGO_ALLOWED_HOSTS=127.0.0.1,localhost,0.0.0.0
KRTC_APP_VERSION=PAO-V6.6.2-AIO
BROADCAST_PLAYBACK_MODE=simulation
INFERENCE_POLL_AUTOSTART=True
INFERENCE_WS_AUTOSTART=True
BROADCAST_SCHEDULER_AUTOSTART=True
"@ | Set-Content -Path $envFile -Encoding UTF8
}

$env:KRTC_PERSISTENT_ROOT = $PersistentRoot
$env:DJANGO_SETTINGS_MODULE = "config.settings"
$env:INFERENCE_POLL_AUTOSTART = "False"
$env:INFERENCE_WS_AUTOSTART = "False"
$env:BROADCAST_SCHEDULER_AUTOSTART = "False"

Push-Location $ProjectRoot
try {
    Write-Step "Applying database migrations"
    & $venvPython manage.py migrate
    Write-Step "Collecting static files"
    & $venvPython manage.py collectstatic --noinput
    Write-Step "Running Django system check"
    & $venvPython manage.py check
    Write-Step "Checking migration drift"
    & $venvPython manage.py makemigrations --check --dry-run
}
finally {
    Pop-Location
}

Write-Host ""
Write-Host "AIO setup complete." -ForegroundColor Green
Write-Host "Persistent root: $PersistentRoot"
Write-Host "Recommended test URL: http://127.0.0.1:$Port/"
Write-Host "Run tools\AIO_START.ps1 to start the AIO test host."
