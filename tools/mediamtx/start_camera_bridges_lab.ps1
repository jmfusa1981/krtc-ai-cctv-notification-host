param(
    [string[]]$CameraCode = @("all"),
    [string]$FfmpegPath = "C:\Program Files\ffmpeg\bin\ffmpeg.exe",
    [string]$ProfilePath = "",
    [string]$MonitorProfile = "grid4",
    [string]$MonitorProfilePath = "",
    [string]$MonitorProfileStatePath = "",
    [string]$TransitionStatePath = "",
    [string]$TransitionAckPath = "",
    [string]$MediaMtxApiBaseUrl = "http://127.0.0.1:9997",
    [ValidateRange(5, 30)]
    [int]$TransitionTimeoutSeconds = 10,
    [ValidateRange(0, 60)]
    [int]$TranscodeFps = 0,
    [ValidateRange(0, 10)]
    [int]$MaxRestarts = 3,
    [ValidateRange(1, 30)]
    [int]$RestartBaseSeconds = 2
)

$ErrorActionPreference = "Stop"
$bridgeScript = Join-Path $PSScriptRoot "start_camera_bridge_lab.ps1"
$codecResolverScript = Join-Path $PSScriptRoot "camera_bridge_codec.ps1"
if ([string]::IsNullOrWhiteSpace($ProfilePath)) {
    $ProfilePath = Join-Path $PSScriptRoot "camera_bridge_profiles.lab.psd1"
}
if ([string]::IsNullOrWhiteSpace($MonitorProfilePath)) {
    $MonitorProfilePath = Join-Path $PSScriptRoot "../../config/monitor_profiles.json"
}
if ([string]::IsNullOrWhiteSpace($MonitorProfileStatePath)) {
    $MonitorProfileStatePath = Join-Path $PSScriptRoot "../../runtime/mediamtx/monitor_profile.json"
}
if ([string]::IsNullOrWhiteSpace($TransitionStatePath)) {
    $TransitionStatePath = Join-Path $PSScriptRoot "../../runtime/mediamtx/profile_transition.json"
}
if ([string]::IsNullOrWhiteSpace($TransitionAckPath)) {
    $TransitionAckPath = Join-Path $PSScriptRoot "../../runtime/mediamtx/profile_transition_ack.json"
}

if (-not (Test-Path -LiteralPath $bridgeScript -PathType Leaf)) {
    throw "Camera bridge script not found: $bridgeScript"
}
if (-not (Test-Path -LiteralPath $codecResolverScript -PathType Leaf)) {
    throw "Camera bridge codec resolver not found: $codecResolverScript"
}
if (-not (Test-Path -LiteralPath $ProfilePath -PathType Leaf)) {
    throw "Camera bridge profile not found: $ProfilePath"
}
if (-not (Test-Path -LiteralPath $FfmpegPath -PathType Leaf)) {
    throw "ffmpeg.exe not found: $FfmpegPath"
}
$cameraProfiles = Import-PowerShellDataFile -LiteralPath $ProfilePath
. $codecResolverScript
$monitorProfileConfiguration = Import-MonitorProfileConfiguration -Path $MonitorProfilePath
$initialMonitorProfile = Resolve-MonitorProfile `
    -Configuration $monitorProfileConfiguration `
    -Name $MonitorProfile

$requestedCodes = @(
    $CameraCode |
        ForEach-Object { $_.Trim().ToUpperInvariant() } |
        Where-Object { $_ }
)
if ($requestedCodes -contains "ALL") {
    $requestedCodes = @($cameraProfiles.Keys | Sort-Object)
}
$requestedCodes = @($requestedCodes | Select-Object -Unique)
foreach ($code in $requestedCodes) {
    if (-not $cameraProfiles.ContainsKey($code)) {
        throw "Unsupported CameraCode: $code"
    }
}

$powerShellPath = (Get-Process -Id $PID).Path
$bridges = @()
$activeMonitorProfile = $initialMonitorProfile.Name
$activeRequestId = "startup"

