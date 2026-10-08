param(
    [ValidateRange(1, 1440)]
    [int]$DurationMinutes = 30,
    [ValidateRange(5, 300)]
    [int]$SampleSeconds = 30,
    [string]$MediaMtxApiBaseUrl = "http://127.0.0.1:9997",
    [string]$DashboardUrl = "http://127.0.0.1:8000/dashboard/lab/media-stress/",
    [string]$ResultDirectory = "",
    [switch]$SmokeMode
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "Stress_Common.ps1")

$runStamp = Get-Date -Format "yyyyMMdd_HHmmss"
if ([string]::IsNullOrWhiteSpace($ResultDirectory)) {
    $ResultDirectory = Join-Path (Get-StressProjectRoot) "stress_results\stress_$runStamp"
}
New-Item -ItemType Directory -Path $ResultDirectory -Force | Out-Null
$csvPath = Join-Path $ResultDirectory "metrics.csv"
$summaryPath = Join-Path $ResultDirectory "summary.txt"
$stdoutLogPath = Join-Path $ResultDirectory "collector.stdout.log"
$stderrLogPath = Join-Path $ResultDirectory "collector.stderr.log"
$metadataPath = Join-Path $ResultDirectory "run_metadata.json"
$exitCodePath = Join-Path $ResultDirectory "collector.exitcode"
if (-not (Test-Path -LiteralPath $stdoutLogPath -PathType Leaf)) {
    New-Item -ItemType File -Path $stdoutLogPath -Force | Out-Null
}
if (-not (Test-Path -LiteralPath $stderrLogPath -PathType Leaf)) {
    New-Item -ItemType File -Path $stderrLogPath -Force | Out-Null
}
trap {
    Set-Content -LiteralPath $exitCodePath -Value "1" -Encoding ascii
    [Console]::Error.WriteLine(
        "Stress collector failed: {0}",
        $_.Exception.Message
    )
    exit 1
}
Remove-StaleStressTempFiles
if (Test-Path -LiteralPath $exitCodePath -PathType Leaf) {
    Remove-Item -LiteralPath $exitCodePath -Force
}
$logicalProcessorCount = [Math]::Max(1, [Environment]::ProcessorCount)
$previousCpuSeconds = @{}
$previousNetworkBytes = $null
$previousSampleAt = $null
$rows = [System.Collections.Generic.List[object]]::new()
$startedAt = Get-Date
$deadline = $startedAt.AddMinutes($DurationMinutes)
$runMetadata = [ordered]@{
    schema_version = 1
    run_id = Split-Path -Leaf $ResultDirectory
    started_at = $startedAt.ToUniversalTime().ToString("o")
    duration_minutes = $DurationMinutes
    sample_seconds = $SampleSeconds
    smoke_mode = [bool]$SmokeMode
    collector_process_id = $PID
    powershell_version = $PSVersionTable.PSVersion.ToString()
    mediamtx_api_base_url = $MediaMtxApiBaseUrl
    dashboard_url = $DashboardUrl
}
$runMetadata | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $metadataPath -Encoding ascii
Write-Host ("Stress collector startup: PID={0} Run={1} DurationMinutes={2} SampleSeconds={3} SmokeMode={4}" -f $PID, $ResultDirectory, $DurationMinutes, $SampleSeconds, [bool]$SmokeMode)

function Get-ProcessTotals {
    param(
        [array]$Processes,
        [string]$KeyPrefix,
        [DateTime]$SampleAt
    )

    $memoryBytes = 0.0
    $cpuDeltaSeconds = 0.0
    $responding = $true
    foreach ($process in $Processes) {
        try {
            $process.Refresh()
            $memoryBytes += [double]$process.WorkingSet64
            $key = "$KeyPrefix-$($process.Id)"
            $currentCpu = [double]$process.CPU
            if ($previousCpuSeconds.ContainsKey($key)) {
                $cpuDeltaSeconds += [Math]::Max(0, $currentCpu - [double]$previousCpuSeconds[$key])
            }
            $previousCpuSeconds[$key] = $currentCpu
            if ($process.PSObject.Properties.Name -contains "Responding" -and -not $process.Responding) {
                $responding = $false
            }
        } catch {
            $responding = $false
        }
    }
    $elapsedSeconds = if ($previousSampleAt) {
        [Math]::Max(0.001, ($SampleAt - $previousSampleAt).TotalSeconds)
    } else {
        1.0
    }
    return [pscustomobject]@{
        Count = @($Processes).Count
        MemoryMb = [Math]::Round($memoryBytes / 1MB, 2)
        CpuPercent = [Math]::Round(($cpuDeltaSeconds / $elapsedSeconds) * 100 / $logicalProcessorCount, 2)
        Responding = $responding
    }
}

