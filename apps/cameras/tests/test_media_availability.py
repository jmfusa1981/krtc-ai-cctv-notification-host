from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone

from apps.cameras.media_availability import (
    NETWORK_REACHABLE,
    STALE,
    UNREACHABLE,
    camera_network_snapshot,
    evaluate_media_availability,
)
from apps.cameras.models import Camera
from apps.cameras.monitor_diagnostics import collect_mediamtx_path_readiness


class CameraMediaAvailabilityTests(SimpleTestCase):
    """驗證網路快照與媒體播放狀態不再互相覆蓋。"""

    def evaluate(
        self,
        camera_code="CAM-001",
        network_reachable=True,
        network_state=NETWORK_REACHABLE,
        path_ready=True,
        bridge_state="running",
    ):
        path = camera_code.lower().replace("-", "")
        return evaluate_media_availability(
            camera_code=camera_code,
            canonical_path=path,
            effective_path=path,
            effective_bridge_state=bridge_state,
            mediamtx_reachable=True,
            path_ready=path_ready,
            metadata_available=True,
            network_reachable=network_reachable,
            network_state=network_state,
        )

    def test_tcp_reachable_and_path_ready_is_playable(self):
        result = self.evaluate()

        self.assertTrue(result["media_ready"])
        self.assertTrue(result["playback_allowed"])
        self.assertEqual(result["playback_reason"], "ready")

    def test_database_offline_but_path_ready_remains_playable(self):
        result = self.evaluate(
            network_reachable=False,
            network_state=UNREACHABLE,
        )

        self.assertFalse(result["network_reachable"])
        self.assertTrue(result["playback_allowed"])

    def test_stale_network_snapshot_does_not_block_ready_media(self):
        result = self.evaluate(
            network_reachable=False,
            network_state=STALE,
        )

        self.assertEqual(result["network_state"], STALE)
        self.assertTrue(result["playback_allowed"])

    def test_path_not_ready_is_unavailable(self):
        result = self.evaluate(path_ready=False)

        self.assertFalse(result["playback_allowed"])
        self.assertEqual(result["playback_reason"], "path_not_ready")

    def test_stale_bridge_is_unavailable(self):
        result = self.evaluate(bridge_state="stale")

        self.assertFalse(result["playback_allowed"])
        self.assertEqual(result["playback_reason"], "bridge_stale")

    def test_one_camera_failure_does_not_pollute_other_cameras(self):
        results = {
            "CAM-001": self.evaluate("CAM-001"),
            "CAM-002": self.evaluate("CAM-002", path_ready=False),
            "CAM-003": self.evaluate("CAM-003"),
        }

        self.assertTrue(results["CAM-001"]["playback_allowed"])
        self.assertFalse(results["CAM-002"]["playback_allowed"])
        self.assertTrue(results["CAM-003"]["playback_allowed"])

    def test_generic_and_sixteen_camera_codes_need_no_mapping(self):
        results = [
            self.evaluate(f"CAM-{index:03d}")
            for index in range(5, 21)
        ]

        self.assertEqual(len(results), 16)
        self.assertTrue(all(item["playback_allowed"] for item in results))
        self.assertEqual(results[0]["canonical_path"], "cam005")
        self.assertEqual(results[-1]["canonical_path"], "cam020")

    @override_settings(KRTC_CAMERA_HEALTH_STALE_SECONDS=60)
    def test_network_snapshot_marks_old_probe_stale(self):
        camera = SimpleNamespace(
            status="online",
            is_online=True,
            last_checked_at=timezone.now() - timedelta(seconds=61),
        )

        snapshot = camera_network_snapshot(camera)

        self.assertTrue(snapshot["network_reachable"])
        self.assertEqual(snapshot["network_state"], STALE)


@override_settings(
    KRTC_MONITOR_MEDIA_MODE="mediamtx",
    KRTC_MEDIAMTX_WEBRTC_BASE_URL="http://127.0.0.1:8889",
    KRTC_MEDIAMTX_PHASE1_CAMERA_CODES=("CAM-001",),
)
class CameraMediaAvailabilityIntegrationTests(TestCase):
    """驗證 DB health 與實際 bridge/path 狀態由同一 evaluator 匯合。"""

    def setUp(self):
        self.camera = Camera.objects.create(
            camera_code="CAM-001",
            name="Camera 1",
            area="A1",
            rtsp_url="rtsp://private/cam1/h264",
            status="offline",
            is_online=False,
            is_active=True,
        )

    @patch("apps.cameras.monitor_diagnostics._read_json")
    @patch("apps.cameras.monitor_diagnostics.load_bridge_statuses")
    def test_offline_database_snapshot_with_running_media_is_playable(
        self,
        load_bridges,
        read_json,
    ):
        load_bridges.return_value = [
            {
                "camera_code": "CAM-001",
                "state": "running",
                "effective_state": "running",
                "publish_path": "cam001",
                "is_canonical_path": True,
                "source_codec": "H264",
                "bridge_mode": "copy",
                "process_started_at": "2026-10-08T00:00:00Z",
            }
        ]
        read_json.return_value = {
            "items": [
                {
                    "name": "cam001",
                    "ready": True,
                    "inboundBytes": 4096,
                }
            ]
        }

        result = collect_mediamtx_path_readiness(cameras=[self.camera])
        detail = result["path_details"]["CAM-001"]

        self.assertFalse(detail["network_reachable"])
        self.assertEqual(detail["effective_state"], "running")
        self.assertTrue(detail["path_ready"])
        self.assertTrue(detail["media_ready"])
        self.assertTrue(detail["playback_allowed"])
        self.assertEqual(detail["playback_reason"], "ready")
        self.assertEqual(detail["inbound_bytes"], 4096)
