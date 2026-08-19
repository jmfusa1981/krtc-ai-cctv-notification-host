[CmdletBinding()]
param(
    [string]$OutputDirectory = (Join-Path $PSScriptRoot "release_output")
)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path $PSScriptRoot).Path
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$stageRoot = Join-Path ([System.IO.Path]::GetTempPath()) "krtc_v4_release_$timestamp"
$stageProject = Join-Path $stageRoot "krtc_notification_host_v4"
$archivePath = Join-Path $OutputDirectory "krtc_notification_host_v4_clean_$timestamp.zip"

$excludedDirectoryNames = @(
    ".git", ".venv", "venv", "venv_python312_backup", "__pycache__",
    "_update_backups", "logs", "runtime", "media", "staticfiles",
    "release_output", "update_output"
)
$excludedFileNames = @(
    ".env", "db.sqlite3"
)
$excludedExtensions = @(
    ".pyc", ".pyo", ".log", ".sqlite3"
)

try {
    New-Item -ItemType Directory -Force -Path $stageProject | Out-Null
    New-Item -ItemType Directory -Force -Path $OutputDirectory | Out-Null

    Get-ChildItem -LiteralPath $projectRoot -Recurse -Force -File | ForEach-Object {
        $relativePath = $_.FullName.Substring($projectRoot.Length).TrimStart("\")
        $parts = $relativePath -split "[\\/]"
        if ($parts | Where-Object { $excludedDirectoryNames -contains $_ }) {
            return
        }
        if ($excludedFileNames -contains $_.Name) {
            return
        }
        if ($excludedExtensions -contains $_.Extension.ToLowerInvariant()) {
            return
        }

        $destination = Join-Path $stageProject $relativePath
        New-Item -ItemType Directory -Force -Path (Split-Path $destination) | Out-Null
        Copy-Item -LiteralPath $_.FullName -Destination $destination -Force
    }

    if (-not (Test-Path (Join-Path $stageProject ".env.example"))) {
        throw ".env.example is required for a clean release."
    }
    if (Test-Path (Join-Path $stageProject ".env")) {
        throw "Release safety check failed: .env was included."
    }
    if (Test-Path (Join-Path $stageProject "db.sqlite3")) {
        throw "Release safety check failed: db.sqlite3 was included."
    }

    Compress-Archive -Path (Join-Path $stageRoot "*") -DestinationPath $archivePath -CompressionLevel Optimal
    Write-Host "Clean release created: $archivePath" -ForegroundColor Green
}
finally {
    if (Test-Path $stageRoot) {
        Remove-Item -LiteralPath $stageRoot -Recurse -Force
    }
}