function Get-NetworkTotals {
    $received = 0.0
    $sent = 0.0
    try {
        foreach ($adapter in (Get-NetAdapterStatistics -ErrorAction Stop)) {
            $received += [double]$adapter.ReceivedBytes
            $sent += [double]$adapter.SentBytes
        }
    } catch {
        return [pscustomobject]@{ Received = 0.0; Sent = 0.0 }
    }
    return [pscustomobject]@{ Received = $received; Sent = $sent }
}

function Get-GpuMetrics {
    $command = Get-Command "nvidia-smi.exe" -ErrorAction SilentlyContinue
    if (-not $command) {
        return [pscustomobject]@{ DecodePercent = ""; MemoryMb = "" }
    }
    try {
        $line = @(& $command.Source "--query-gpu=utilization.decoder,memory.used" "--format=csv,noheader,nounits" 2>$null)[0]
        $parts = $line -split ","
        return [pscustomobject]@{
            DecodePercent = [double]$parts[0].Trim()
            MemoryMb = [double]$parts[1].Trim()
        }
    } catch {
        return [pscustomobject]@{ DecodePercent = ""; MemoryMb = "" }
    }
}

function Get-DjangoProcesses {
    try {
        $processIds = @(
            Get-CimInstance Win32_Process -ErrorAction Stop |
                Where-Object {
                    $_.Name -in @("python.exe", "pythonw.exe") -and
                    [string]$_.CommandLine -match '(manage\.py\s+runserver|daphne|gunicorn)'
                } |
                ForEach-Object { [int]$_.ProcessId }
        )
        return @($processIds | ForEach-Object {
            Get-Process -Id $_ -ErrorAction SilentlyContinue
        })
    } catch {
        return @()
    }
}

function Get-MediaMtxMetrics {
    $result = [ordered]@{
        Reachable = $false
        ReadyPathCount = 0
        WebRtcSessionCount = 0
        StressWebRtcSessionCount = 0
        TotalReadyPathCount = 0
        ActiveReaderCount = 0
        TotalActiveReaderCount = 0
        Cam001ReadyPathCount = 0
        Cam001ReaderCount = 0
    }
    try {
        $pathsPayload = Invoke-RestMethod -Uri "$($MediaMtxApiBaseUrl.TrimEnd('/'))/v3/paths/list" -TimeoutSec 5
        $sessionsPayload = Invoke-RestMethod -Uri "$($MediaMtxApiBaseUrl.TrimEnd('/'))/v3/webrtc/sessions/list" -TimeoutSec 5
        $result.Reachable = $true
        $allPaths = @($pathsPayload.items)
        $stressPaths = @($pathsPayload.items | Where-Object { $_.name -match '^stress(0[1-9]|1[0-6])$' })
        $result.TotalReadyPathCount = @($allPaths | Where-Object { $_.ready -eq $true -or $_.online -eq $true }).Count
        $result.TotalActiveReaderCount = [int](($allPaths | ForEach-Object { @($_.readers).Count } | Measure-Object -Sum).Sum)
        $result.ReadyPathCount = @($stressPaths | Where-Object { $_.ready -eq $true -or $_.online -eq $true }).Count
        $result.ActiveReaderCount = [int](($stressPaths | ForEach-Object { @($_.readers).Count } | Measure-Object -Sum).Sum)
        $cam001Paths = @($stressPaths | Where-Object { $_.name -in @("stress01", "stress05", "stress09", "stress13") })
        $result.Cam001ReadyPathCount = @($cam001Paths | Where-Object { $_.ready -eq $true -or $_.online -eq $true }).Count
        $result.Cam001ReaderCount = [int](($cam001Paths | ForEach-Object { @($_.readers).Count } | Measure-Object -Sum).Sum)
        $sessions = @($sessionsPayload.items)
        $result.WebRtcSessionCount = if ($null -ne $sessionsPayload.itemCount) { [int]$sessionsPayload.itemCount } else { $sessions.Count }
        $result.StressWebRtcSessionCount = @($sessions | Where-Object {
            $sessionPath = if ($_.path) { $_.path } elseif ($_.pathName) { $_.pathName } else { $_.path_name }
            $sessionPath -match '^stress(0[1-9]|1[0-6])$'
        }).Count
    } catch {
        $result.Reachable = $false
    }
    return [pscustomobject]$result
}

