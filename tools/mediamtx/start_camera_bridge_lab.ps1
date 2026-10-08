param(
    [Parameter(Mandatory = $true)]
    [string]$CameraCode,

    [string]$SourceCodec = "",
    [string]$PublishPath = "",
    [string]$StatusKey = "",
    [string]$MonitorProfile = "grid4",
    [string]$MonitorProfilePath = "",
    [ValidateRange(0, 60)]
    [int]$TranscodeFps = 0,
    [string]$FfmpegPath = "C:\Program Files\ffmpeg\bin\ffmpeg.exe",
    [string]$ProfilePath = "",
    [string]$StatusDirectory = ""
)

$ErrorActionPreference = "Stop"
$codecResolverScript = Join-Path $PSScriptRoot "camera_bridge_codec.ps1"
if (-not (Test-Path -LiteralPath $codecResolverScript -PathType Leaf)) {
    throw "Camera bridge codec resolver not found: $codecResolverScript"
}
. $codecResolverScript

$normalizedCameraCode = $CameraCode.Trim().ToUpperInvariant()
if ([string]::IsNullOrWhiteSpace($ProfilePath)) {
    $ProfilePath = Join-Path $PSScriptRoot "camera_bridge_profiles.lab.psd1"
}
if ([string]::IsNullOrWhiteSpace($StatusDirectory)) {
    $StatusDirectory = Join-Path $PSScriptRoot "../../runtime/mediamtx/bridges"
}
if ([string]::IsNullOrWhiteSpace($MonitorProfilePath)) {
    $MonitorProfilePath = Join-Path $PSScriptRoot "../../config/monitor_profiles.json"
}

if (-not (Test-Path -LiteralPath $ProfilePath -PathType Leaf)) {
    throw "Camera bridge profile not found: $ProfilePath"
}
$cameraProfiles = Import-PowerShellDataFile -LiteralPath $ProfilePath
if (-not $cameraProfiles.ContainsKey($normalizedCameraCode)) {
    throw "Unsupported CameraCode: $normalizedCameraCode"
}
if (-not (Test-Path -LiteralPath $FfmpegPath -PathType Leaf)) {
    throw "ffmpeg.exe not found: $FfmpegPath"
}

$cameraUsername = $env:KRTC_LAB_CAMERA_USERNAME
$cameraPassword = $env:KRTC_LAB_CAMERA_PASSWORD
if (
    [string]::IsNullOrWhiteSpace($cameraUsername) -or
    [string]::IsNullOrWhiteSpace($cameraPassword)
) {
    throw "Set KRTC_LAB_CAMERA_USERNAME and KRTC_LAB_CAMERA_PASSWORD first."
}

