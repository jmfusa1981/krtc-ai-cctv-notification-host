param(
    [string]$ExecutablePath = "",
    [string]$ConfigPath = ""
)

$ErrorActionPreference = "Stop"

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path

if (-not $ExecutablePath) {
    $ExecutablePath = Join-Path $projectRoot "tools\runtime\mediamtx\mediamtx.exe"
}

if (-not $ConfigPath) {
    $ConfigPath = Join-Path $projectRoot "config\mediamtx.lab.yml"
}

if (-not (Test-Path -LiteralPath $ExecutablePath -PathType Leaf)) {
    throw "MediaMTX executable not found: $ExecutablePath"
}

if (-not (Test-Path -LiteralPath $ConfigPath -PathType Leaf)) {
    throw "MediaMTX config not found: $ConfigPath"
}

Write-Host "MediaMTX LAB: publisher mode configuration loaded."
Write-Host "Camera bridges must publish streams separately."

& $ExecutablePath $ConfigPath

exit $LASTEXITCODE