while ((Get-Date) -lt $deadline) {
    $sampleAt = Get-Date
    $operatingSystem = Get-CimInstance Win32_OperatingSystem
    $processors = @(Get-CimInstance Win32_Processor)
    $systemCpu = [Math]::Round((($processors | Measure-Object -Property LoadPercentage -Average).Average), 2)
    $availableMemoryMb = [Math]::Round([double]$operatingSystem.FreePhysicalMemory / 1024, 2)
    $committedMemoryMb = [Math]::Round(([double]$operatingSystem.TotalVirtualMemorySize - [double]$operatingSystem.FreeVirtualMemory) / 1024, 2)

    $browserProcesses = @(Get-Process -Name "msedge", "chrome" -ErrorAction SilentlyContinue)
    $stressRecords = @(Read-StressState)
    $stressProcesses = @()
    foreach ($record in $stressRecords) {
        if (Test-StressProcessRecord -Record $record) {
            $stressProcesses += Get-Process -Id $record.ProcessId -ErrorAction SilentlyContinue
        }
    }
    $mediaMtxProcesses = @(Get-Process -Name "mediamtx" -ErrorAction SilentlyContinue)
    $allFfmpegProcesses = @(Get-Process -Name "ffmpeg" -ErrorAction SilentlyContinue)
    $djangoProcesses = @(Get-DjangoProcesses)
    $browserMetrics = Get-ProcessTotals -Processes $browserProcesses -KeyPrefix "browser" -SampleAt $sampleAt
    $ffmpegMetrics = Get-ProcessTotals -Processes $stressProcesses -KeyPrefix "stressffmpeg" -SampleAt $sampleAt
    $ffmpegAggregateMetrics = Get-ProcessTotals -Processes $allFfmpegProcesses -KeyPrefix "allffmpeg" -SampleAt $sampleAt
    $djangoMetrics = Get-ProcessTotals -Processes $djangoProcesses -KeyPrefix "django" -SampleAt $sampleAt
    $mediaMtxProcessMetrics = Get-ProcessTotals -Processes $mediaMtxProcesses -KeyPrefix "mediamtx" -SampleAt $sampleAt
    $mediaMtxMetrics = Get-MediaMtxMetrics
    $gpuMetrics = Get-GpuMetrics

    $network = Get-NetworkTotals
    $networkElapsed = if ($previousSampleAt) { [Math]::Max(0.001, ($sampleAt - $previousSampleAt).TotalSeconds) } else { 1.0 }
    $networkRxMbps = 0.0
    $networkTxMbps = 0.0
    if ($previousNetworkBytes) {
        $networkRxMbps = [Math]::Round((($network.Received - $previousNetworkBytes.Received) * 8 / 1MB) / $networkElapsed, 3)
        $networkTxMbps = [Math]::Round((($network.Sent - $previousNetworkBytes.Sent) * 8 / 1MB) / $networkElapsed, 3)
    }
    $previousNetworkBytes = $network

    $browserState = $null
    $browserStatePath = Join-Path (Get-StressRuntimeDirectory) "browser_state.json"
    if (Test-Path -LiteralPath $browserStatePath -PathType Leaf) {
        try {
            $candidateBrowserState = Get-Content -LiteralPath $browserStatePath -Raw | ConvertFrom-Json
            if ($candidateBrowserState -isnot [System.Array]) {
                $browserState = $candidateBrowserState
            }
        } catch {
            Write-Warning ("Skipped invalid browser stress state: {0}" -f $_.Exception.Message)
            $browserState = $null
        }
    }
    $visibleStreamCount = if ($browserState) { [int]$browserState.visible_stream_count } else { 0 }
    $loadingPaths = if ($browserState) { [string]$browserState.loading_paths } else { "" }
    $oldestLoadingStartedAt = if ($browserState) { [string]$browserState.oldest_loading_started_at } else { "" }
    $browserTelemetryTimestamp = if ($browserState) { [string]$browserState.timestamp } else { "" }
    $recoveredPath = if ($browserState) { [string]$browserState.recovered_path } else { "" }
    $recoveryDurationMs = if ($browserState -and $browserState.recovery_duration_ms) { [int]$browserState.recovery_duration_ms } else { 0 }
    $cam001LoadingPaths = @($loadingPaths -split "," | Where-Object { $_ -in @("stress01", "stress05", "stress09", "stress13") }) -join ","
    $transcodingCount = @($stressRecords | Where-Object { $_.BridgeMode -ne "copy" }).Count
    $djangoReachable = $false
    try {
        $dashboardResponse = Invoke-WebRequest -Uri $DashboardUrl -UseBasicParsing -TimeoutSec 5
        $djangoReachable = $dashboardResponse.StatusCode -lt 500
    } catch {
        $djangoReachable = $false
    }

    $elapsedSeconds = [int]($sampleAt - $startedAt).TotalSeconds
    $phase = if ($SmokeMode) {
        "collector_smoke"
    } elseif ($elapsedSeconds -lt 300) {
        "phase_1_9_streams"
    } elseif ($elapsedSeconds -lt 600) {
        "phase_2_16_streams"
    } elseif ($elapsedSeconds -lt 900) {
        "phase_3_layout_switching"
    } else {
        "phase_4_16_grid_soak"
    }
    $expectedStreams = if ($SmokeMode) { $stressProcesses.Count } elseif ($elapsedSeconds -lt 300) { 9 } else { 16 }
    $row = [pscustomobject][ordered]@{
        timestamp = $sampleAt.ToUniversalTime().ToString("o")
        elapsed_seconds = $elapsedSeconds
        phase = $phase
        expected_streams = $expectedStreams
        system_cpu_percent = $systemCpu
        system_available_memory_mb = $availableMemoryMb
        system_committed_memory_mb = $committedMemoryMb
        browser_process_count = $browserMetrics.Count
        browser_memory_mb = $browserMetrics.MemoryMb
        browser_responding = $browserMetrics.Responding
        ffmpeg_process_count = $ffmpegMetrics.Count
        ffmpeg_memory_mb = $ffmpegMetrics.MemoryMb
        ffmpeg_cpu_percent = $ffmpegMetrics.CpuPercent
        ffmpeg_aggregate_process_count = $ffmpegAggregateMetrics.Count
        ffmpeg_aggregate_memory_mb = $ffmpegAggregateMetrics.MemoryMb
        ffmpeg_aggregate_cpu_percent = $ffmpegAggregateMetrics.CpuPercent
        transcoding_count = $transcodingCount
        django_process_count = $djangoMetrics.Count
        django_memory_mb = $djangoMetrics.MemoryMb
        django_cpu_percent = $djangoMetrics.CpuPercent
        mediamtx_cpu_percent = $mediaMtxProcessMetrics.CpuPercent
        mediamtx_memory_mb = $mediaMtxProcessMetrics.MemoryMb
        mediamtx_reachable = $mediaMtxMetrics.Reachable
        django_reachable = $djangoReachable
        ready_stress_path_count = $mediaMtxMetrics.ReadyPathCount
        mediamtx_ready_path_count = $mediaMtxMetrics.TotalReadyPathCount
        webrtc_session_count = $mediaMtxMetrics.WebRtcSessionCount
        stress_webrtc_session_count = $mediaMtxMetrics.StressWebRtcSessionCount
        active_reader_count = $mediaMtxMetrics.ActiveReaderCount
        mediamtx_active_reader_count = $mediaMtxMetrics.TotalActiveReaderCount
        visible_stream_count = $visibleStreamCount
        loading_paths = $loadingPaths
        oldest_loading_started_at = $oldestLoadingStartedAt
        browser_telemetry_timestamp = $browserTelemetryTimestamp
        recovered_path = $recoveredPath
        recovery_duration_ms = $recoveryDurationMs
        cam001_ready_path_count = $mediaMtxMetrics.Cam001ReadyPathCount
        cam001_reader_count = $mediaMtxMetrics.Cam001ReaderCount
        cam001_loading_paths = $cam001LoadingPaths
        network_rx_mbps = $networkRxMbps
        network_tx_mbps = $networkTxMbps
        gpu_video_decode_percent = $gpuMetrics.DecodePercent
        gpu_memory_mb = $gpuMetrics.MemoryMb
    }
    $rows.Add($row)
    $row | Export-Csv -LiteralPath $csvPath -NoTypeInformation -Append -Encoding utf8
    Write-Host ("Sample {0}: ffmpeg={1} ready={2} stress_sessions={3} readers={4} visible={5}" -f $rows.Count, $row.ffmpeg_process_count, $row.ready_stress_path_count, $row.stress_webrtc_session_count, $row.active_reader_count, $row.visible_stream_count)
    $previousSampleAt = $sampleAt

    $remainingSeconds = [Math]::Min($SampleSeconds, [Math]::Max(0, ($deadline - (Get-Date)).TotalSeconds))
    if ($remainingSeconds -gt 0) {
        Start-Sleep -Seconds $remainingSeconds
    }
}

