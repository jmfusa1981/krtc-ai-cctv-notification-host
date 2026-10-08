from datetime import datetime, timezone
from unittest.mock import patch

from django.test import SimpleTestCase

from apps.cameras.bridge_runtime import (
    RUNNING,
    STALE,
    ProcessSnapshot,
    effective_camera_path,
    reconcile_bridge_record,
    select_effective_bridge_statuses,
)


class BridgeRuntimeReconciliationTests(SimpleTestCase):
    """驗證 bridge effective state 完全由程序身分證據決定。"""

    started_at = datetime(2026, 10, 8, 3, 41, 49, tzinfo=timezone.utc)

    def record(self, camera_code="CAM-005", **overrides):
        values = {
            "CameraCode": camera_code,
            "SourceCodec": "H264",
            "BridgeMode": "copy",
            "PublishPath": camera_code.lower().replace("-", ""),
            "ProcessId": 505,
            "ProcessStartedAt": self.started_at.isoformat(),
            "State": "running",
            "ExitCode": None,
            "LastError": "",
        }
        values.update(overrides)
        return values

    def test_matching_live_ffmpeg_is_running(self):
        status = reconcile_bridge_record(
            self.record(),
            ProcessSnapshot(True, "ffmpeg.exe", self.started_at),
        )

        self.assertEqual(status["declared_state"], RUNNING)
        self.assertEqual(status["effective_state"], RUNNING)
        self.assertTrue(status["process_alive"])
        self.assertTrue(status["process_start_match"])

    def test_missing_pid_is_stale(self):
        status = reconcile_bridge_record(
            self.record(),
            ProcessSnapshot(False),
        )

        self.assertEqual(status["effective_state"], STALE)
        self.assertEqual(status["last_error"], "stale_process_missing")

    def test_reused_pid_is_stale(self):
        later = datetime(2026, 10, 8, 4, 0, 0, tzinfo=timezone.utc)
        status = reconcile_bridge_record(
            self.record(),
            ProcessSnapshot(True, "ffmpeg.exe", later),
        )

        self.assertEqual(status["effective_state"], STALE)
        self.assertEqual(status["last_error"], "stale_process_start_mismatch")

    def test_non_ffmpeg_process_is_stale(self):
        status = reconcile_bridge_record(
            self.record(),
            ProcessSnapshot(True, "python.exe", self.started_at),
        )

        self.assertEqual(status["effective_state"], STALE)
        self.assertEqual(status["last_error"], "stale_process_not_ffmpeg")

    def test_publish_destination_mismatch_is_stale_when_command_line_available(self):
        status = reconcile_bridge_record(
            self.record(),
            ProcessSnapshot(
                True,
                "ffmpeg.exe",
                self.started_at,
                "ffmpeg -f rtsp rtsp://127.0.0.1:8554/wrong",
            ),
        )

        self.assertEqual(status["effective_state"], STALE)
        self.assertEqual(status["last_error"], "stale_publish_path_mismatch")

    def test_stale_h265_alternate_never_overrides_live_canonical_h264(self):
        canonical = reconcile_bridge_record(
            self.record("CAM-005"),
            ProcessSnapshot(True, "ffmpeg.exe", self.started_at),
        )
        alternate = reconcile_bridge_record(
            self.record(
                "CAM-005",
                SourceCodec="H265",
                BridgeMode="transcode",
                PublishPath="cam005_b",
                ProcessId=506,
            ),
            ProcessSnapshot(False),
        )
        transition = {
            "cameras": {"CAM-005": {"active_path": "cam005_b"}}
        }

        selected = select_effective_bridge_statuses(
            [alternate, canonical],
            transition,
            ["CAM-005"],
        )

        self.assertEqual(selected[0]["publish_path"], "cam005")
        self.assertEqual(
            effective_camera_path("CAM-005", [alternate, canonical], transition),
            "cam005",
        )

    def test_one_stale_camera_does_not_affect_another_camera(self):
        stale = reconcile_bridge_record(
            self.record("CAM-005"),
            ProcessSnapshot(False),
        )
        live = reconcile_bridge_record(
            self.record("CAM-020", ProcessId=2020),
            ProcessSnapshot(True, "ffmpeg.exe", self.started_at),
        )

        selected = select_effective_bridge_statuses(
            [stale, live],
            {"cameras": {}},
            ["CAM-005", "CAM-020"],
        )

        self.assertEqual(
            {item["camera_code"]: item["effective_state"] for item in selected},
            {"CAM-005": STALE, "CAM-020": RUNNING},
        )

    @patch("apps.cameras.bridge_runtime.inspect_process")
    def test_generic_camera_codes_require_no_code_mapping(self, inspect_process):
        inspect_process.return_value = ProcessSnapshot(
            True,
            "ffmpeg.exe",
            self.started_at,
        )

        for camera_code in ("CAM-005", "CAM-020"):
            status = reconcile_bridge_record(self.record(camera_code))
            self.assertEqual(
                status["canonical_path"],
                camera_code.lower().replace("-", ""),
            )
            self.assertEqual(status["effective_state"], RUNNING)
