param(
    [string]$ResultRootDirectory = ""
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "Stress_Common.ps1")

if ([string]::IsNullOrWhiteSpace($ResultRootDirectory)) {
    $ResultRootDirectory = Join-Path (Get-StressProjectRoot) "stress_results"
}
$runDirectory = Join-Path $ResultRootDirectory (
    "collector_smoke_{0}" -f (Get-Date -Format "yyyyMMdd_HHmmss")
)
New-Item -ItemType Directory -Path $runDirectory -Force | Out-Null
Remove-StaleStressTempFiles

$stdoutPath = Join-Path $runDirectory "collector.stdout.log"
$stderrPath = Join-Path $runDirectory "collector.stderr.log"
$collectorScript = Join-Path $PSScriptRoot "Collect_Stress_Metrics.ps1"
$arguments = @(
    "-NoProfile",
    "-ExecutionPolicy", "Bypass",
    "-File", $collectorScript,
    "-DurationMinutes", "1",
    "-SampleSeconds", "10",
    "-ResultDirectory", $runDirectory,
    "-SmokeMode"
)
$collector = Start-Process -FilePath "powershell.exe" -ArgumentList $arguments -PassThru -WindowStyle Hidden -RedirectStandardOutput $stdoutPath -RedirectStandardError $stderrPath
Set-Content -LiteralPath (Join-Path $runDirectory "collector.pid") -Value $collector.Id -Encoding ascii
Start-Sleep -Seconds 2
$collector.Refresh()
if ($collector.HasExited) {
    $earlyExitCodePath = Join-Path $runDirectory "collector.exitcode"
    $earlyExitState = if (Test-Path -LiteralPath $earlyExitCodePath -PathType Leaf) {
        [string](Get-Content -LiteralPath $earlyExitCodePath -Raw).Trim()
    } else {
        "missing"
    }
    $errorTail = @(Get-Content -LiteralPath $stderrPath -Tail 20) -join [Environment]::NewLine
    throw ("Collector smoke exited early. CompletionState={0}. {1}" -f $earlyExitState, $errorTail)
}
if (-not $collector.WaitForExit(90000)) {
    Stop-Process -Id $collector.Id -Force -ErrorAction SilentlyContinue
    throw "Collector smoke exceeded the 90-second timeout."
}
$collector.WaitForExit()
$collector.Refresh()
$exitCodePath = Join-Path $runDirectory "collector.exitcode"
if (-not (Test-Path -LiteralPath $exitCodePath -PathType Leaf)) {
    throw "Collector smoke did not write its completion state."
}
$collectorExitCode = 1
if (-not [int]::TryParse(
    [string](Get-Content -LiteralPath $exitCodePath -Raw),
    [ref]$collectorExitCode
)) {
    throw "Collector smoke wrote an invalid completion state."
}
if ($collectorExitCode -ne 0) {
    $errorTail = @(Get-Content -LiteralPath $stderrPath -Tail 20) -join [Environment]::NewLine
    throw ("Collector smoke failed with exit code {0}. {1}" -f $collectorExitCode, $errorTail)
}

foreach ($requiredOutput in @("metrics.csv", "summary.txt", "collector.stdout.log", "collector.stderr.log", "run_metadata.json", "collector.exitcode")) {
    if (-not (Test-Path -LiteralPath (Join-Path $runDirectory $requiredOutput) -PathType Leaf)) {
        throw ("Collector smoke output is missing: {0}" -f $requiredOutput)
    }
}
$samples = @(Import-Csv -LiteralPath (Join-Path $runDirectory "metrics.csv"))
if ($samples.Count -lt 5) {
    throw ("Collector smoke produced only {0} samples." -f $samples.Count)
}
Remove-StaleStressTempFiles -MinimumAgeSeconds 5
$staleTempFiles = @(
    Get-ChildItem -LiteralPath (Get-StressRuntimeDirectory) -File -ErrorAction SilentlyContinue |
        Where-Object {
            $_.LastWriteTime -le (Get-Date).AddSeconds(-5) -and (
                $_.Name -match '^\.?stress_processes\.json\.[0-9a-f-]+\.tmp$' -or
                $_.Name -match '^\.browser_state\.json\.[0-9a-f-]+\.tmp$' -or
                $_.Name -eq 'stress_processes.json.tmp'
            )
        }
)
if ($staleTempFiles.Count -gt 0) {
    throw "Collector smoke left stale temporary state files."
}
Write-Host ("Collector smoke PASS: Samples={0} Run={1}" -f $samples.Count, $runDirectory)