$failures = [System.Collections.Generic.List[string]]::new()
$finalRow = $rows[$rows.Count - 1]
$expectedSamples = [Math]::Floor(($DurationMinutes * 60) / $SampleSeconds)
if ($rows.Count -lt [Math]::Floor($expectedSamples * 0.9)) { $failures.Add("missing_metric_samples") }
if (-not $SmokeMode) {
    if ($finalRow.ready_stress_path_count -ne 16) { $failures.Add("final_ready_path_count_not_16") }
    if ($finalRow.ffmpeg_process_count -ne 16) { $failures.Add("final_ffmpeg_count_not_16") }
    if ($finalRow.stress_webrtc_session_count -ne 16) { $failures.Add("final_stress_webrtc_session_count_not_16") }
    if ($finalRow.active_reader_count -ne 16) { $failures.Add("final_reader_count_not_16") }
    if ($finalRow.visible_stream_count -ne 16) { $failures.Add("final_visible_stream_count_not_16") }
    if (@($rows | Where-Object { $_.transcoding_count -ne 0 }).Count -gt 0) { $failures.Add("transcoding_detected") }
    if (@($rows | Where-Object { $_.ffmpeg_process_count -gt 16 }).Count -gt 0) { $failures.Add("ffmpeg_process_leak") }
    if (@($rows | Where-Object { $_.stress_webrtc_session_count -gt 16 }).Count -gt 0) { $failures.Add("webrtc_session_leak") }
    if (@($rows | Where-Object { $_.active_reader_count -gt 16 }).Count -gt 0) { $failures.Add("reader_leak") }
    if (@($rows | Where-Object { $_.browser_responding -ne $true }).Count -gt 0) { $failures.Add("browser_not_responding") }
    if (@($rows | Where-Object { $_.mediamtx_reachable -ne $true }).Count -gt 0) { $failures.Add("mediamtx_unreachable") }
    if (@($rows | Where-Object { $_.django_reachable -ne $true }).Count -gt 0) { $failures.Add("django_unreachable") }
    if (-not [string]::IsNullOrWhiteSpace([string]$finalRow.loading_paths)) { $failures.Add("persistent_loading_stream") }
    if (($rows | Measure-Object -Property recovery_duration_ms -Maximum).Maximum -gt 30000) { $failures.Add("recovery_exceeded_30_seconds") }
}
$releaseCheckRows = @($rows | Where-Object {
    ($_.elapsed_seconds -ge 625 -and $_.elapsed_seconds -le 655) -or
    ($_.elapsed_seconds -ge 685 -and $_.elapsed_seconds -le 715) -or
    ($_.elapsed_seconds -ge 805 -and $_.elapsed_seconds -le 835)
})
if (@($releaseCheckRows | Where-Object {
    $_.stress_webrtc_session_count -gt $_.visible_stream_count -or
    $_.active_reader_count -gt $_.visible_stream_count
}).Count -gt 0) { $failures.Add("hidden_session_or_reader_not_released_after_grace") }