function Invoke-BridgeRuntimeReconciliation {
    $statusDirectory = Join-Path $PSScriptRoot "../../runtime/mediamtx/bridges"
    if (-not (Test-Path -LiteralPath $statusDirectory -PathType Container)) {
        return
    }
    foreach ($statusFile in Get-ChildItem -LiteralPath $statusDirectory -Filter "*.json" -File) {
        try {
            $record = Get-Content -Raw -LiteralPath $statusFile.FullName |
                ConvertFrom-Json
            $declaredState = [string]$record.State
            if (-not [string]::IsNullOrWhiteSpace([string]$record.DeclaredState)) {
                $declaredState = [string]$record.DeclaredState
            }
            if ($declaredState -ne "running" -and $declaredState -ne "starting") {
                continue
            }

            $process = Get-Process -Id ([int]$record.ProcessId) -ErrorAction SilentlyContinue
            $staleReason = ""
            if ($null -eq $process) {
                $staleReason = "stale_process_missing"
            } elseif ($process.ProcessName -ne "ffmpeg") {
                $staleReason = "stale_process_not_ffmpeg"
            } else {
                try {
                    $expectedStart = [datetimeoffset]::Parse(
                        [string]$record.ProcessStartedAt
                    ).UtcDateTime
                    $actualStart = $process.StartTime.ToUniversalTime()
                    if ([math]::Abs(($actualStart - $expectedStart).TotalSeconds) -gt 2) {
                        $staleReason = "stale_process_start_mismatch"
                    }
                } catch {
                    $staleReason = "stale_process_start_mismatch"
                }
            }

            $record | Add-Member -NotePropertyName DeclaredState `
                -NotePropertyValue $declaredState -Force
            $record | Add-Member -NotePropertyName ProcessAlive `
                -NotePropertyValue ($null -ne $process) -Force
            $record | Add-Member -NotePropertyName ProcessStartMatch `
                -NotePropertyValue ([string]::IsNullOrWhiteSpace($staleReason)) -Force
            $record | Add-Member -NotePropertyName ReconciledAt `
                -NotePropertyValue ((Get-Date).ToUniversalTime().ToString("o")) -Force
            if (-not [string]::IsNullOrWhiteSpace($staleReason)) {
                $record.State = "stale"
                $record | Add-Member -NotePropertyName EffectiveState `
                    -NotePropertyValue "stale" -Force
                $record.LastError = $staleReason
            } else {
                $record.State = "running"
                $record | Add-Member -NotePropertyName EffectiveState `
                    -NotePropertyValue "running" -Force
            }
            $temporaryPath = "$($statusFile.FullName).$PID.tmp"
            $record | ConvertTo-Json -Depth 5 | Set-Content `
                -LiteralPath $temporaryPath `
                -Encoding ascii
            Move-Item -LiteralPath $temporaryPath `
                -Destination $statusFile.FullName `
                -Force
        } catch {
            Write-Warning "Bridge runtime reconciliation skipped invalid record: $($statusFile.Name)"
        }
    }
}

Invoke-BridgeRuntimeReconciliation

function Get-RequestedMonitorProfile {
    if (-not (Test-Path -LiteralPath $MonitorProfileStatePath -PathType Leaf)) {
        return [pscustomobject]@{ Name = $activeMonitorProfile; RequestId = $activeRequestId }
    }
    try {
        $state = Get-Content -Raw -LiteralPath $MonitorProfileStatePath | ConvertFrom-Json
        $resolved = Resolve-MonitorProfile `
            -Configuration $monitorProfileConfiguration `
            -Name ([string]$state.profile)
        $requestId = [string]$state.request_id
        if ([string]::IsNullOrWhiteSpace($requestId)) {
            $requestId = "legacy:$($resolved.Name)"
        }
        return [pscustomobject]@{ Name = $resolved.Name; RequestId = $requestId }
    } catch {
        return [pscustomobject]@{ Name = $activeMonitorProfile; RequestId = $activeRequestId }
    }
}

