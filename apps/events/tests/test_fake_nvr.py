import io
import json
import tempfile
import threading
from base64 import b64encode
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone

from apps.cameras.models import Camera
from apps.events.models import Event, EventRecordingEvidence
from apps.events.services.fake_nvr import (
    FakeNvrHttpServer,
    FakeNvrState,
    fake_mp4_bytes,
)
from apps.events.services.nvr_recording import (
    create_recording_evidence,
    download_completed_export,
    refresh_export_status,
)
from apps.events.services.recording_worker import process_recording_cycle


class MutableClock:
    def __init__(self, value=1000.0):
        self.value = value

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += seconds


class FakeNvrServerMixin:
    username = "lab-user"
    password = "lab&?=@:password"

    def start_fake_server(self, *, delay_seconds=5.0):
        self.clock = MutableClock()
        self.fake_state = FakeNvrState(
            delay_seconds=delay_seconds,
            clock=self.clock,
        )
        self.fake_server = FakeNvrHttpServer(
            ("127.0.0.1", 0),
            state=self.fake_state,
            username=self.username,
            password=self.password,
        )
        self.fake_thread = threading.Thread(
            target=self.fake_server.serve_forever,
            kwargs={"poll_interval": 0.01},
            daemon=True,
        )
        self.fake_thread.start()
        self.addCleanup(self.stop_fake_server)
        self.base_url = f"http://127.0.0.1:{self.fake_server.server_address[1]}"

    def stop_fake_server(self):
        if getattr(self, "fake_server", None) is None:
            return
        self.fake_server.shutdown()
        self.fake_server.server_close()
        self.fake_thread.join(timeout=2)
        self.fake_server = None

    def request(self, path, *, username=None, password=None):
        username = self.username if username is None else username
        password = self.password if password is None else password
        authorization = b64encode(f"{username}:{password}".encode("utf-8")).decode(
            "ascii"
        )
        request = Request(
            self.base_url + path,
            headers={"Authorization": f"Basic {authorization}"},
        )
        try:
            with urlopen(request, timeout=2) as response:
                return response.status, dict(response.headers), response.read()
        except HTTPError as exc:
            return exc.code, dict(exc.headers), exc.read()

    def create_export(self, channel=1):
        query = urlencode(
            {
                "channel": channel,
                "start_time": "2026-10-05T10:00:00",
                "end_time": "2026-10-05T10:02:00",
                "format": "MP4",
            }
        )
        status, _headers, body = self.request(f"/export.cgi?{query}")
        self.assertEqual(status, 200)
        return str(json.loads(body)["ID"])


