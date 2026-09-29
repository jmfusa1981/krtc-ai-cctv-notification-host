$ErrorActionPreference = "Stop"

# ============================================================
# KRTC Notification Host V3
# Broadcast / IP Speaker feature review package exporter
# ============================================================

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$TimeStamp = Get-Date -Format "yyyyMMdd_HHmmss"

$ExportName = "KRTC_V3_BROADCAST_REVIEW_$TimeStamp"
$ExportRoot = Join-Path $ProjectRoot $ExportName
$ZipPath = Join-Path $ProjectRoot "$ExportName.zip"

Write-Host ""
Write-Host "============================================"
Write-Host "KRTC Broadcast Review Export"
Write-Host "============================================"
Write-Host "Project : $ProjectRoot"
Write-Host "Output  : $ExportRoot"
Write-Host "ZIP     : $ZipPath"
Write-Host ""

if (Test-Path $ExportRoot) {
    Remove-Item $ExportRoot -Recurse -Force
}

New-Item -ItemType Directory -Path $ExportRoot -Force | Out-Null

# ------------------------------------------------------------
# Files specifically required for functional review
# ------------------------------------------------------------

$RequestedFiles = @(
    # Django project configuration
    "manage.py",
    "requirements.txt",
    ".gitignore",
    ".env.example",

    "config\settings.py",
    "config\urls.py",
    "config\asgi.py",
    "config\wsgi.py",

    # Notification / broadcasting backend
    "apps\notifications\__init__.py",
    "apps\notifications\apps.py",
    "apps\notifications\models.py",
    "apps\notifications\admin.py",
    "apps\notifications\forms.py",
    "apps\notifications\views.py",
    "apps\notifications\urls.py",
    "apps\notifications\services.py",
    "apps\notifications\consumers.py",
    "apps\notifications\routing.py",

    # PJSIP backend
    "apps\notifications\backends\__init__.py",
    "apps\notifications\backends\pjsip.py",

    # Dashboard routing and settings pages
    "apps\dashboard\models.py",
    "apps\dashboard\forms.py",
    "apps\dashboard\views.py",
    "apps\dashboard\urls.py",

    # Broadcast and settings templates
    "templates\dashboard\station_broadcast.html",
    "templates\dashboard\system_settings.html",
    "templates\dashboard\settings.html",
    "templates\dashboard\base.html",

    # JavaScript
    "static\js\station_broadcast.js",
    "static\js\system_settings.js",
    "static\js\settings.js",

    # Optional startup scripts for comparison
    "ENABLE_PJSIP_MODE.ps1"
)

$CopiedFiles = New-Object System.Collections.Generic.List[string]
$MissingFiles = New-Object System.Collections.Generic.List[string]