function Start-BridgeProcess {
    param(
        [Parameter(Mandatory = $true)]$Bridge,
        [Parameter(Mandatory = $true)][string]$ProfileName,
        [Parameter(Mandatory = $true)][string]$PublishPath,
        [Parameter(Mandatory = $true)][string]$Slot,
        [switch]$Transition
    )

    $arguments = @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", "`"$bridgeScript`"",
        "-CameraCode", $Bridge.CameraCode,
        "-SourceCodec", $Bridge.SourceCodec,
        "-PublishPath", $PublishPath,
        "-StatusKey", "$($Bridge.CameraCode)_$Slot",
        "-MonitorProfile", $ProfileName,
        "-MonitorProfilePath", "`"$MonitorProfilePath`"",
        "-TranscodeFps", $TranscodeFps,
        "-FfmpegPath", "`"$FfmpegPath`"",
        "-ProfilePath", "`"$ProfilePath`""
    )
    $process = Start-Process `
        -FilePath $powerShellPath `
        -ArgumentList $arguments `
        -WindowStyle Hidden `
        -PassThru
    if (-not $Transition) {
        $Bridge.Process = $process
        $Bridge.ExitReported = $false
        $Bridge.NextRestartAt = $null
    }
    Write-Host (
        "Bridge started: CameraCode={0} SourceCodec={1} BridgeMode={2} Destination=rtsp://127.0.0.1:8554/{3} PID={4} Restart={5}/{6} Transition={7}" -f `
            $Bridge.CameraCode,
            $Bridge.SourceCodec,
            $Bridge.BridgeMode,
            $PublishPath,
            $process.Id,
            $Bridge.RestartCount,
            $MaxRestarts,
            [bool]$Transition
    )
    return $process
}

