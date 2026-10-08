import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse


@override_settings(
    DEBUG=True,
    KRTC_MEDIAMTX_WEBRTC_BASE_URL="http://127.0.0.1:8889",
    KRTC_MEDIAMTX_API_BASE_URL="http://127.0.0.1:9997",
)
class LabStressViewTests(TestCase):
    """驗證Lab壓測頁的隔離、權限與安全診斷資料。"""

    def setUp(self):
        self.user = get_user_model().objects.create_superuser(
            username="stress-admin",
            password="Pass1234!",
            email="stress@example.com",
        )
        self.client.force_login(self.user)

    def test_lab_page_has_sixteen_safe_webrtc_players_and_shared_helper(self):
        response = self.client.get(reverse("dashboard:lab_stress_monitor"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "data-stress-player", count=16)
        self.assertContains(response, "stress01")
        self.assertContains(response, "stress16")
        self.assertNotContains(response, "rtsp://")
        content = response.content.decode("utf-8")
        self.assertLess(
            content.index("js/mediamtx_player.js"),
            content.index("js/lab_stress_monitor.js"),
        )

    @override_settings(DEBUG=False)
    def test_lab_page_is_hidden_outside_debug_mode(self):
        response = self.client.get(reverse("dashboard:lab_stress_monitor"))

        self.assertEqual(response.status_code, 404)

    @patch("apps.dashboard.stress._read_json")
    def test_status_api_reports_only_stress_path_runtime(self, read_json):
        path_items = [
            {
                "name": "stress01",
                "ready": True,
                "readers": [{"type": "webRTCSession"}],
            },
            {
                "name": "cam001",
                "ready": True,
                "readers": [{"type": "webRTCSession"}],
            },
        ]
        read_json.side_effect = [
            {"items": path_items},
            {
                "itemCount": 2,
                "items": [
                    {"path": "stress01"},
                    {"path": "cam001"},
                ],
            },
        ]

        response = self.client.get(reverse("dashboard:lab_stress_status_api"))

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["ready_stress_path_count"], 1)
        self.assertEqual(payload["stress_webrtc_session_count"], 1)
        self.assertEqual(payload["active_reader_count"], 1)
        self.assertNotIn("cam001", payload["paths"])

    def test_telemetry_validates_and_writes_runtime_state_without_database(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            state_path = Path(temporary_directory) / "browser_state.json"
            with patch(
                "apps.dashboard.stress._stress_runtime_path",
                return_value=state_path,
            ):
                response = self.client.post(
                    reverse("dashboard:lab_stress_telemetry_api"),
                    {
                        "visible_stream_count": 16,
                        "loading_paths": "stress01,stress13",
                        "recovered_path": "stress01",
                        "recovery_duration_ms": 1200,
                        "event": "recovered",
                        "timestamp": "2026-10-07T01:02:03Z",
                        "oldest_loading_started_at": "2026-10-07T01:02:01Z",
                    },
                )

            self.assertEqual(response.status_code, 200)
            payload = json.loads(state_path.read_text(encoding="ascii"))
            self.assertEqual(payload["visible_stream_count"], 16)
            self.assertEqual(payload["loading_paths"], "stress01,stress13")

    def test_telemetry_rejects_non_stress_path(self):
        response = self.client.post(
            reverse("dashboard:lab_stress_telemetry_api"),
            {
                "visible_stream_count": 1,
                "loading_paths": "cam001",
                "event": "loading",
            },
        )

        self.assertEqual(response.status_code, 400)


class LabStressSourceContractTests(SimpleTestCase):
    """驗證壓測腳本維持copy-only、隔離與可回收契約。"""

    def setUp(self):
        self.project_root = Path(settings.BASE_DIR)
        self.tools_root = self.project_root / "tools" / "stress"
        self.common = (self.tools_root / "Stress_Common.ps1").read_text(
            encoding="utf-8"
        )
        self.metrics = (
            self.tools_root / "Collect_Stress_Metrics.ps1"
        ).read_text(encoding="utf-8")
        self.runner = (
            self.tools_root / "Start_30_Minute_Stress.ps1"
        ).read_text(encoding="utf-8")
        self.browser_script = (
            self.project_root / "static/js/lab_stress_monitor.js"
        ).read_text(encoding="utf-8")

    def test_logical_mapping_rotates_four_physical_h264_sources(self):
        self.assertIn("(($index - 1) % 4) + 1", self.common)
        self.assertIn('"CAM-{0:D3}" -f $sourceIndex', self.common)
        self.assertIn('SourceCodec -ne "H264"', self.common)
        self.assertIn('"stress{0:D2}" -f $index', self.common)

    def test_publishers_are_copy_only_video_only_and_rtsp_tcp(self):
        for token in (
            '"-map", "0:v:0"',
            '"-c:v", "copy"',
            '"-an", "-dn"',
            '"-rtsp_transport", "tcp"',
        ):
            self.assertIn(token, self.common)
        for token in ("libx264", '"-vf"', '"-r"'):
            self.assertNotIn(token, self.common)

    def test_runtime_state_has_no_source_url_or_credentials(self):
        record_section = self.common[
            self.common.index("$record = [ordered]@{"):
            self.common.index("$existingByPath[$path]")
        ]
        self.assertNotIn("sourceUrl", record_section)
        self.assertNotIn("Password", record_section)
        self.assertNotIn("Write-Host $sourceUrl", self.common)

    def test_stop_uses_pid_start_time_and_only_ffmpeg(self):
        self.assertIn("ProcessStartedAt", self.common)
        self.assertIn(
            '$process.ProcessName -ne [string]$Record.ProcessName',
            self.common,
        )
        self.assertIn("Stop-StressProcessRecord", self.common)
        stop_script = (self.tools_root / "Stop_Stress.ps1").read_text(
            encoding="utf-8"
        )
        self.assertNotIn('Get-Process -Name "mediamtx"', stop_script)
        self.assertNotIn('Get-Process -Name "python"', stop_script)

    def test_browser_layout_releases_hidden_players_without_refresh(self):
        self.assertIn("window.KRTCMediaPlayer.activateWebRTC", self.browser_script)
        self.assertIn("window.KRTCMediaPlayer.releaseWebRTC", self.browser_script)
        self.assertIn('tile.hidden = !shouldShow', self.browser_script)
        self.assertIn('window.addEventListener("pagehide"', self.browser_script)
        self.assertNotIn("window.location.reload", self.browser_script)
        self.assertNotIn("mjpeg", self.browser_script.lower())

    def test_thirty_minute_profile_has_required_phases_and_cleanup(self):
        self.assertIn("Start-StressPublishers -Count 9", self.runner)
        self.assertIn("Start-StressPublishers -Count 16", self.runner)
        self.assertIn("$second -lt 300", self.runner)
        self.assertIn("$second -lt 1500", self.runner)
        self.assertIn("finally", self.runner)
        self.assertIn("Stop-AllStressPublishers", self.runner)

    def test_metrics_cover_required_resources_and_leak_thresholds(self):
        for metric in (
            "phase",
            "expected_streams",
            "system_cpu_percent",
            "system_available_memory_mb",
            "system_committed_memory_mb",
            "browser_process_count",
            "browser_memory_mb",
            "ffmpeg_process_count",
            "ffmpeg_memory_mb",
            "ffmpeg_cpu_percent",
            "ffmpeg_aggregate_process_count",
            "ffmpeg_aggregate_memory_mb",
            "ffmpeg_aggregate_cpu_percent",
            "django_process_count",
            "django_memory_mb",
            "django_cpu_percent",
            "mediamtx_cpu_percent",
            "mediamtx_memory_mb",
            "mediamtx_ready_path_count",
            "mediamtx_active_reader_count",
            "ready_stress_path_count",
            "webrtc_session_count",
            "active_reader_count",
            "visible_stream_count",
            "network_rx_mbps",
            "network_tx_mbps",
            "gpu_video_decode_percent",
            "gpu_memory_mb",
            "cam001_ready_path_count",
            "cam001_reader_count",
            "cam001_loading_paths",
            "oldest_loading_started_at",
            "recovery_duration_ms",
        ):
            self.assertIn(metric, self.metrics)
        self.assertIn("browser_memory_growth_over_1024_mb", self.metrics)
        self.assertIn("mediamtx_memory_growth_over_512_mb", self.metrics)
        self.assertIn("persistent_loading_stream", self.metrics)
        self.assertIn("browser_memory_monotonic_growth", self.metrics)
        self.assertIn("hidden_session_or_reader_not_released_after_grace", self.metrics)

    def test_state_reader_normalizes_arrays_and_rejects_invalid_records(self):
        powershell_hosts = [
            host
            for host in (
                shutil.which("powershell.exe"),
                shutil.which("pwsh.exe"),
            )
            if host
        ]
        self.assertTrue(powershell_hosts)

        valid_record = {
            "Path": "stress01",
            "SourceCamera": "CAM-001",
            "ProcessName": "ffmpeg",
            "ProcessId": 123,
            "ProcessStartedAt": "2026-10-08T01:02:03Z",
            "StartedAt": "2026-10-08T01:02:04Z",
        }
        second_record = {**valid_record, "Path": "stress02", "ProcessId": 456}
        invalid_record = {**valid_record, "Path": "stress03", "ProcessId": [7, 8]}

        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_path = Path(temporary_directory)
            state_path = temporary_path / "stress_processes.json"
            state_path.write_text(
                json.dumps([valid_record, second_record, invalid_record]),
                encoding="ascii",
            )
            probe_path = temporary_path / "probe.ps1"
            common_path = str(self.tools_root / "Stress_Common.ps1").replace(
                "'", "''"
            )
            state_path_literal = str(state_path).replace("'", "''")
            probe_path.write_text(
                "\n".join(
                    (
                        f". '{common_path}'",
                        "function Get-StressStatePath {",
                        f"    return '{state_path_literal}'",
                        "}",
                        "$records = @(Read-StressState)",
                        "$result = [pscustomobject]@{",
                        "    Count = $records.Count",
                        "    AllObjects = @($records | Where-Object { $_ -is [pscustomobject] }).Count -eq $records.Count",
                        "    ProcessIds = @($records | ForEach-Object { $_.ProcessId })",
                        "    ArrayAccepted = Test-StressProcessRecord -Record (, $records)",
                        "}",
                        "$result | ConvertTo-Json -Compress",
                    )
                ),
                encoding="ascii",
            )

            for powershell_host in powershell_hosts:
                completed = subprocess.run(
                    [
                        powershell_host,
                        "-NoProfile",
                        "-ExecutionPolicy",
                        "Bypass",
                        "-File",
                        str(probe_path),
                    ],
                    check=True,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                )
                json_line = next(
                    line
                    for line in reversed(completed.stdout.splitlines())
                    if line.startswith("{")
                )
                payload = json.loads(json_line)
                self.assertEqual(payload["Count"], 2)
                self.assertTrue(payload["AllObjects"])
                self.assertEqual(payload["ProcessIds"], [123, 456])
                self.assertFalse(payload["ArrayAccepted"])

    def test_collector_supervision_outputs_and_temp_cleanup_contract(self):
        smoke = (
            self.tools_root / "Start_1_Minute_Collector_Smoke.ps1"
        ).read_text(encoding="utf-8")

        self.assertNotIn("[int]$Record.ProcessId", self.common)
        self.assertIn("[int]::TryParse", self.common)
        self.assertIn("ConvertTo-NormalizedStressRecord", self.common)
        self.assertIn(
            "ConvertTo-Json -InputObject @($normalizedRecords) -Depth 4",
            self.common,
        )
        self.assertNotIn("ConvertTo-Json -Depth4", self.common)
        self.assertIn(
            "[System.IO.File]::Replace($temporaryPath, $statePath, "
            "$backupPath, $true)",
            self.common,
        )
        self.assertIn("Resolve-StressRuntimeFilePath", self.common)
        self.assertNotIn(
            "[System.IO.File]::Replace($temporaryPath, $statePath, $null)",
            self.common,
        )
        self.assertIn("Remove-StaleStressTempFiles", self.common)
        self.assertIn("RedirectStandardOutput", self.runner)
        self.assertIn("RedirectStandardError", self.runner)
        self.assertIn("Assert-StressCollectorRunning", self.runner)
        self.assertIn("run_metadata.json", self.metrics)
        self.assertIn("collector.stdout.log", self.metrics)
        self.assertIn("collector.stderr.log", self.metrics)
        self.assertIn('"-DurationMinutes", "1"', smoke)
        self.assertIn('"-SampleSeconds", "10"', smoke)
        self.assertIn("$samples.Count -lt 5", smoke)

    def test_atomic_state_write_on_windows_powershell_and_powershell_7(self):
        powershell_hosts = [
            host
            for host in (
                shutil.which("powershell.exe"),
                shutil.which("pwsh.exe"),
            )
            if host
        ]
        self.assertTrue(powershell_hosts)

        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_path = Path(temporary_directory)
            probe_path = temporary_path / "atomic_write_probe.ps1"
            common_path = str(self.tools_root / "Stress_Common.ps1").replace(
                "'", "''"
            )
            runtime_literal = str(temporary_path).replace("'", "''")
            probe_path.write_text(
                "\n".join(
                    (
                        f". '{common_path}'",
                        "function Get-StressRuntimeDirectory {",
                        f"    return '{runtime_literal}'",
                        "}",
                        "function Get-StressStatePath {",
                        "    return Join-Path (Get-StressRuntimeDirectory) 'stress_processes.json'",
                        "}",
                        "$started = '2026-10-08T01:02:03Z'",
                        "$one = [pscustomobject]@{ Path = 'stress01'; SourceCamera = 'CAM-001'; ProcessName = 'ffmpeg'; ProcessId = 101; ProcessStartedAt = $started; StartedAt = $started }",
                        "$two = [pscustomobject]@{ Path = 'stress02'; SourceCamera = 'CAM-002'; ProcessName = 'ffmpeg'; ProcessId = 202; ProcessStartedAt = $started; StartedAt = $started }",
                        "Write-StressState -Records @($one)",
                        "$first = @(Read-StressState)",
                        "$firstJsonValid = $null -ne (Get-Content -LiteralPath (Get-StressStatePath) -Raw | ConvertFrom-Json)",
                        "Write-StressState -Records @($one, $two)",
                        "$second = @(Read-StressState)",
                        "Write-StressState -Records @($two)",
                        "$third = @(Read-StressState)",
                        "Write-StressState -Records @()",
                        "$empty = @(Read-StressState)",
                        "$statePath = Get-StressStatePath",
                        "$beforeMalformed = Get-Content -LiteralPath $statePath -Raw",
                        "$malformedRejected = $false",
                        "function Get-StressStatePath { return @('bad-one', 'bad-two') }",
                        "try { Write-StressState -Records @($one) } catch { $malformedRejected = $true }",
                        "function Get-StressStatePath { return Join-Path (Get-StressRuntimeDirectory) 'stress_processes.json' }",
                        "$afterMalformed = Get-Content -LiteralPath $statePath -Raw",
                        "$leftovers = @(Get-ChildItem -LiteralPath (Get-StressRuntimeDirectory) -File | Where-Object { $_.Name -match '^\\.stress_processes\\.json\\.[0-9a-f]+\\.(tmp|bak)$' })",
                        "$result = [pscustomobject]@{",
                        "    FirstCount = $first.Count",
                        "    FirstJsonValid = $firstJsonValid",
                        "    FirstIsNormalizedObject = $first[0] -is [pscustomobject]",
                        "    SecondCount = $second.Count",
                        "    ThirdCount = $third.Count",
                        "    ThirdProcessId = $third[0].ProcessId",
                        "    EmptyCount = $empty.Count",
                        "    MalformedRejected = $malformedRejected",
                        "    DestinationPreserved = $beforeMalformed -eq $afterMalformed",
                        "    LeftoverCount = $leftovers.Count",
                        "    StatePathType = $statePath.GetType().FullName",
                        "    StatePathRooted = [System.IO.Path]::IsPathRooted($statePath)",
                        "}",
                        "$result | ConvertTo-Json -Compress",
                    )
                ),
                encoding="ascii",
            )

            for powershell_host in powershell_hosts:
                completed = subprocess.run(
                    [
                        powershell_host,
                        "-NoProfile",
                        "-ExecutionPolicy",
                        "Bypass",
                        "-File",
                        str(probe_path),
                    ],
                    check=True,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                )
                json_line = next(
                    line
                    for line in reversed(completed.stdout.splitlines())
                    if line.startswith("{")
                )
                payload = json.loads(json_line)
                self.assertEqual(payload["FirstCount"], 1)
                self.assertTrue(payload["FirstJsonValid"])
                self.assertTrue(payload["FirstIsNormalizedObject"])
                self.assertEqual(payload["SecondCount"], 2)
                self.assertEqual(payload["ThirdCount"], 1)
                self.assertEqual(payload["ThirdProcessId"], 202)
                self.assertEqual(payload["EmptyCount"], 0)
                self.assertTrue(payload["MalformedRejected"])
                self.assertTrue(payload["DestinationPreserved"])
                self.assertEqual(payload["LeftoverCount"], 0)
                self.assertEqual(payload["StatePathType"], "System.String")
                self.assertTrue(payload["StatePathRooted"])

    def test_stop_flow_removes_only_two_state_managed_publishers(self):
        powershell_hosts = [
            host
            for host in (
                shutil.which("powershell.exe"),
                shutil.which("pwsh.exe"),
            )
            if host
        ]
        self.assertTrue(powershell_hosts)
        ffmpeg_path = shutil.which("ffmpeg.exe")
        if ffmpeg_path is None:
            installed_ffmpeg = Path("C:/Program Files/ffmpeg/bin/ffmpeg.exe")
            if installed_ffmpeg.is_file():
                ffmpeg_path = str(installed_ffmpeg)
        self.assertIsNotNone(ffmpeg_path)

        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_path = Path(temporary_directory)
            probe_path = temporary_path / "managed_stop_probe.ps1"
            common_path = str(self.tools_root / "Stress_Common.ps1").replace(
                "'", "''"
            )
            runtime_literal = str(temporary_path).replace("'", "''")
            ffmpeg_literal = str(ffmpeg_path).replace("'", "''")
            probe_path.write_text(
                "\n".join(
                    (
                        f". '{common_path}'",
                        "function Get-StressRuntimeDirectory {",
                        f"    return '{runtime_literal}'",
                        "}",
                        "function Get-StressStatePath {",
                        "    return Join-Path (Get-StressRuntimeDirectory) 'stress_processes.json'",
                        "}",
                        "$baselineIds = @(Get-Process -Name 'ffmpeg' -ErrorAction SilentlyContinue | ForEach-Object { $_.Id })",
                        "$publishers = @()",
                        "try {",
                        "    foreach ($index in 1..2) {",
                        f"        $publisher = Start-Process -FilePath '{ffmpeg_literal}' -ArgumentList @('-hide_banner', '-loglevel', 'error', '-re', '-f', 'lavfi', '-i', 'color=c=black:s=16x16:r=1', '-f', 'null', 'NUL') -PassThru -WindowStyle Hidden",
                        "        $publishers += $publisher",
                        "    }",
                        "    $startedAt = (Get-Date).ToUniversalTime().ToString('o')",
                        "    $records = @(for ($index = 0; $index -lt $publishers.Count; $index++) {",
                        "        [pscustomobject]@{",
                        "            Path = ('stress{0:D2}' -f ($index + 1))",
                        "            SourceCamera = ('CAM-{0:D3}' -f ($index + 1))",
                        "            ProcessName = 'ffmpeg'",
                        "            ProcessId = $publishers[$index].Id",
                        "            ProcessStartedAt = $publishers[$index].StartTime.ToUniversalTime().ToString('o')",
                        "            StartedAt = $startedAt",
                        "        }",
                        "    })",
                        "    Write-StressState -Records $records",
                        "    $stateExistsBeforeStop = Test-Path -LiteralPath (Get-StressStatePath) -PathType Leaf",
                        "    $stateRecords = @(Read-StressState)",
                        "    $stateCountBeforeStop = $stateRecords.Count",
                        "    $recordDiagnostics = @($stateRecords | ForEach-Object {",
                        "        $actualProcess = Get-Process -Id $_.ProcessId -ErrorAction SilentlyContinue",
                        "        [pscustomobject]@{ ExpectedName = $_.ProcessName; ActualName = $actualProcess.ProcessName; StartDelta = [Math]::Abs(($actualProcess.StartTime.ToUniversalTime() - ([DateTime]$_.ProcessStartedAt).ToUniversalTime()).TotalSeconds) }",
                        "    })",
                        "    $validCountBeforeStop = @($stateRecords | Where-Object { Test-StressProcessRecord -Record $_ }).Count",
                        "    Stop-AllStressPublishers",
                        "    foreach ($publisher in $publishers) { $publisher.WaitForExit(5000) | Out-Null }",
                        "    $managedRemaining = @($publishers | Where-Object { Get-Process -Id $_.Id -ErrorAction SilentlyContinue }).Count",
                        "    $baselineRemaining = @($baselineIds | Where-Object { Get-Process -Id $_ -ErrorAction SilentlyContinue }).Count",
                        "    [pscustomobject]@{",
                        "        StateExistsBeforeStop = $stateExistsBeforeStop",
                        "        StateCountBeforeStop = $stateCountBeforeStop",
                        "        ValidCountBeforeStop = $validCountBeforeStop",
                        "        RecordDiagnostics = $recordDiagnostics",
                        "        StateRemoved = -not (Test-Path -LiteralPath (Get-StressStatePath))",
                        "        ManagedRemaining = $managedRemaining",
                        "        BaselineCount = $baselineIds.Count",
                        "        BaselineRemaining = $baselineRemaining",
                        "        TempCount = @(Get-ChildItem -LiteralPath (Get-StressRuntimeDirectory) -File -ErrorAction SilentlyContinue | Where-Object { $_.Name -match '\\.tmp$' }).Count",
                        "    } | ConvertTo-Json -Compress",
                        "} finally {",
                        "    foreach ($publisher in $publishers) { Stop-Process -Id $publisher.Id -Force -ErrorAction SilentlyContinue }",
                        "}",
                    )
                ),
                encoding="ascii",
            )

            for powershell_host in powershell_hosts:
                completed = subprocess.run(
                    [
                        powershell_host,
                        "-NoProfile",
                        "-ExecutionPolicy",
                        "Bypass",
                        "-File",
                        str(probe_path),
                    ],
                    check=True,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                )
                json_line = next(
                    line
                    for line in reversed(completed.stdout.splitlines())
                    if line.startswith("{")
                )
                payload = json.loads(json_line)
                self.assertTrue(payload["StateExistsBeforeStop"])
                self.assertEqual(payload["StateCountBeforeStop"], 2)
                self.assertEqual(
                    payload["ValidCountBeforeStop"], 2, completed.stdout
                )
                self.assertTrue(payload["StateRemoved"])
                self.assertEqual(payload["ManagedRemaining"], 0)
                self.assertEqual(
                    payload["BaselineRemaining"], payload["BaselineCount"]
                )
                self.assertEqual(payload["TempCount"], 0)

    def test_lab_config_keeps_production_paths_and_adds_sixteen_stress_paths(self):
        config = (self.project_root / "config/mediamtx.lab.yml").read_text(
            encoding="utf-8"
        )
        for index in range(1, 5):
            self.assertIn(f"  cam{index:03d}:\n", config)
        for index in range(1, 17):
            self.assertIn(f"  stress{index:02d}:\n", config)

    def test_all_powershell_sources_are_ascii_and_results_are_ignored(self):
        for script_path in self.tools_root.glob("*.ps1"):
            script_path.read_bytes().decode("ascii")
        gitignore = (self.project_root / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("stress_results/", gitignore)
        self.assertIn("runtime/", gitignore)