$soakRows = @($rows | Where-Object { $_.elapsed_seconds -ge 900 })
if ($soakRows.Count -ge 2) {
    $browserGrowth = [double]$soakRows[-1].browser_memory_mb - [double]$soakRows[0].browser_memory_mb
    $mediaMtxGrowth = [double]$soakRows[-1].mediamtx_memory_mb - [double]$soakRows[0].mediamtx_memory_mb
    if ($browserGrowth -gt 1024) { $failures.Add("browser_memory_growth_over_1024_mb") }
    if ($mediaMtxGrowth -gt 512) { $failures.Add("mediamtx_memory_growth_over_512_mb") }
    $browserIncreases = 0
    $mediaMtxIncreases = 0
    for ($index = 1; $index -lt $soakRows.Count; $index++) {
        if ([double]$soakRows[$index].browser_memory_mb -gt [double]$soakRows[$index - 1].browser_memory_mb) { $browserIncreases++ }
        if ([double]$soakRows[$index].mediamtx_memory_mb -gt [double]$soakRows[$index - 1].mediamtx_memory_mb) { $mediaMtxIncreases++ }
    }
    $transitionCount = $soakRows.Count - 1
    if ($browserGrowth -gt 256 -and ($browserIncreases / $transitionCount) -ge 0.8) { $failures.Add("browser_memory_monotonic_growth") }
    if ($mediaMtxGrowth -gt 128 -and ($mediaMtxIncreases / $transitionCount) -ge 0.8) { $failures.Add("mediamtx_memory_monotonic_growth") }
    if ([int]$soakRows[-1].browser_process_count -gt ([int]$soakRows[0].browser_process_count + 4)) { $failures.Add("browser_process_growth") }
}