function Stop-BridgeProcess {
    param(
        $Process,
        [Parameter(Mandatory = $true)][string]$CameraCode,
        [Parameter(Mandatory = $true)][string]$Reason
    )

    if ($null -ne $Process -and -not $Process.HasExited) {
        & taskkill.exe /PID $Process.Id /T /F | Out-Null
        Write-Host (
            "Bridge stopped: CameraCode={0} PID={1} Reason={2}" -f `
                $CameraCode,
                $Process.Id,
                $Reason
        )
    }
}

function Write-TransitionState {
    param(
        [Parameter(Mandatory = $true)][string]$State,
        [string]$TransitionId = "",
        [string]$FromProfile = "",
        [string]$ToProfile = "",
        [string]$StartedAt = "",
        [hashtable]$NextEntries = @{},
        [int]$TransitionCameraCount = -1,
        [string]$LastError = ""
    )

    $cameraStates = @()
    foreach ($bridge in $bridges) {
        $nextEntry = $NextEntries[$bridge.CameraCode]
        $nextPath = if ($null -ne $nextEntry) { [string]$nextEntry.Path } else { "" }
        $cameraState = if ($null -ne $nextEntry) { $State } else { "idle" }
        $cameraStates += [ordered]@{
            CameraCode = $bridge.CameraCode
            ActivePath = $bridge.ActivePath
            NextPath = $nextPath
            TransitionState = $cameraState
        }
    }
    $record = [ordered]@{
        TransitionId = $TransitionId
        ActiveProfile = $activeMonitorProfile
        ProfileTransitionState = $State
        FromProfile = $FromProfile
        ToProfile = $ToProfile
        StartedAt = $StartedAt
        CameraCount = if ($TransitionCameraCount -ge 0) {
            $TransitionCameraCount
        } else {
            @($NextEntries.Keys).Count
        }
        LastError = $LastError
        Cameras = $cameraStates
    }
    $stateDirectory = Split-Path -Parent $TransitionStatePath
    New-Item -ItemType Directory -Path $stateDirectory -Force | Out-Null
    $temporaryPath = "$TransitionStatePath.$PID.tmp"
    $record | ConvertTo-Json -Depth 5 | Set-Content `
        -LiteralPath $temporaryPath `
        -Encoding ascii
    Move-Item -LiteralPath $temporaryPath -Destination $TransitionStatePath -Force
}

function Test-MediaPathReady {
    param([Parameter(Mandatory = $true)][string]$Path)

    try {
        $payload = Invoke-RestMethod `
            -Uri "$($MediaMtxApiBaseUrl.TrimEnd('/'))/v3/paths/list" `
            -Method Get `
            -TimeoutSec 2
        foreach ($item in @($payload.items)) {
            if (
                [string]$item.name -eq $Path -and
                ([bool]$item.ready -or [bool]$item.online)
            ) {
                return $true
            }
        }
    } catch {
        return $false
    }
    return $false
}

function Test-TransitionAcknowledged {
    param(
        [Parameter(Mandatory = $true)][string]$TransitionId,
        [Parameter(Mandatory = $true)][string[]]$ExpectedCameraCodes
    )

    if (-not (Test-Path -LiteralPath $TransitionAckPath -PathType Leaf)) {
        return $false
    }
    try {
        $ack = Get-Content -Raw -LiteralPath $TransitionAckPath | ConvertFrom-Json
        $actualCodes = @($ack.CameraCodes | Sort-Object)
        $expectedCodes = @($ExpectedCameraCodes | Sort-Object)
        return (
            [string]$ack.TransitionId -eq $TransitionId -and
            [bool]$ack.Acknowledged -and
            ($actualCodes -join ",") -eq ($expectedCodes -join ",")
        )
    } catch {
        return $false
    }
}

function Stop-TransitionEntries {
    param(
        [hashtable]$Entries,
        [Parameter(Mandatory = $true)][string]$Reason
    )

    foreach ($entry in $Entries.Values) {
        Stop-BridgeProcess `
            -Process $entry.Process `
            -CameraCode $entry.Bridge.CameraCode `
            -Reason $Reason
    }
}

function Invoke-ProfileTransition {
    param(
        [Parameter(Mandatory = $true)][string]$TargetProfile,
        [Parameter(Mandatory = $true)][string]$RequestId
    )

    $fromProfile = $activeMonitorProfile
    $transitionId = [guid]::NewGuid().ToString()
    $startedAt = (Get-Date).ToUniversalTime().ToString("o")
    $deadline = (Get-Date).AddSeconds($TransitionTimeoutSeconds)
    $nextEntries = @{}
    try {
        foreach ($bridge in $bridges) {
            if ($bridge.BridgeMode -ne "transcode" -or $bridge.Exhausted) {
                continue
            }
            $nextSlot = if ($bridge.ActiveSlot -eq "a") { "b" } else { "a" }
            $nextPath = if ($nextSlot -eq "a") {
                $bridge.BasePath
            } else {
                "$($bridge.BasePath)_b"
            }
            $nextProcess = Start-BridgeProcess `
                -Bridge $bridge `
                -ProfileName $TargetProfile `
                -PublishPath $nextPath `
                -Slot $nextSlot `
                -Transition
            $nextEntries[$bridge.CameraCode] = [pscustomobject]@{
                Bridge = $bridge
                Process = $nextProcess
                Path = $nextPath
                Slot = $nextSlot
            }
        }

        if ($nextEntries.Count -eq 0) {
            foreach ($bridge in $bridges) {
                $bridge.Profile = $TargetProfile
            }
            $script:activeMonitorProfile = $TargetProfile
            $script:activeRequestId = $RequestId
            Write-TransitionState -State "idle"
            return [pscustomobject]@{ Outcome = "completed"; RequestId = $RequestId }
        }

        Write-TransitionState `
            -State "starting" `
            -TransitionId $transitionId `
            -FromProfile $fromProfile `
            -ToProfile $TargetProfile `
            -StartedAt $startedAt `
            -NextEntries $nextEntries

        $pathsReady = $false
        while ((Get-Date) -lt $deadline) {
            $latestRequest = Get-RequestedMonitorProfile
            if ($latestRequest.RequestId -ne $RequestId) {
                Stop-TransitionEntries -Entries $nextEntries -Reason "layout_change_cancelled"
                Write-TransitionState `
                    -State "cancelled" `
                    -TransitionId $transitionId `
                    -FromProfile $fromProfile `
                    -ToProfile $TargetProfile `
                    -StartedAt $startedAt `
                    -TransitionCameraCount $nextEntries.Count `
                    -LastError "replaced_by_newer_profile_request"
                return [pscustomobject]@{ Outcome = "cancelled"; RequestId = $latestRequest.RequestId }
            }

            $failedEntry = @(
                $nextEntries.Values | Where-Object { $_.Process.HasExited }
            ) | Select-Object -First 1
            if ($null -ne $failedEntry) {
                throw "transition_bridge_exited"
            }

            if (-not $pathsReady) {
                $pathsReady = @(
                    $nextEntries.Values |
                        Where-Object { -not (Test-MediaPathReady -Path $_.Path) }
                ).Count -eq 0
                if ($pathsReady) {
                    Write-TransitionState `
                        -State "preloading" `
                        -TransitionId $transitionId `
                        -FromProfile $fromProfile `
                        -ToProfile $TargetProfile `
                        -StartedAt $startedAt `
                        -NextEntries $nextEntries
                }
            }

            if (
                $pathsReady -and
                (Test-TransitionAcknowledged `
                    -TransitionId $transitionId `
                    -ExpectedCameraCodes @($nextEntries.Keys))
            ) {
                Write-TransitionState `
                    -State "committing" `
                    -TransitionId $transitionId `
                    -FromProfile $fromProfile `
                    -ToProfile $TargetProfile `
                    -StartedAt $startedAt `
                    -NextEntries $nextEntries
                foreach ($entry in $nextEntries.Values) {
                    $bridge = $entry.Bridge
                    $oldProcess = $bridge.Process
                    $bridge.Process = $entry.Process
                    $bridge.ActivePath = $entry.Path
                    $bridge.ActiveSlot = $entry.Slot
                    $bridge.Profile = $TargetProfile
                    $bridge.ExitReported = $false
                    $bridge.NextRestartAt = $null
                    Stop-BridgeProcess `
                        -Process $oldProcess `
                        -CameraCode $bridge.CameraCode `
                        -Reason "layout_change_cleanup"
                }
                foreach ($bridge in $bridges) {
                    if ($bridge.BridgeMode -eq "copy") {
                        $bridge.Profile = $TargetProfile
                    }
                }
                $script:activeMonitorProfile = $TargetProfile
                $script:activeRequestId = $RequestId
                Write-TransitionState -State "idle"
                Write-Host (
                    "Monitor profile switched: Previous={0} Current={1} Reason=layout_change" -f `
                        $fromProfile,
                        $TargetProfile
                )
                return [pscustomobject]@{ Outcome = "completed"; RequestId = $RequestId }
            }
            Start-Sleep -Milliseconds 250
        }

        Stop-TransitionEntries -Entries $nextEntries -Reason "layout_change_timeout"
        $script:activeRequestId = $RequestId
        Write-TransitionState `
            -State "failed" `
            -TransitionId $transitionId `
            -FromProfile $fromProfile `
            -ToProfile $TargetProfile `
            -StartedAt $startedAt `
            -TransitionCameraCount $nextEntries.Count `
            -LastError "transition_timeout_current_stream_retained"
        return [pscustomobject]@{ Outcome = "failed"; RequestId = $RequestId }
    } catch {
        Stop-TransitionEntries -Entries $nextEntries -Reason "layout_change_failed"
        $script:activeRequestId = $RequestId
        Write-TransitionState `
            -State "failed" `
            -TransitionId $transitionId `
            -FromProfile $fromProfile `
            -ToProfile $TargetProfile `
            -StartedAt $startedAt `
            -TransitionCameraCount $nextEntries.Count `
            -LastError "transition_failed_current_stream_retained"
        return [pscustomobject]@{ Outcome = "failed"; RequestId = $RequestId }
    }
}

$requestedMonitorProfile = Get-RequestedMonitorProfile
$activeMonitorProfile = $requestedMonitorProfile.Name
$activeRequestId = $requestedMonitorProfile.RequestId
$resolvedStartupProfile = Resolve-MonitorProfile `
    -Configuration $monitorProfileConfiguration `
    -Name $activeMonitorProfile

try {
    foreach ($code in $requestedCodes) {
        $profile = $cameraProfiles[$code]
        $bridgeProfile = Resolve-BridgeProfile `
            -Codec ([string]$profile.SourceCodec) `
            -OutputWidth $resolvedStartupProfile.Width `
            -OutputHeight $resolvedStartupProfile.Height `
            -OutputFps $resolvedStartupProfile.Fps
        $bridge = [pscustomobject]@{
            CameraCode = $code
            BasePath = [string]$profile.Path
            ActivePath = [string]$profile.Path
            ActiveSlot = "a"
            SourceCodec = $bridgeProfile.SourceCodec
            BridgeMode = $bridgeProfile.BridgeMode
            Process = $null
            ExitReported = $false
            RestartCount = 0
            NextRestartAt = $null
            Exhausted = $false
            Profile = $activeMonitorProfile
        }
        $bridges += $bridge
        Start-BridgeProcess `
            -Bridge $bridge `
            -ProfileName $activeMonitorProfile `
            -PublishPath $bridge.ActivePath `
            -Slot $bridge.ActiveSlot | Out-Null
    }

    Write-TransitionState -State "idle"
    Write-Host "All requested bridges started. Press Ctrl+C to stop."
    while (@($bridges | Where-Object { -not $_.Exhausted }).Count -gt 0) {
        $requestedMonitorProfile = Get-RequestedMonitorProfile
        if (
            $requestedMonitorProfile.RequestId -ne $activeRequestId -and
            $requestedMonitorProfile.Name -ne $activeMonitorProfile
        ) {
            $null = Invoke-ProfileTransition `
                -TargetProfile $requestedMonitorProfile.Name `
                -RequestId $requestedMonitorProfile.RequestId
        } elseif ($requestedMonitorProfile.Name -eq $activeMonitorProfile) {
            $activeRequestId = $requestedMonitorProfile.RequestId
        }

        foreach ($bridge in $bridges) {
            if (
                $null -ne $bridge.Process -and
                $bridge.Process.HasExited -and
                -not $bridge.ExitReported
            ) {
                $bridge.ExitReported = $true
                Write-Host (
                    "Bridge exited: CameraCode={0} SourceCodec={1} BridgeMode={2} Destination=rtsp://127.0.0.1:8554/{3} PID={4} Exit={5}" -f `
                        $bridge.CameraCode,
                        $bridge.SourceCodec,
                        $bridge.BridgeMode,
                        $bridge.ActivePath,
                        $bridge.Process.Id,
                        $bridge.Process.ExitCode
                )
                if ($bridge.RestartCount -lt $MaxRestarts) {
                    $bridge.RestartCount += 1
                    $restartDelay = $RestartBaseSeconds * [math]::Pow(
                        2,
                        $bridge.RestartCount - 1
                    )
                    $bridge.NextRestartAt = (Get-Date).AddSeconds($restartDelay)
                    $bridge.Process = $null
                    Write-Host (
                        "Bridge restart scheduled: CameraCode={0} DelaySeconds={1} Attempt={2}/{3}" -f `
                            $bridge.CameraCode,
                            $restartDelay,
                            $bridge.RestartCount,
                            $MaxRestarts
                    )
                } else {
                    $bridge.Exhausted = $true
                    Write-Host (
                        "Bridge restart limit reached: CameraCode={0} Attempts={1}" -f `
                            $bridge.CameraCode,
                            $bridge.RestartCount
                    )
                }
            }
            if (
                $null -eq $bridge.Process -and
                -not $bridge.Exhausted -and
                $null -ne $bridge.NextRestartAt -and
                (Get-Date) -ge $bridge.NextRestartAt
            ) {
                Start-BridgeProcess `
                    -Bridge $bridge `
                    -ProfileName $bridge.Profile `
                    -PublishPath $bridge.ActivePath `
                    -Slot $bridge.ActiveSlot | Out-Null
            }
        }
        Start-Sleep -Milliseconds 500
    }
} finally {
    foreach ($bridge in $bridges) {
        Stop-BridgeProcess `
            -Process $bridge.Process `
            -CameraCode $bridge.CameraCode `
            -Reason "supervisor_shutdown"
    }
}