function Copy-ReviewFile {
    param(
        [Parameter(Mandatory = $true)]
        [string]$RelativePath
    )

    $SourcePath = Join-Path $ProjectRoot $RelativePath

    if (-not (Test-Path $SourcePath -PathType Leaf)) {
        $MissingFiles.Add($RelativePath)
        return
    }

    $DestinationPath = Join-Path $ExportRoot $RelativePath
    $DestinationDirectory = Split-Path -Parent $DestinationPath

    if (-not (Test-Path $DestinationDirectory)) {
        New-Item `
            -ItemType Directory `
            -Path $DestinationDirectory `
            -Force | Out-Null
    }

    Copy-Item `
        -Path $SourcePath `
        -Destination $DestinationPath `
        -Force

    $CopiedFiles.Add($RelativePath)
    Write-Host "[COPIED] $RelativePath"
}

foreach ($RelativePath in $RequestedFiles) {
    Copy-ReviewFile -RelativePath $RelativePath
}

# ------------------------------------------------------------
# Copy full relevant directories when present
# ------------------------------------------------------------

$RequestedDirectories = @(
    "apps\notifications\management\commands",
    "apps\notifications\migrations",
    "apps\notifications\backends",

    "templates\notifications",
    "static\notifications",

    "apps\dashboard\migrations"
)

foreach ($RelativeDirectory in $RequestedDirectories) {
    $SourceDirectory = Join-Path $ProjectRoot $RelativeDirectory

    if (-not (Test-Path $SourceDirectory -PathType Container)) {
        Write-Host "[MISSING DIRECTORY] $RelativeDirectory"
        continue
    }

    $Files = Get-ChildItem `
        -Path $SourceDirectory `
        -Recurse `
        -File |
        Where-Object {
            $_.FullName -notmatch "\\__pycache__\\" -and
            $_.Extension -ne ".pyc"
        }

    foreach ($File in $Files) {
        $RelativePath = $File.FullName.Substring(
            $ProjectRoot.Length
        ).TrimStart("\", "/")

        Copy-ReviewFile -RelativePath $RelativePath
    }
}

# ------------------------------------------------------------
# Search for additional files related to requirements 6.1-6.6
# ------------------------------------------------------------

$SearchRoots = @(
    "apps",
    "templates",
    "static",
    "config"
)

$SearchPatterns = @(
    "speaker",
    "broadcast",
    "pjsip",
    "pjsua",
    "sip",
    "rtp",
    "codec",
    "pcmu",
    "pcma",
    "g711",
    "g726",
    "microphone",
    "push.to.talk",
    "getUserMedia",
    "MediaRecorder",
    "AudioContext",
    "schedule",
    "scheduled",
    "recurrence",
    "dhcp",
    "static_ip",
    "network_mode"
)

$TextExtensions = @(
    ".py",
    ".html",
    ".js",
    ".css",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".ini",
    ".txt",
    ".md",
    ".ps1"
)

Write-Host ""
Write-Host "Searching for additional broadcast-related files..."

foreach ($SearchRoot in $SearchRoots) {
    $AbsoluteSearchRoot = Join-Path $ProjectRoot $SearchRoot

    if (-not (Test-Path $AbsoluteSearchRoot -PathType Container)) {
        continue
    }

    $CandidateFiles = Get-ChildItem `
        -Path $AbsoluteSearchRoot `
        -Recurse `
        -File |
        Where-Object {
            $TextExtensions -contains $_.Extension.ToLower() -and
            $_.FullName -notmatch "\\__pycache__\\" -and
            $_.FullName -notmatch "\\migrations\\.*\.pyc$"
        }

    foreach ($CandidateFile in $CandidateFiles) {
        $Matched = $false

        foreach ($Pattern in $SearchPatterns) {
            $MatchResult = Select-String `
                -Path $CandidateFile.FullName `
                -Pattern $Pattern `
                -CaseSensitive:$false `
                -Quiet `
                -ErrorAction SilentlyContinue

            if ($MatchResult) {
                $Matched = $true
                break
            }
        }

        if (-not $Matched) {
            continue
        }

        $RelativePath = $CandidateFile.FullName.Substring(
            $ProjectRoot.Length
        ).TrimStart("\", "/")

        if (-not $CopiedFiles.Contains($RelativePath)) {
            Copy-ReviewFile -RelativePath $RelativePath
        }
    }
}

# ------------------------------------------------------------
# Generate safe environment configuration summary
# Does not export the actual .env file.
# ------------------------------------------------------------

$EnvironmentSummaryPath = Join-Path `
    $ExportRoot `
    "REVIEW_ENVIRONMENT_SUMMARY.txt"

$PythonVersion = "Unavailable"
$DjangoVersion = "Unavailable"

try {
    $PythonVersion = & `
        (Join-Path $ProjectRoot "venv\Scripts\python.exe") `
        --version 2>&1
}
catch {
    $PythonVersion = "Unable to read Python version: $($_.Exception.Message)"
}

try {
    $DjangoVersion = & `
        (Join-Path $ProjectRoot "venv\Scripts\python.exe") `
        -m django --version 2>&1
}
catch {
    $DjangoVersion = "Unable to read Django version: $($_.Exception.Message)"
}

$EnvironmentSummary = @"
KRTC V3 BROADCAST REVIEW ENVIRONMENT
Generated: $(Get-Date -Format "yyyy-MM-dd HH:mm:ss")

Project root:
$ProjectRoot

Python:
$PythonVersion

Django:
$DjangoVersion

Expected runtime settings:
BROADCAST_PLAYBACK_MODE=pjsip
PJSIP_EXECUTABLE_PATH=C:\krtc-tools\pjsip\pjsua.exe
PJSIP_LOCAL_IP=192.168.6.25
PJSIP_ADVERTISE_IP=192.168.6.25

Security exclusions:
- Actual .env was not exported.
- SQLite database was not exported.
- Media audio files were not exported.
- Runtime logs were not exported.
- Virtual environment was not exported.

Known tested function:
- PJSUA executable starts successfully.
- SIP call confirmation succeeded.
- PCMU/G.711 media became active.
- Call disconnected normally.
- PJSUA return code was 0.
"@

Set-Content `
    -Path $EnvironmentSummaryPath `
    -Value $EnvironmentSummary `
    -Encoding UTF8

# ------------------------------------------------------------
# Export Django model schema using introspection commands
# No database rows are included.
# ------------------------------------------------------------

$ModelSummaryPath = Join-Path `
    $ExportRoot `
    "DJANGO_MODEL_SCHEMA.txt"

$ModelSummaryScript = @'
from django.apps import apps

target_models = [
    "SpeakerDevice",
    "AudioFile",
    "BroadcastRule",
    "BroadcastLog",
    "BroadcastSchedule",
    "ScheduledBroadcast",
]

print("DJANGO MODEL FIELD SUMMARY")
print("=" * 80)

found = False

for model in apps.get_models():
    if (
        model.__name__ in target_models
        or "speaker" in model.__name__.lower()
        or "broadcast" in model.__name__.lower()
        or "audio" in model.__name__.lower()
    ):
        found = True
        print()
        print(f"MODEL: {model._meta.label}")
        print("-" * 80)

        for field in model._meta.get_fields():
            field_type = type(field).__name__
            print(
                f"{field.name:30} "
                f"{field_type:25} "
                f"null={getattr(field, 'null', '')} "
                f"blank={getattr(field, 'blank', '')}"
            )

if not found:
    print("No speaker, broadcast, or audio models were found.")
'@

$TemporarySchemaScript = Join-Path `
    $ProjectRoot `
    "_temporary_export_model_schema.py"

try {
    Set-Content `
        -Path $TemporarySchemaScript `
        -Value $ModelSummaryScript `
        -Encoding UTF8

    $PythonExecutable = Join-Path `
        $ProjectRoot `
        "venv\Scripts\python.exe"

    if (Test-Path $PythonExecutable) {
        $SchemaOutput = Get-Content $TemporarySchemaScript -Raw |
            & $PythonExecutable manage.py shell 2>&1

        Set-Content `
            -Path $ModelSummaryPath `
            -Value $SchemaOutput `
            -Encoding UTF8
    }
    else {
        Set-Content `
            -Path $ModelSummaryPath `
            -Value "Venv Python executable was not found." `
            -Encoding UTF8
    }
}
catch {
    Set-Content `
        -Path $ModelSummaryPath `
        -Value "Unable to export model schema: $($_.Exception.Message)" `
        -Encoding UTF8
}
finally {
    if (Test-Path $TemporarySchemaScript) {
        Remove-Item $TemporarySchemaScript -Force
    }
}

# ------------------------------------------------------------
# Run Django system check and save result
# ------------------------------------------------------------

$DjangoCheckPath = Join-Path `
    $ExportRoot `
    "DJANGO_CHECK_RESULT.txt"

try {
    $PythonExecutable = Join-Path `
        $ProjectRoot `
        "venv\Scripts\python.exe"

    if (Test-Path $PythonExecutable) {
        $CheckOutput = & `
            $PythonExecutable `
            manage.py check 2>&1

        Set-Content `
            -Path $DjangoCheckPath `
            -Value $CheckOutput `
            -Encoding UTF8
    }
}
catch {
    Set-Content `
        -Path $DjangoCheckPath `
        -Value "Django check failed: $($_.Exception.Message)" `
        -Encoding UTF8
}

# ------------------------------------------------------------
# Generate package manifest
# ------------------------------------------------------------

$ManifestPath = Join-Path $ExportRoot "FILE_MANIFEST.txt"

$ManifestLines = New-Object System.Collections.Generic.List[string]

$ManifestLines.Add("KRTC V3 BROADCAST REVIEW PACKAGE")
$ManifestLines.Add("Generated: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')")
$ManifestLines.Add("")
$ManifestLines.Add("COPIED FILES")
$ManifestLines.Add("=" * 80)

foreach ($File in ($CopiedFiles | Sort-Object -Unique)) {
    $ManifestLines.Add($File)
}

$ManifestLines.Add("")
$ManifestLines.Add("OPTIONAL FILES NOT FOUND")
$ManifestLines.Add("=" * 80)

foreach ($File in ($MissingFiles | Sort-Object -Unique)) {
    $ManifestLines.Add($File)
}

$ManifestLines.Add("")
$ManifestLines.Add("EXCLUDED")
$ManifestLines.Add("=" * 80)
$ManifestLines.Add(".env")
$ManifestLines.Add("db.sqlite3")
$ManifestLines.Add("venv/")
$ManifestLines.Add("media/")
$ManifestLines.Add("logs/")
$ManifestLines.Add(".git/")
$ManifestLines.Add("__pycache__/")
$ManifestLines.Add("*.pyc")

Set-Content `
    -Path $ManifestPath `
    -Value $ManifestLines `
    -Encoding UTF8

# ------------------------------------------------------------
# Compress package
# ------------------------------------------------------------

if (Test-Path $ZipPath) {
    Remove-Item $ZipPath -Force
}

Compress-Archive `
    -Path "$ExportRoot\*" `
    -DestinationPath $ZipPath `
    -CompressionLevel Optimal `
    -Force

# ------------------------------------------------------------
# Final verification
# ------------------------------------------------------------

if (-not (Test-Path $ZipPath)) {
    throw "ZIP package creation failed."
}

$ZipInfo = Get-Item $ZipPath
$SizeMB = [math]::Round($ZipInfo.Length / 1MB, 2)

Write-Host ""
Write-Host "============================================"
Write-Host "EXPORT COMPLETED"
Write-Host "============================================"
Write-Host "Copied files : $($CopiedFiles.Count)"
Write-Host "Missing files: $($MissingFiles.Count)"
Write-Host "ZIP size     : $SizeMB MB"
Write-Host "ZIP path     : $ZipPath"
Write-Host ""
Write-Host "Please upload this ZIP file for review."