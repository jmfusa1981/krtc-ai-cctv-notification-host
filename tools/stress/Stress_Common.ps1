Set-StrictMode -Version Latest

function Get-StressProjectRoot {
    return (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
}

function Get-StressRuntimeDirectory {
    return Join-Path (Get-StressProjectRoot) "runtime\stress"
}

function Get-StressStatePath {
    return Join-Path (Get-StressRuntimeDirectory) "stress_processes.json"
}

function Get-StressStopRequestPath {
    return Join-Path (Get-StressRuntimeDirectory) "stop.request"
}

function Write-StressWarning {
    param([string]$Message)

    Write-Warning $Message
}

function ConvertTo-NormalizedStressRecord {
    param($Record)

    if ($null -eq $Record -or $Record -is [System.Array]) {
        Write-StressWarning "Skipped invalid stress process record: expected one object."
        return $null
    }
    $propertyNames = @($Record.PSObject.Properties.Name)
    foreach ($requiredProperty in @("ProcessId", "Path", "SourceCamera", "ProcessStartedAt", "StartedAt")) {
        if ($propertyNames -notcontains $requiredProperty) {
            Write-StressWarning ("Skipped invalid stress process record: missing {0}." -f $requiredProperty)
            return $null
        }
    }

    $processId = 0
    if (
        -not [int]::TryParse([string]$Record.ProcessId, [ref]$processId) -or
        $processId -le 0
    ) {
        Write-StressWarning "Skipped invalid stress process record: ProcessId must be a positive integer."
        return $null
    }
    if ([string]$Record.Path -notmatch '^stress(0[1-9]|1[0-6])$') {
        Write-StressWarning "Skipped invalid stress process record: Path is outside the stress namespace."
        return $null
    }
    if ([string]$Record.SourceCamera -notmatch '^CAM-[0-9]{3}$') {
        Write-StressWarning "Skipped invalid stress process record: SourceCamera is invalid."
        return $null
    }

    $processStartedAt = [DateTime]::MinValue
    $startedAt = [DateTime]::MinValue
    if (-not [DateTime]::TryParse([string]$Record.ProcessStartedAt, [ref]$processStartedAt)) {
        Write-StressWarning "Skipped invalid stress process record: ProcessStartedAt is invalid."
        return $null
    }
    if (-not [DateTime]::TryParse([string]$Record.StartedAt, [ref]$startedAt)) {
        Write-StressWarning "Skipped invalid stress process record: StartedAt is invalid."
        return $null
    }

    $processName = if (
        $propertyNames -contains "ProcessName" -and
        -not [string]::IsNullOrWhiteSpace([string]$Record.ProcessName)
    ) {
        [string]$Record.ProcessName
    } else {
        "ffmpeg"
    }
    if ($processName -ne "ffmpeg") {
        Write-StressWarning "Skipped invalid stress process record: ProcessName must be ffmpeg."
        return $null
    }

    $normalized = [ordered]@{}
    foreach ($property in $Record.PSObject.Properties) {
        $normalized[$property.Name] = $property.Value
    }
    $normalized["SchemaVersion"] = 1
    $normalized["ProcessName"] = "ffmpeg"
    $normalized["ProcessId"] = $processId
    $normalized["ProcessStartedAt"] = $processStartedAt.ToUniversalTime().ToString("o")
    $normalized["StartedAt"] = $startedAt.ToUniversalTime().ToString("o")
    return [pscustomobject]$normalized
}

function Read-StressState {
    $statePath = Get-StressStatePath
    if (-not (Test-Path -LiteralPath $statePath -PathType Leaf)) {
        return @()
    }
    try {
        $payload = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
        foreach ($record in @($payload)) {
            $normalizedRecord = ConvertTo-NormalizedStressRecord -Record $record
            if ($null -ne $normalizedRecord) {
                Write-Output $normalizedRecord
            }
        }
    } catch {
        Write-StressWarning ("Unable to read stress process state: {0}" -f $_.Exception.Message)
        return @()
    }
}

function Remove-StaleStressTempFiles {
    param([int]$MinimumAgeSeconds = 60)

    $runtimeDirectory = Get-StressRuntimeDirectory
    if (-not (Test-Path -LiteralPath $runtimeDirectory -PathType Container)) {
        return
    }
    $cutoff = (Get-Date).AddSeconds(-1 * [Math]::Max(0, $MinimumAgeSeconds))
    foreach ($item in (Get-ChildItem -LiteralPath $runtimeDirectory -File -ErrorAction SilentlyContinue)) {
        if (
            $item.Name -notmatch '^\.?stress_processes\.json\.[0-9a-f-]+\.tmp$' -and
            $item.Name -notmatch '^\.browser_state\.json\.[0-9a-f-]+\.tmp$' -and
            $item.Name -ne 'stress_processes.json.tmp'
        ) {
            continue
        }
        if ($item.LastWriteTime -gt $cutoff) {
            continue
        }
        Remove-Item -LiteralPath $item.FullName -Force -ErrorAction SilentlyContinue
    }
}

function Resolve-StressRuntimeFilePath {
    param(
        $Path,
        [string]$ParameterName
    )

    if ($null -eq $Path -or $Path -is [System.Array]) {
        throw ("{0} must be one scalar filesystem path." -f $ParameterName)
    }
    $pathValue = [string]$Path
    if ([string]::IsNullOrWhiteSpace($pathValue)) {
        throw ("{0} must not be empty." -f $ParameterName)
    }

    $runtimeDirectoryValue = Get-StressRuntimeDirectory
    if (
        $null -eq $runtimeDirectoryValue -or
        $runtimeDirectoryValue -is [System.Array] -or
        [string]::IsNullOrWhiteSpace([string]$runtimeDirectoryValue)
    ) {
        throw "Stress runtime directory must be one non-empty scalar filesystem path."
    }

    $runtimeDirectory = [System.IO.Path]::GetFullPath([string]$runtimeDirectoryValue).TrimEnd(
        [System.IO.Path]::DirectorySeparatorChar,
        [System.IO.Path]::AltDirectorySeparatorChar
    )
    $fullPath = [System.IO.Path]::GetFullPath($pathValue)
    $parentDirectory = [System.IO.Path]::GetDirectoryName($fullPath).TrimEnd(
        [System.IO.Path]::DirectorySeparatorChar,
        [System.IO.Path]::AltDirectorySeparatorChar
    )
    if (-not [string]::Equals(
        $parentDirectory,
        $runtimeDirectory,
        [System.StringComparison]::OrdinalIgnoreCase
    )) {
        throw ("{0} must be directly inside the stress runtime directory." -f $ParameterName)
    }
    return $fullPath
}

function Write-StressState {
    param([array]$Records)

    $runtimeDirectoryValue = Get-StressRuntimeDirectory
    if ($null -eq $runtimeDirectoryValue -or $runtimeDirectoryValue -is [System.Array]) {
        throw "Stress runtime directory must be one scalar filesystem path."
    }
    $runtimeDirectory = [System.IO.Path]::GetFullPath([string]$runtimeDirectoryValue)
    New-Item -ItemType Directory -Path $runtimeDirectory -Force | Out-Null
    $statePath = Resolve-StressRuntimeFilePath -Path (Get-StressStatePath) -ParameterName "StatePath"
    $temporaryPath = Resolve-StressRuntimeFilePath -Path (Join-Path $runtimeDirectory (
        ".stress_processes.json.{0}.tmp" -f [Guid]::NewGuid().ToString("N")
    )) -ParameterName "TemporaryPath"
    $backupPath = Resolve-StressRuntimeFilePath -Path (Join-Path $runtimeDirectory (
        ".stress_processes.json.{0}.bak" -f [Guid]::NewGuid().ToString("N")
    )) -ParameterName "BackupPath"
    $normalizedRecords = @()
    foreach ($record in @($Records)) {
        $normalizedRecord = ConvertTo-NormalizedStressRecord -Record $record
        if ($null -ne $normalizedRecord) {
            $normalizedRecords += $normalizedRecord
        }
    }
    try {
        $json = ConvertTo-Json -InputObject @($normalizedRecords) -Depth 4
        Set-Content -LiteralPath $temporaryPath -Value $json -Encoding ascii
        if (Test-Path -LiteralPath $statePath -PathType Leaf) {
            [System.IO.File]::Replace($temporaryPath, $statePath, $backupPath, $true)
            if (Test-Path -LiteralPath $backupPath -PathType Leaf) {
                Remove-Item -LiteralPath $backupPath -Force
            }
        } else {
            [System.IO.File]::Move($temporaryPath, $statePath)
        }
    } finally {
        if (Test-Path -LiteralPath $temporaryPath -PathType Leaf) {
            Remove-Item -LiteralPath $temporaryPath -Force -ErrorAction SilentlyContinue
        }
    }
}

function Test-StressProcessRecord {
    param($Record)

    if ($null -eq $Record -or $Record -is [System.Array]) {
        Write-StressWarning "Skipped invalid stress process record: Test-StressProcessRecord requires one normalized object."
        return $false
    }
    $propertyNames = @($Record.PSObject.Properties.Name)
    foreach ($requiredProperty in @("ProcessId", "Path", "SourceCamera", "ProcessStartedAt", "StartedAt", "ProcessName")) {
        if ($propertyNames -notcontains $requiredProperty) {
            Write-StressWarning ("Skipped invalid stress process record: missing {0}." -f $requiredProperty)
            return $false
        }
    }
    $processId = 0
    if (
        -not [int]::TryParse([string]$Record.ProcessId, [ref]$processId) -or
        $processId -le 0 -or
        [string]$Record.ProcessName -ne "ffmpeg"
    ) {
        Write-StressWarning "Skipped invalid stress process record: PID or process name is invalid."
        return $false
    }
    $expectedStart = [DateTime]::MinValue
    if (-not [DateTime]::TryParse([string]$Record.ProcessStartedAt, [ref]$expectedStart)) {
        Write-StressWarning "Skipped invalid stress process record: ProcessStartedAt is invalid."
        return $false
    }
    $process = Get-Process -Id $processId -ErrorAction SilentlyContinue
    if (-not $process -or $process.ProcessName -ne [string]$Record.ProcessName) {
        return $false
    }
    $expectedStart = $expectedStart.ToUniversalTime()
    $actualStart = $process.StartTime.ToUniversalTime()
    return [Math]::Abs(($actualStart - $expectedStart).TotalSeconds) -lt 2
}

function Stop-StressProcessRecord {
    param($Record)

    if (-not (Test-StressProcessRecord -Record $Record)) {
        return
    }
    Stop-Process -Id $Record.ProcessId -Force -ErrorAction SilentlyContinue
    Write-Host ("Stopped stress publisher: Path={0} PID={1}" -f $Record.Path, $Record.ProcessId)
}

function Start-StressPublishers {
    param(
        [ValidateSet(9, 16)]
        [int]$Count,
        [string]$FfmpegPath = "C:\Program Files\ffmpeg\bin\ffmpeg.exe"
    )

    Remove-StaleStressTempFiles
    if (-not (Test-Path -LiteralPath $FfmpegPath -PathType Leaf)) {
        throw "ffmpeg.exe not found: $FfmpegPath"
    }
    $username = $env:KRTC_LAB_CAMERA_USERNAME
    $password = $env:KRTC_LAB_CAMERA_PASSWORD
    if ([string]::IsNullOrWhiteSpace($username) -or [string]::IsNullOrWhiteSpace($password)) {
        throw "Set KRTC_LAB_CAMERA_USERNAME and KRTC_LAB_CAMERA_PASSWORD first."
    }

    $projectRoot = Get-StressProjectRoot
    $profilePath = Join-Path $projectRoot "tools\mediamtx\camera_bridge_profiles.lab.psd1"
    $profiles = Import-PowerShellDataFile -LiteralPath $profilePath
    $existingByPath = @{}
    foreach ($record in (Read-StressState)) {
        if (Test-StressProcessRecord -Record $record) {
            $existingByPath[[string]$record.Path] = $record
        }
    }

    $targetPaths = @(1..$Count | ForEach-Object { "stress{0:D2}" -f $_ })
    foreach ($path in @($existingByPath.Keys)) {
        if ($targetPaths -notcontains $path) {
            Stop-StressProcessRecord -Record $existingByPath[$path]
            $existingByPath.Remove($path)
        }
    }

    $encodedUsername = [Uri]::EscapeDataString($username)
    $encodedPassword = [Uri]::EscapeDataString($password)
    foreach ($index in 1..$Count) {
        $path = "stress{0:D2}" -f $index
        if ($existingByPath.ContainsKey($path)) {
            continue
        }
        $sourceIndex = (($index - 1) % 4) + 1
        $cameraCode = "CAM-{0:D3}" -f $sourceIndex
        $profile = $profiles[$cameraCode]
        if (-not $profile -or [string]$profile.SourceCodec -ne "H264") {
            throw "Stress source must be native H264: $cameraCode"
        }
        $sourceUrl = "rtsp://${encodedUsername}:${encodedPassword}@$($profile.Host)/cam1/h264"
        $destinationUrl = "rtsp://127.0.0.1:8554/$path"
        $arguments = @(
            "-hide_banner", "-loglevel", "warning", "-nostats",
            "-fflags", "+genpts", "-use_wallclock_as_timestamps", "1",
            "-rtsp_transport", "tcp", "-i", $sourceUrl,
            "-map", "0:v:0", "-c:v", "copy", "-an", "-dn",
            "-f", "rtsp", "-rtsp_transport", "tcp", $destinationUrl
        )
        $process = Start-Process -FilePath $FfmpegPath -ArgumentList $arguments -PassThru -WindowStyle Hidden
        $record = [ordered]@{
            Path = $path
            SourceCamera = $cameraCode
            SourceCodec = "H264"
            BridgeMode = "copy"
            Destination = $destinationUrl
            ProcessName = "ffmpeg"
            ProcessId = $process.Id
            ProcessStartedAt = $process.StartTime.ToUniversalTime().ToString("o")
            StartedAt = (Get-Date).ToUniversalTime().ToString("o")
        }
        $existingByPath[$path] = [pscustomobject]$record
        Write-StressState -Records @($existingByPath.Values | Sort-Object Path)
        Write-Host ("Started stress publisher: Source={0} Path={1} Mode=copy PID={2}" -f $cameraCode, $path, $process.Id)
    }
    Write-StressState -Records @($existingByPath.Values | Sort-Object Path)
    Write-Host ("Stress publisher target reached: Count={0}" -f $Count)
}

function Stop-AllStressPublishers {
    foreach ($record in (Read-StressState)) {
        Stop-StressProcessRecord -Record $record
    }
    $statePath = Get-StressStatePath
    if (Test-Path -LiteralPath $statePath -PathType Leaf) {
        Remove-Item -LiteralPath $statePath -Force
    }
    $browserStatePath = Join-Path (Get-StressRuntimeDirectory) "browser_state.json"
    if (Test-Path -LiteralPath $browserStatePath -PathType Leaf) {
        Remove-Item -LiteralPath $browserStatePath -Force
    }
    Remove-StaleStressTempFiles -MinimumAgeSeconds 0
}
