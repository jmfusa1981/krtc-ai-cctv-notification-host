import io
import tempfile
from datetime import timedelta
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.error import HTTPError

from django.test import TestCase, override_settings
from django.utils import timezone

from apps.cameras.models import Camera
from apps.events.models import Event, EventRecordingEvidence
from apps.events.services.media_retention import (
    prune_expired_event_media,
    run_daily_media_retention,
)
from apps.events.services.nvr_recording import (
    NvrRecordingError,
    NvrTerminalError,
    download_completed_export,
    redact_nvr_error,
    refresh_export_status,
    request_export,
)
from apps.events.services.recording_worker import process_recording_cycle
from apps.station_api.occ_media import local_occ_upload_candidates


class FakeNvrResponse:
    def __init__(self, body, headers=None):
        self.stream = io.BytesIO(body)
        self.headers = headers or {}

    def read(self, size=-1):
        return self.stream.read(size)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False


@override_settings(
    KRTC_NVR_RECORDING_MODE="nvr",
    KRTC_NVR_DEFAULT_HOST="192.0.2.10",
    KRTC_NVR_DEFAULT_PORT=80,
    KRTC_NVR_DEFAULT_USERNAME="vendor-user",
    KRTC_NVR_DEFAULT_PASSWORD="vendor-password",
    KRTC_NVR_POLL_INTERVAL_SECONDS=5,
    KRTC_NVR_EXPORT_TIMEOUT_SECONDS=60,
    KRTC_NVR_WORKER_BATCH_SIZE=20,
    KRTC_NVR_DOWNLOAD_TIMEOUT_SECONDS=10,
    KRTC_NVR_MAX_VIDEO_BYTES=1024,
    KRTC_NVR_DOWNLOAD_CHUNK_BYTES=8,
    KRTC_EVENT_MEDIA_RETENTION_DAYS=30,
    KRTC_EVENT_MEDIA_RETENTION_BATCH_SIZE=100,
    KRTC_STATION_CODE="TEST-STATION",
    KRTC_NOTIFICATION_HOST_CODE="PAO-TEST-001",
)
class NvrAcquisitionMvpTests(TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.media_root = Path(self.temporary_directory.name) / "media"
        self.media_root.mkdir()
        self.media_override = override_settings(MEDIA_ROOT=self.media_root)
        self.media_override.enable()
        self.addCleanup(self.media_override.disable)
        self.addCleanup(self.temporary_directory.cleanup)
        self.camera = Camera.objects.create(
            camera_code="CAM-NVR-001",
            name="NVR Camera",
            area="A",
            nvr_channel=1,
            nvr_recording_enabled=True,
        )
        self.event = Event.objects.create(
            camera=self.camera,
            camera_code=self.camera.camera_code,
            event_id="NVR-EVENT-001",
            source_event_id="SOURCE-001",
            detected_at=timezone.now(),
        )

    def _evidence(self, status=EventRecordingEvidence.STATUS_PENDING, **values):
        defaults = {
            "event": self.event,
            "camera": self.camera,
            "nvr_host": "192.0.2.10",
            "nvr_port": 80,
            "nvr_channel": 1,
            "evidence_start_at": self.event.detected_at - timedelta(seconds=30),
            "evidence_end_at": self.event.detected_at + timedelta(seconds=90),
            "export_status": status,
        }
        defaults.update(values)
        return EventRecordingEvidence.objects.create(**defaults)

    def _set_old_updated_at(self, evidence):
        old = timezone.now() - timedelta(seconds=10)
        EventRecordingEvidence.objects.filter(pk=evidence.pk).update(updated_at=old)
        evidence.refresh_from_db()

    @patch("apps.events.services.nvr_recording._request_json", return_value={"ID": 77})
    def test_request_export_saves_id_and_requested_state(self, request_json):
        evidence = self._evidence()

        request_export(evidence)

        self.assertEqual(evidence.export_id, "77")
        self.assertEqual(evidence.export_status, EventRecordingEvidence.STATUS_REQUESTED)
        self.assertEqual(evidence.pre_event_seconds, 30)
        self.assertEqual(evidence.post_event_seconds, 90)
        self.assertNotIn("vendor-password", str(evidence.request_payload))

    @patch("apps.events.services.nvr_recording._request_json")
    def test_no_record_data_is_terminal(self, request_json):
        request_json.return_value = {"message": "No record data exist"}
        evidence = self._evidence()

        request_export(evidence)

        self.assertEqual(evidence.export_status, EventRecordingEvidence.STATUS_FAILED)

    @patch("apps.events.services.nvr_recording._request_json")
    def test_transient_request_error_remains_retryable(self, request_json):
        request_json.side_effect = NvrRecordingError("temporary network failure")
        evidence = self._evidence()

        request_export(evidence)

        self.assertEqual(evidence.export_status, EventRecordingEvidence.STATUS_PENDING)
        self.assertIsNotNone(evidence.requested_at)

    @patch("apps.events.services.nvr_recording._request_json")
    def test_authentication_rejection_is_terminal_and_redacted(self, request_json):
        request_json.side_effect = NvrTerminalError(
            "http://vendor-user:vendor-password@192.0.2.10 rejected"
        )
        evidence = self._evidence()

        request_export(evidence)

        self.assertEqual(evidence.export_status, EventRecordingEvidence.STATUS_FAILED)
        self.assertNotIn("vendor-user", evidence.last_error)
        self.assertNotIn("vendor-password", evidence.last_error)

    @patch("apps.events.services.nvr_recording._request_json")
    def test_poll_state_mapping(self, request_json):
        cases = [
            ({"Status": 0, "FFmpeg": 0, "Rate": 0}, "requested"),
            ({"Status": 0, "FFmpeg": 1, "Rate": 5}, "exporting"),
            ({"Status": 1, "FFmpeg": 1, "Rate": 100}, "exporting"),
        ]
        for index, (payload, expected) in enumerate(cases):
            with self.subTest(payload=payload):
                evidence = self._evidence(
                    status=EventRecordingEvidence.STATUS_REQUESTED,
                    export_id=f"job-{index}",
                )
                request_json.return_value = payload
                refresh_export_status(evidence)
                self.assertEqual(evidence.export_status, expected)
                self.assertEqual(evidence.response_payload["Status"], payload["Status"])
                self.assertFalse(evidence.file)

    @patch("apps.events.services.nvr_recording._request_json", return_value={"Status": -1})
    def test_status_minus_one_is_terminal(self, request_json):
        evidence = self._evidence(
            status=EventRecordingEvidence.STATUS_REQUESTED,
            export_id="missing",
        )
        refresh_export_status(evidence)
        self.assertEqual(evidence.export_status, EventRecordingEvidence.STATUS_FAILED)

    @patch("apps.events.services.nvr_recording._request_json")
    def test_transient_poll_error_keeps_current_state(self, request_json):
        request_json.side_effect = NvrRecordingError("temporary")
        evidence = self._evidence(
            status=EventRecordingEvidence.STATUS_EXPORTING,
            export_id="job",
        )
        refresh_export_status(evidence)
        self.assertEqual(evidence.export_status, EventRecordingEvidence.STATUS_EXPORTING)

    @override_settings(KRTC_NVR_RECORDING_MODE="simulation")
    def test_worker_creates_once_and_restart_scan_does_not_duplicate(self):
        first = process_recording_cycle()
        second = process_recording_cycle()

        self.assertEqual(first["created"], 1)
        self.assertEqual(second["created"], 0)
        self.assertEqual(self.event.recording_evidences.count(), 1)

    @override_settings(KRTC_NVR_RECORDING_MODE="simulation")
    def test_worker_does_not_create_unlimited_rows_after_failure(self):
        self._evidence(status=EventRecordingEvidence.STATUS_FAILED)

        process_recording_cycle()

        self.assertEqual(self.event.recording_evidences.count(), 1)

    @patch("apps.events.services.recording_worker.refresh_export_status")
    def test_worker_recovers_requested_evidence_from_database(self, refresh):
        evidence = self._evidence(
            status=EventRecordingEvidence.STATUS_REQUESTED,
            export_id="restart-job",
            requested_at=timezone.now(),
        )
        self._set_old_updated_at(evidence)

        process_recording_cycle()

        refresh.assert_called_once()
        self.assertEqual(refresh.call_args.args[0].pk, evidence.pk)

    @patch("apps.events.services.recording_worker.download_completed_export")
    @patch("apps.events.services.recording_worker.refresh_export_status")
    def test_ready_status_downloads_on_next_cycle_without_second_poll(self, refresh, download):
        evidence = self._evidence(
            status=EventRecordingEvidence.STATUS_EXPORTING,
            export_id="ready-job",
            requested_at=timezone.now(),
            response_payload={"Status": 1, "Rate": 100},
        )
        self._set_old_updated_at(evidence)

        process_recording_cycle()

        download.assert_called_once()
        refresh.assert_not_called()

    def test_export_deadline_marks_failed_without_network_action(self):
        evidence = self._evidence(
            status=EventRecordingEvidence.STATUS_REQUESTED,
            export_id="late-job",
            requested_at=timezone.now() - timedelta(minutes=2),
        )
        self._set_old_updated_at(evidence)

        with patch("apps.events.services.recording_worker.refresh_export_status") as refresh:
            process_recording_cycle()

        refresh.assert_not_called()
        evidence.refresh_from_db()
        self.assertEqual(evidence.export_status, EventRecordingEvidence.STATUS_FAILED)

    @patch("apps.events.services.nvr_recording.urlopen")
    def test_completed_download_streams_and_finalizes_mp4(self, urlopen):
        content = b"\x00\x00\x00\x18ftypmp42" + b"video-data" * 5
        urlopen.return_value = FakeNvrResponse(
            content,
            {
                "Content-Length": str(len(content)),
                "Content-Disposition": 'attachment; filename="event.mp4"',
            },
        )
        evidence = self._evidence(
            status=EventRecordingEvidence.STATUS_EXPORTING,
            export_id="ready-job",
            response_payload={"Status": 1},
        )

        download_completed_export(evidence)

        self.assertEqual(evidence.export_status, EventRecordingEvidence.STATUS_COMPLETED)
        self.assertTrue(evidence.file.name.startswith("event_recordings/"))
        self.assertEqual((self.media_root / evidence.file.name).read_bytes(), content)
        self.assertFalse(any((self.media_root / "event_recordings" / ".partial").iterdir()))

    @patch("apps.events.services.nvr_recording.urlopen")
    def test_json_download_error_is_not_saved_and_partial_is_removed(self, urlopen):
        body = b'{"Message":"not exist or not finish."}'
        urlopen.return_value = FakeNvrResponse(body, {"Content-Length": str(len(body))})
        evidence = self._evidence(
            status=EventRecordingEvidence.STATUS_EXPORTING,
            export_id="not-ready",
        )

        download_completed_export(evidence)

        self.assertEqual(evidence.export_status, EventRecordingEvidence.STATUS_EXPORTING)
        self.assertFalse(evidence.file)
        partial = self.media_root / "event_recordings" / ".partial"
        self.assertFalse(partial.exists() and any(partial.iterdir()))

    @patch("apps.events.services.nvr_recording.urlopen")
    def test_invalid_mp4_and_max_size_do_not_finalize(self, urlopen):
        evidence = self._evidence(
            status=EventRecordingEvidence.STATUS_EXPORTING,
            export_id="invalid",
        )
        urlopen.return_value = FakeNvrResponse(b"not-mp4", {"Content-Length": "7"})
        download_completed_export(evidence)
        self.assertFalse(evidence.file)

        evidence.last_error = ""
        with override_settings(KRTC_NVR_MAX_VIDEO_BYTES=8):
            urlopen.return_value = FakeNvrResponse(
                b"\x00\x00\x00\x18ftypmp42oversize",
                {"Content-Length": "24"},
            )
            download_completed_export(evidence)
        self.assertEqual(evidence.export_status, EventRecordingEvidence.STATUS_FAILED)
        self.assertFalse(evidence.file)

    def test_credential_redaction_masks_userinfo_and_config_values(self):
        redacted = redact_nvr_error(
            "http://vendor-user:vendor-password@192.0.2.10/export.cgi"
        )
        self.assertNotIn("vendor-user", redacted)
        self.assertNotIn("vendor-password", redacted)
        self.assertIn("***:***@", redacted)

    def test_retention_deletes_old_local_media_and_preserves_metadata(self):
        old_time = timezone.now() - timedelta(days=31)
        Event.objects.filter(pk=self.event.pk).update(detected_at=old_time)
        self.event.refresh_from_db()
        snapshot_path = self.media_root / "event_snapshots" / "old.jpg"
        snapshot_path.parent.mkdir(parents=True)
        snapshot_path.write_bytes(b"snapshot")
        self.event.snapshot = "event_snapshots/old.jpg"
        self.event.save(update_fields=["snapshot"])
        video_path = self.media_root / "event_recordings" / "old.mp4"
        video_path.parent.mkdir(parents=True)
        video_path.write_bytes(b"\x00\x00\x00\x18ftypmp42")
        evidence = self._evidence(
            status=EventRecordingEvidence.STATUS_COMPLETED,
            file="event_recordings/old.mp4",
            download_url="http://nvr.example/external.mp4",
        )
        self.event.video_url = evidence.file.url
        self.event.snapshot_url = "http://inference.example/external.jpg"
        self.event.save(update_fields=["video_url", "snapshot_url"])

        result = prune_expired_event_media(now=timezone.now())

        self.assertEqual(result["snapshots_deleted"], 1)
        self.assertEqual(result["videos_deleted"], 1)
        self.event.refresh_from_db()
        evidence.refresh_from_db()
        self.assertTrue(Event.objects.filter(pk=self.event.pk).exists())
        self.assertTrue(EventRecordingEvidence.objects.filter(pk=evidence.pk).exists())
        self.assertFalse(self.event.snapshot)
        self.assertFalse(evidence.file)
        self.assertEqual(self.event.video_url, "")
        self.assertEqual(self.event.snapshot_url, "http://inference.example/external.jpg")
        self.assertEqual(evidence.download_url, "http://nvr.example/external.mp4")
        self.assertFalse(snapshot_path.exists())
        self.assertFalse(video_path.exists())

    @patch("apps.events.services.media_retention.prune_expired_event_media")
    def test_daily_retention_marker_survives_worker_restart(self, prune):
        prune.return_value = {"events_processed": 0}
        now = timezone.now()

        first = run_daily_media_retention(now=now)
        second = run_daily_media_retention(now=now)

        self.assertEqual(first, {"events_processed": 0})
        self.assertIsNone(second)
        prune.assert_called_once()

    def test_seven_day_candidates_only_include_valid_local_completed_mp4(self):
        video_path = self.media_root / "event_recordings" / "ready.mp4"
        video_path.parent.mkdir(parents=True)
        video_path.write_bytes(b"\x00\x00\x00\x18ftypmp42")
        ready = self._evidence(
            status=EventRecordingEvidence.STATUS_COMPLETED,
            file="event_recordings/ready.mp4",
        )
        self._evidence(status=EventRecordingEvidence.STATUS_PENDING)
        old_event = Event.objects.create(
            camera=self.camera,
            event_id="OLD-EVENT",
            detected_at=timezone.now() - timedelta(days=8),
        )
        old_path = self.media_root / "event_recordings" / "old-ready.mp4"
        old_path.write_bytes(b"\x00\x00\x00\x18ftypmp42")
        EventRecordingEvidence.objects.create(
            event=old_event,
            camera=self.camera,
            evidence_start_at=old_event.detected_at - timedelta(seconds=30),
            evidence_end_at=old_event.detected_at + timedelta(seconds=90),
            export_status=EventRecordingEvidence.STATUS_COMPLETED,
            file="event_recordings/old-ready.mp4",
        )

        candidates = local_occ_upload_candidates(now=timezone.now())

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["recording_evidence_id"], ready.id)
        self.assertEqual(candidates[0]["pao_event_id"], self.event.id)
        self.assertEqual(candidates[0]["local_file_name"], "event_recordings/ready.mp4")
        self.assertNotIn(str(self.media_root), str(candidates[0]))

    @patch("apps.events.services.nvr_recording.urlopen")
    def test_http_auth_rejection_is_terminal(self, urlopen):
        urlopen.side_effect = HTTPError(
            "http://masked.invalid", 401, "Unauthorized", {}, None
        )
        evidence = self._evidence(
            status=EventRecordingEvidence.STATUS_EXPORTING,
            export_id="auth-job",
        )

        download_completed_export(evidence)

        self.assertEqual(evidence.export_status, EventRecordingEvidence.STATUS_FAILED)
        self.assertNotIn("vendor-password", evidence.last_error)