class FakeNvrHttpTests(FakeNvrServerMixin, SimpleTestCase):
    def setUp(self):
        self.start_fake_server()

    def test_cam_list_returns_deterministic_mapping(self):
        status, _headers, body = self.request("/cam_list.cgi")
        payload = json.loads(body)

        self.assertEqual(status, 200)
        self.assertEqual(
            payload["Cameras"],
            [
                {"CameraCode": "CAM-001", "IP": "192.168.6.93", "Channel": 1},
                {"CameraCode": "CAM-002", "IP": "192.168.6.90", "Channel": 2},
                {"CameraCode": "CAM-003", "IP": "192.168.6.94", "Channel": 3},
                {"CameraCode": "CAM-004", "IP": "192.168.6.92", "Channel": 4},
            ],
        )

    def test_valid_basic_auth_is_accepted(self):
        status, _headers, _body = self.request("/cam_list.cgi")

        self.assertEqual(status, 200)

    def test_invalid_basic_auth_returns_401(self):
        status, headers, body = self.request(
            "/cam_list.cgi",
            username="wrong",
            password="wrong",
        )

        self.assertEqual(status, 401)
        self.assertIn("Basic", headers["WWW-Authenticate"])
        self.assertEqual(body, b"")

    def test_export_request_creates_unique_ids(self):
        first = self.create_export(channel=1)
        second = self.create_export(channel=2)

        self.assertEqual(first, "1001")
        self.assertEqual(second, "1002")
        self.assertEqual(self.fake_state.export_count, 2)

    def test_export_request_rejects_invalid_channel_and_time(self):
        invalid_channel = urlencode(
            {
                "channel": 99,
                "start_time": "2026-10-05T10:00:00",
                "end_time": "2026-10-05T10:02:00",
                "format": "MP4",
            }
        )
        status, _headers, _body = self.request(
            f"/export.cgi?{invalid_channel}"
        )
        self.assertEqual(status, 400)

        invalid_time = urlencode(
            {
                "channel": 1,
                "start_time": "not-a-time",
                "end_time": "2026-10-05T10:02:00",
                "format": "MP4",
            }
        )
        status, _headers, _body = self.request(f"/export.cgi?{invalid_time}")
        self.assertEqual(status, 400)
        self.assertEqual(self.fake_state.export_count, 0)

    def test_status_zero_before_delay_and_one_after_delay(self):
        export_id = self.create_export()

        _status, _headers, body = self.request(f"/export.cgi?ID={export_id}")
        self.assertEqual(json.loads(body)["Status"], 0)

        self.clock.advance(5)
        _status, _headers, body = self.request(f"/export.cgi?ID={export_id}")
        self.assertEqual(json.loads(body), {"Status": 1, "FFmpeg": 0, "Rate": 100})

    def test_download_before_ready_fails(self):
        export_id = self.create_export()

        status, headers, body = self.request(
            f"/export.cgi?ID={export_id}&action=download"
        )

        self.assertEqual(status, 409)
        self.assertIn("application/json", headers["Content-Type"])
        self.assertIn("not finish", json.loads(body)["Message"])

    def test_download_after_ready_returns_nonzero_mp4(self):
        export_id = self.create_export()
        self.clock.advance(5)

        status, headers, body = self.request(
            f"/export.cgi?ID={export_id}&action=download"
        )

        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Type"], "video/mp4")
        self.assertEqual(int(headers["Content-Length"]), len(body))
        self.assertGreater(len(body), 0)
        self.assertEqual(body[4:8], b"ftyp")
        self.assertEqual(body, fake_mp4_bytes())

    def test_three_concurrent_exports_remain_isolated(self):
        with ThreadPoolExecutor(max_workers=3) as executor:
            export_ids = list(executor.map(self.create_export, (1, 2, 3)))

        self.assertEqual(set(export_ids), {"1001", "1002", "1003"})
        self.assertEqual(self.fake_state.export_count, 3)
        self.clock.advance(5)
        for export_id in export_ids:
            status, _headers, body = self.request(
                f"/export.cgi?ID={export_id}&action=download"
            )
            self.assertEqual(status, 200)
            self.assertEqual(body[4:8], b"ftyp")

    def test_logs_never_include_credentials_or_authorization(self):
        with self.assertLogs("apps.events.services.fake_nvr", level="DEBUG") as logs:
            self.request("/cam_list.cgi")

        output = "\n".join(logs.output)
        self.assertNotIn(self.username, output)
        self.assertNotIn(self.password, output)
        self.assertNotIn("Authorization", output)

    @override_settings(DEBUG=False, KRTC_PRODUCTION=True)
    def test_production_guard_rejects_command_before_bind(self):
        with self.assertRaises(CommandError):
            call_command("run_fake_nvr", port=0, stdout=io.StringIO())