$cameraProfile = $cameraProfiles[$normalizedCameraCode]
$monitorProfileConfiguration = Import-MonitorProfileConfiguration `
    -Path $MonitorProfilePath
$resolvedMonitorProfile = Resolve-MonitorProfile `
    -Configuration $monitorProfileConfiguration `
    -Name $MonitorProfile
if ($TranscodeFps -gt 0) {
    $resolvedMonitorProfile.Fps = $TranscodeFps
}
$resolvedSourceCodec = if ([string]::IsNullOrWhiteSpace($SourceCodec)) {
    [string]$cameraProfile.SourceCodec
} else {
    $SourceCodec
}
$bridgeProfile = Resolve-BridgeProfile `
    -Codec $resolvedSourceCodec `
    -OutputWidth $resolvedMonitorProfile.Width `
    -OutputHeight $resolvedMonitorProfile.Height `
    -OutputFps $resolvedMonitorProfile.Fps
$cameraHost = [string]$cameraProfile.Host
$pathName = [string]$cameraProfile.Path
if (-not [string]::IsNullOrWhiteSpace($PublishPath)) {
    $allowedPublishPaths = @($pathName, "${pathName}_b")
    if ($allowedPublishPaths -notcontains $PublishPath) {
        throw "Unsupported publish path for CameraCode: $normalizedCameraCode"
    }
    if (
        $PublishPath -eq "${pathName}_b" -and
        $bridgeProfile.BridgeMode -ne "transcode"
    ) {
        throw "Alternate publish path requires transcode mode."
    }
    $pathName = $PublishPath
}
if ([string]::IsNullOrWhiteSpace($StatusKey)) {
    $StatusKey = $normalizedCameraCode
}
if ($StatusKey -notmatch '^[A-Za-z0-9_-]+$') {
    throw "Invalid bridge status key."
}

$encodedUsername = [Uri]::EscapeDataString($cameraUsername)
$encodedPassword = [Uri]::EscapeDataString($cameraPassword)
$sourceUrl = "rtsp://${encodedUsername}:${encodedPassword}@$cameraHost/cam1/h264"
$destinationUrl = "rtsp://127.0.0.1:8554/$pathName"

$ffmpegArguments = @(
    "-hide_banner",
    "-loglevel", "warning",
    "-nostats",
    "-fflags", "+genpts",
    "-use_wallclock_as_timestamps", "1",
    "-rtsp_transport", "tcp",
    "-i", $sourceUrl,
    "-map", "0:v:0"
)
$ffmpegArguments += $bridgeProfile.VideoArguments
$ffmpegArguments += @(
    "-an",
    "-dn",
    "-f", "rtsp",
    "-rtsp_transport", "tcp",
    $destinationUrl
)

New-Item -ItemType Directory -Path $StatusDirectory -Force | Out-Null
$statusPath = Join-Path $StatusDirectory "$StatusKey.json"
$statusRecord = [ordered]@{
    CameraCode = $normalizedCameraCode
    SourceCodec = $bridgeProfile.SourceCodec
    BridgeMode = $bridgeProfile.BridgeMode
    Destination = $destinationUrl
    PublishPath = $pathName
    ProcessId = 0
    ProcessStartedAt = ""
    DeclaredState = "starting"
    EffectiveState = "starting"
    State = "starting"
    StartedAt = (Get-Date).ToUniversalTime().ToString("o")
    ExitCode = $null
    LastError = ""
    Profile = $resolvedMonitorProfile.Name
    OutputWidth = $resolvedMonitorProfile.Width
    OutputHeight = $resolvedMonitorProfile.Height
    OutputFps = $resolvedMonitorProfile.Fps
}

function Write-BridgeStatus {
    $temporaryPath = "$statusPath.$PID.tmp"
    $statusRecord | ConvertTo-Json | Set-Content `
        -LiteralPath $temporaryPath `
        -Encoding ascii
    Move-Item -LiteralPath $temporaryPath -Destination $statusPath -Force
}

Write-BridgeStatus

Write-Host (
    "Bridge starting: CameraCode={0} SourceCodec={1} BridgeMode={2} Destination={3}" -f `
        $normalizedCameraCode,
        $bridgeProfile.SourceCodec,
        $bridgeProfile.BridgeMode,
        $destinationUrl
)
Write-Host "TimestampMode=genpts+wallclock Transport=RTSP/TCP VideoOnly=true"
if ($bridgeProfile.BridgeMode -eq "transcode") {
    Write-Host (
        "Profile={0} Output={1}x{2} OutputFps={3} FrameRateMode=CFR" -f `
            $resolvedMonitorProfile.Name,
            $resolvedMonitorProfile.Width,
            $resolvedMonitorProfile.Height,
            $resolvedMonitorProfile.Fps
    )
}
Write-Host "Press Ctrl+C to stop the bridge."

$exitCode = 1
$lastError = ""
$ffmpegProcess = $null
try {
    $ffmpegProcess = Start-Process `
        -FilePath $FfmpegPath `
        -ArgumentList $ffmpegArguments `
        -NoNewWindow `
        -PassThru
    $statusRecord["ProcessId"] = $ffmpegProcess.Id
    $statusRecord["ProcessStartedAt"] = (
        $ffmpegProcess.StartTime.ToUniversalTime().ToString("o")
    )
    $statusRecord["DeclaredState"] = "running"
    $statusRecord["EffectiveState"] = "running"
    $statusRecord["State"] = "running"
    Write-BridgeStatus
    $ffmpegProcess.WaitForExit()
    $exitCode = $ffmpegProcess.ExitCode
    if ($exitCode -ne 0) {
        $lastError = "ffmpeg_exit_code_$exitCode"
    }
} catch {
    $exitCode = 1
    $lastError = "bridge_execution_exception_$($_.Exception.GetType().Name)"
} finally {
    if ($exitCode -ne 0 -and [string]::IsNullOrWhiteSpace($lastError)) {
        $lastError = "bridge_interrupted_or_failed"
    }
    $statusRecord["State"] = "stopped"
    $statusRecord["DeclaredState"] = "stopped"
    $statusRecord["EffectiveState"] = "stopped"
    $statusRecord["StoppedAt"] = (Get-Date).ToUniversalTime().ToString("o")
    $statusRecord["ExitCode"] = $exitCode
    $statusRecord["LastError"] = $lastError
    Write-BridgeStatus
}

Write-Host (
    "Bridge stopped: CameraCode={0} SourceCodec={1} BridgeMode={2} Exit={3}" -f `
        $normalizedCameraCode,
        $bridgeProfile.SourceCodec,
        $bridgeProfile.BridgeMode,
        $exitCode
)
exit $exitCode
