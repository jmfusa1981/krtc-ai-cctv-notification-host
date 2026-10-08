param(
    [string]$FfmpegPath = "C:\Program Files\ffmpeg\bin\ffmpeg.exe",
    [string]$StressPageUrl = "http://127.0.0.1:8000/dashboard/lab/media-stress/?auto=1",
    [string]$ResultRootDirectory = "",
    [switch]$DoNotOpenBrowser
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "Stress_Common.ps1")

$collector = $null
function Assert-StressCollectorRunning {
    param($CollectorProcess, [string]$ErrorLogPath)

    if (-not $CollectorProcess) {
        throw "Stress collector process was not created."
    }
    $CollectorProcess.Refresh()
    if ($CollectorProcess.HasExited) {
        $completionPath = Join-Path (Split-Path -Parent $ErrorLogPath) "collector.exitcode"
        $completionState = if (Test-Path -LiteralPath $completionPath -PathType Leaf) {
            [string](Get-Content -LiteralPath $completionPath -Raw).Trim()
        } else {
            "missing"
        }
        $errorTail = if (Test-Path -LiteralPath $ErrorLogPath -PathType Leaf) {
            @(Get-Content -LiteralPath $ErrorLogPath -Tail 20) -join [Environment]::NewLine
        } else {
            "collector stderr log was not created"
        }
        throw ("Stress collector exited early. CompletionState={0}. {1}" -f $completionState, $errorTail)
    }
}

try {
    Remove-StaleStressTempFiles
    $stopRequestPath = Get-StressStopRequestPath
    if (Test-Path -LiteralPath $stopRequestPath -PathType Leaf) {
        Remove-Item -LiteralPath $stopRequestPath -Force
    }
    Start-StressPublishers -Count 9 -FfmpegPath $FfmpegPath
    if (-not $DoNotOpenBrowser) {
        Start-Process $StressPageUrl
    }
    if ([string]::IsNullOrWhiteSpace($ResultRootDirectory)) {
        $ResultRootDirectory = Join-Path (Get-StressProjectRoot) "stress_results"
    }
    $runDirectory = Join-Path $ResultRootDirectory (
        "stress_{0}" -f (Get-Date -Format "yyyyMMdd_HHmmss")
    )
    New-Item -ItemType Directory -Path $runDirectory -Force | Out-Null
    $collectorStdoutPath = Join-Path $runDirectory "collector.stdout.log"
    $collectorStderrPath = Join-Path $runDirectory "collector.stderr.log"
    $collectorPidPath = Join-Path $runDirectory "collector.pid"
    $collectorScript = Join-Path $PSScriptRoot "Collect_Stress_Metrics.ps1"
    $collectorArguments = @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", $collectorScript,
        "-DurationMinutes", "30",
        "-SampleSeconds", "30",
        "-DashboardUrl", $StressPageUrl,
        "-ResultDirectory", $runDirectory
    )
    $collector = Start-Process -FilePath "powershell.exe" -ArgumentList $collectorArguments -PassThru -WindowStyle Hidden -RedirectStandardOutput $collectorStdoutPath -RedirectStandardError $collectorStderrPath
    Set-Content -LiteralPath $collectorPidPath -Value $collector.Id -Encoding ascii
    Start-Sleep -Seconds 2
    Assert-StressCollectorRunning -CollectorProcess $collector -ErrorLogPath $collectorStderrPath
    if (-not (Test-Path -LiteralPath (Join-Path $runDirectory "run_metadata.json") -PathType Leaf)) {
        throw "Stress collector did not create run metadata during startup."
    }
    Write-Host ("Stress collector verified: PID={0} Run={1}" -f $collector.Id, $runDirectory)
    Write-Host "Phase 1 started: minutes 0-5, 9 streams."
    for ($second = 0; $second -lt 300; $second++) {
        if (Test-Path -LiteralPath $stopRequestPath -PathType Leaf) {
            throw "Stress stop requested."
        }
        Assert-StressCollectorRunning -CollectorProcess $collector -ErrorLogPath $collectorStderrPath
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
        Assert-StressCollectorRunning -CollectorProcess $collector -ErrorLogPath $collectorStderrPath
        Start-Sleep -Seconds 1
    }
    if ($collector -and -not $collector.HasExited) {
        $collector.WaitForExit(60000)
    }
    $collector.Refresh()
    if (-not $collector.HasExited) {
        throw "Stress collector did not exit within the completion timeout."
    }
    $collector.WaitForExit()
    $collector.Refresh()
    $collectorExitCodePath = Join-Path $runDirectory "collector.exitcode"
    if (-not (Test-Path -LiteralPath $collectorExitCodePath -PathType Leaf)) {
        throw "Stress collector did not write its completion state."
    }
    $collectorExitCode = 1
    if (-not [int]::TryParse(
        [string](Get-Content -LiteralPath $collectorExitCodePath -Raw),
        [ref]$collectorExitCode
    )) {
        throw "Stress collector wrote an invalid completion state."
    }
    if ($collectorExitCode -ne 0) {
        $errorTail = @(Get-Content -LiteralPath $collectorStderrPath -Tail 20) -join [Environment]::NewLine
        throw ("Stress collector failed with exit code {0}. {1}" -f $collectorExitCode, $errorTail)
    }
    foreach ($requiredOutput in @("metrics.csv", "summary.txt", "collector.stdout.log", "collector.stderr.log", "run_metadata.json", "collector.exitcode")) {
        if (-not (Test-Path -LiteralPath (Join-Path $runDirectory $requiredOutput) -PathType Leaf)) {
            throw ("Stress collector output is missing: {0}" -f $requiredOutput)
        }
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