@override_settings(
    DEBUG=True,
    KRTC_PRODUCTION=False,
    KRTC_NVR_RECORDING_MODE="nvr",
    KRTC_NVR_TIME_ZONE="Asia/Taipei",
    KRTC_NVR_POLL_INTERVAL_SECONDS=1,
    KRTC_NVR_EXPORT_WARNING_SECONDS=3600,
    KRTC_NVR_EXPORT_TIMEOUT_SECONDS=7200,
    KRTC_NVR_MAX_RETRIES=120,
    KRTC_NVR_REQUEST_TIMEOUT=2,
    KRTC_NVR_DOWNLOAD_TIMEOUT_SECONDS=2,
)
class FakeNvrPaoE2ETests(FakeNvrServerMixin, TestCase):
    def setUp(self):
        self.start_fake_server()
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.media_root = Path(self.temporary_directory.name) / "media"
        self.media_root.mkdir()
        self.media_override = override_settings(MEDIA_ROOT=self.media_root)
        self.media_override.enable()
        self.addCleanup(self.media_override.disable)
        self.addCleanup(self.temporary_directory.cleanup)
        self.camera = Camera.objects.create(
            camera_code="CAM-001",
            name="Fake NVR Camera",
            area="LAB",
            nvr_host="127.0.0.1",
            nvr_port=self.fake_server.server_address[1],
            nvr_username=self.username,
            nvr_password=self.password,
            nvr_channel=1,
            nvr_recording_enabled=True,
        )
        self.event = Event.objects.create(
            camera=self.camera,
            camera_code=self.camera.camera_code,
            event_id="FAKE-NVR-EVENT-001",
            source_event_id="FAKE-SOURCE-001",
            detected_at=timezone.now().replace(microsecond=0),
        )

    def test_production_client_completes_evidence_through_fake_server(self):
        evidence = create_recording_evidence(self.event)
        self.assertEqual(evidence.export_id, "1001")
        self.assertEqual(evidence.export_status, EventRecordingEvidence.STATUS_REQUESTED)

        refresh_export_status(evidence)
        self.assertEqual(evidence.export_status, EventRecordingEvidence.STATUS_EXPORTING)

        self.clock.advance(5)
        refresh_export_status(evidence)
        self.assertEqual(evidence.export_status, EventRecordingEvidence.STATUS_READY)
        download_completed_export(evidence)

        evidence.refresh_from_db()
        self.assertEqual(evidence.export_status, EventRecordingEvidence.STATUS_COMPLETED)
        self.assertEqual(evidence.file_size, len(fake_mp4_bytes()))
        self.assertTrue((self.media_root / evidence.file.name).is_file())
        self.assertEqual((self.media_root / evidence.file.name).read_bytes()[4:8], b"ftyp")

    def test_worker_restart_resumes_export_id_without_duplicate_request(self):
        evidence = create_recording_evidence(self.event)
        original_export_id = evidence.export_id
        self.clock.advance(5)
        EventRecordingEvidence.objects.filter(pk=evidence.pk).update(
            next_poll_at=timezone.now() - timedelta(seconds=1),
            updated_at=timezone.now() - timedelta(seconds=2),
        )

        process_recording_cycle()

        evidence.refresh_from_db()
        self.assertEqual(evidence.export_id, original_export_id)
        self.assertEqual(evidence.export_status, EventRecordingEvidence.STATUS_COMPLETED)
        self.assertEqual(self.fake_state.export_count, 1)

    def test_three_events_keep_distinct_export_ids_and_output_paths(self):
        evidences = []
        for index in range(3):
            event = Event.objects.create(
                camera=self.camera,
                camera_code=self.camera.camera_code,
                event_id=f"FAKE-NVR-EVENT-{index + 10}",
                source_event_id=f"FAKE-SOURCE-{index + 10}",
                detected_at=self.event.detected_at + timedelta(seconds=index + 1),
            )
            evidences.append(create_recording_evidence(event))

        self.clock.advance(5)
        for evidence in evidences:
            refresh_export_status(evidence)
            download_completed_export(evidence)

        self.assertEqual(
            {evidence.export_id for evidence in evidences},
            {"1001", "1002", "1003"},
        )
        self.assertEqual(len({evidence.file.name for evidence in evidences}), 3)
        self.assertTrue(all(evidence.file_size > 0 for evidence in evidences))

    def test_lab_mapping_command_is_dry_run_by_default(self):
        original = (
            self.camera.nvr_host,
            self.camera.nvr_port,
            self.camera.nvr_channel,
        )
        output = io.StringIO()

        call_command(
            "configure_fake_nvr_lab",
            camera_codes=["CAM-001"],
            stdout=output,
        )

        self.camera.refresh_from_db()
        self.assertEqual(
            (self.camera.nvr_host, self.camera.nvr_port, self.camera.nvr_channel),
            original,
        )
        self.assertIn("DRY-RUN", output.getvalue())

    def test_lab_mapping_requires_explicit_apply_and_never_prints_password(self):
        output = io.StringIO()

        call_command(
            "configure_fake_nvr_lab",
            camera_codes=["CAM-001"],
            port=self.fake_server.server_address[1],
            username="lab",
            password="private-placeholder",
            apply=True,
            confirm="FAKE-NVR-LAB",
            stdout=output,
        )

        self.camera.refresh_from_db()
        self.assertEqual(self.camera.nvr_host, "127.0.0.1")
        self.assertEqual(self.camera.nvr_channel, 1)
        self.assertEqual(self.camera.nvr_username, "lab")
        self.assertEqual(self.camera.nvr_password, "private-placeholder")
        self.assertNotIn("private-placeholder", output.getvalue())