$result = if ($failures.Count -eq 0) { "PASS" } else { "FAIL" }
$summary = @(
    "KRTC V6.8 Lab Multi-Stream Stress Summary",
    "Result=$result",
    "StartedAt=$($startedAt.ToUniversalTime().ToString('o'))",
    "CompletedAt=$((Get-Date).ToUniversalTime().ToString('o'))",
    "SampleCount=$($rows.Count)",
    "FinalReadyStressPaths=$($finalRow.ready_stress_path_count)",
    "FinalStressWebRtcSessions=$($finalRow.stress_webrtc_session_count)",
    "FinalActiveReaders=$($finalRow.active_reader_count)",
    "FinalStressFfmpegCount=$($finalRow.ffmpeg_process_count)",
    "FinalVisibleStreams=$($finalRow.visible_stream_count)",
    "TranscodingCount=$($finalRow.transcoding_count)",
    "FailureReasons=$($failures -join ',')",
    "ThresholdBrowserMemoryGrowthMb=1024",
    "ThresholdMediaMtxMemoryGrowthMb=512",
    "ThresholdRecoveryDurationMs=30000",
    "ManualVisualValidationRequired=true",
    "ManualCriteria=no_persistent_black_screen,no_browser_freeze,no_aio_freeze"
)
$summary | Set-Content -LiteralPath $summaryPath -Encoding ascii
Remove-StaleStressTempFiles
Write-Host ("Stress metrics completed: Result={0} CSV={1} Summary={2}" -f $result, $csvPath, $summaryPath)
if ($result -ne "PASS") {
    Set-Content -LiteralPath $exitCodePath -Value "1" -Encoding ascii
    exit 1
}
Set-Content -LiteralPath $exitCodePath -Value "0" -Encoding ascii
