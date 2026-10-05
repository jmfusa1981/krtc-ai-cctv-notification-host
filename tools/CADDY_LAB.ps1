param(
    [ValidateSet("Validate", "Run", "Reload", "Stop", "Trust")]
    [string]$Action = "Validate",
    [string]$CaddyExe = "C:\KRTC\NotificationHost\caddy\caddy.exe",
    [string]$ConfigPath = (Join-Path (Split-Path -Parent $PSScriptRoot) "service\Caddyfile"),
    [string]$PersistentRoot = "C:\KRTC\NotificationHost",
    [string]$Site = "https://localhost"
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path -LiteralPath $CaddyExe -PathType Leaf)) {
    throw "找不到 Caddy 執行檔：$CaddyExe"
}

if (-not (Test-Path -LiteralPath $ConfigPath -PathType Leaf)) {
    throw "找不到 Caddyfile：$ConfigPath"
}

$env:KRTC_TLS_SITE = $Site
$env:KRTC_CADDY_LOG_PATH = Join-Path $PersistentRoot "logs\caddy\access.log"
$env:XDG_DATA_HOME = Join-Path $PersistentRoot "caddy\data"
$env:XDG_CONFIG_HOME = Join-Path $PersistentRoot "caddy\config"

foreach ($directory in @(
    (Split-Path -Parent $env:KRTC_CADDY_LOG_PATH),
    $env:XDG_DATA_HOME,
    $env:XDG_CONFIG_HOME
)) {
    New-Item -ItemType Directory -Force -Path $directory | Out-Null
}

switch ($Action) {
    "Validate" {
        & $CaddyExe validate --config $ConfigPath --adapter caddyfile
    }
    "Run" {
        & $CaddyExe run --config $ConfigPath --adapter caddyfile
    }
    "Reload" {
        & $CaddyExe reload --config $ConfigPath --adapter caddyfile
    }
    "Stop" {
        & $CaddyExe stop
    }
    "Trust" {
        & $CaddyExe trust
    }
}

if ($LASTEXITCODE -ne 0) {
    throw "Caddy 動作失敗：Action=$Action, ExitCode=$LASTEXITCODE"
}
