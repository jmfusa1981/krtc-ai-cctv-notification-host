param(
    [string]$FfmpegPath = "C:\Program Files\ffmpeg\bin\ffmpeg.exe",
    [string]$StressPageUrl = "http://127.0.0.1:8000/dashboard/lab/media-stress/?auto=1",
    [switch]$DoNotOpenBrowser
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "Stress_Common.ps1")

$collector = $null
try {
    $stopRequestPath = Get-StressStopRequestPath
    if (Test-Path -LiteralPath $stopRequestPath -PathType Leaf) {
        Remove-Item -LiteralPath $stopRequestPath -Force
    }
    Start-StressPublishers -Count 9 -FfmpegPath $FfmpegPath
    if (-not $DoNotOpenBrowser) {
        Start-Process $StressPageUrl
    }
    $collectorScript = Join-Path $PSScriptRoot "Collect_Stress_Metrics.ps1"
    $collectorArguments = @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", $collectorScript,
        "-DurationMinutes", "30",
        "-SampleSeconds", "30",
        "-DashboardUrl", $StressPageUrl
    )
    $collector = Start-Process -FilePath "powershell.exe" -ArgumentList $collectorArguments -PassThru -WindowStyle Hidden
    Write-Host "Phase 1 started: minutes 0-5, 9 streams."
    for ($second = 0; $second -lt 300; $second++) {
        if (Test-Path -LiteralPath $stopRequestPath -PathType Leaf) {
            throw "Stress stop requested."
        }
        Start-Sleep -Seconds 1
    }
    Start-StressPublishers -Count 16 -FfmpegPath $FfmpegPath
    Write-Host "Phase 2 started: minutes 5-10, 16 streams."
    Write-Host "Phase 3 is automatic: minutes 10-15, 4-9-16-4-16 layouts."
    Write-Host "Phase 4 is automatic: minutes 15-30, 16-grid soak."
    for ($second = 0; $second -lt 1500; $second++) {
        if (Test-Path -LiteralPath $stopRequestPath -PathType Leaf) {
            throw "Stress stop requested."
        }
        Start-Sleep -Seconds 1
    }
    if ($collector -and -not $collector.HasExited) {
        $collector.WaitForExit(60000)
    }
} finally {
    if ($collector -and -not $collector.HasExited) {
        Stop-Process -Id $collector.Id -Force -ErrorAction SilentlyContinue
    }
    Stop-AllStressPublishers
    if (Test-Path -LiteralPath (Get-StressStopRequestPath) -PathType Leaf) {
        Remove-Item -LiteralPath (Get-StressStopRequestPath) -Force
    }
    Write-Host "Stress cleanup complete. Results were preserved."
}
