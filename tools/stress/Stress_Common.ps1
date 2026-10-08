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

function Read-StressState {
    $statePath = Get-StressStatePath
    if (-not (Test-Path -LiteralPath $statePath -PathType Leaf)) {
        return @()
    }
    try {
        return @(Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json)
    } catch {
        return @()
    }
}

function Write-StressState {
    param([array]$Records)

    $runtimeDirectory = Get-StressRuntimeDirectory
    New-Item -ItemType Directory -Path $runtimeDirectory -Force | Out-Null
    $statePath = Get-StressStatePath
    $temporaryPath = "$statePath.tmp"
    @($Records) | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $temporaryPath -Encoding ascii
    Move-Item -LiteralPath $temporaryPath -Destination $statePath -Force
}

function Test-StressProcessRecord {
    param($Record)

    if (-not $Record -or -not $Record.ProcessId -or -not $Record.ProcessStartedAt) {
        return $false
    }
    $process = Get-Process -Id ([int]$Record.ProcessId) -ErrorAction SilentlyContinue
    if (-not $process -or $process.ProcessName -ne "ffmpeg") {
        return $false
    }
    $expectedStart = [DateTime]::Parse([string]$Record.ProcessStartedAt).ToUniversalTime()
    $actualStart = $process.StartTime.ToUniversalTime()
    return [Math]::Abs(($actualStart - $expectedStart).TotalSeconds) -lt 2
}

function Stop-StressProcessRecord {
    param($Record)

    if (-not (Test-StressProcessRecord -Record $Record)) {
        return
    }
    Stop-Process -Id ([int]$Record.ProcessId) -Force -ErrorAction SilentlyContinue
    Write-Host ("Stopped stress publisher: Path={0} PID={1}" -f $Record.Path, $Record.ProcessId)
}

function Start-StressPublishers {
    param(
        [ValidateSet(9, 16)]
        [int]$Count,
        [string]$FfmpegPath = "C:\Program Files\ffmpeg\bin\ffmpeg.exe"
    )

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
}
