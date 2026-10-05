import io
import inspect
import tempfile
from datetime import timedelta
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo

from django.core.management import call_command
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
    NvrConfig,
    _build_nvr_request,
    _local_nvr_timestamp,
    create_recording_evidence,
    download_completed_export,
    enqueue_recording_evidence,
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

    @patch("apps.events.services.nvr_recording._request_json", return_value={})
    def test_missing_export_id_is_terminal(self, request_json):
        evidence = self._evidence()

        request_export(evidence)

        self.assertEqual(evidence.export_status, EventRecordingEvidence.STATUS_FAILED)
        self.assertFalse(evidence.export_id)

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
            ({"Status": 0, "FFmpeg": 0, "Rate": 0}, "exporting"),
            ({"Status": 0, "FFmpeg": 1, "Rate": 5}, "exporting"),
            ({"Status": 1, "FFmpeg": 1, "Rate": 100}, "ready"),
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
        self.assertEqual(evidence.export_status, EventRecordingEvidence.STATUS_EXPIRED)

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

        self.assertEqual(evidence.export_status, EventRecordingEvidence.STATUS_READY)
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

    def test_event_time_window_is_exact_and_timezone_format_is_deterministic(self):
        detected_at = timezone.datetime(
            2026, 8, 3, 2, 30, 0, tzinfo=ZoneInfo("UTC")
        )
        self.event.detected_at = detected_at
        self.event.save(update_fields=["detected_at"])

        evidence = enqueue_recording_evidence(self.event)

        self.assertEqual(
            evidence.evidence_start_at,
            detected_at - timedelta(seconds=30),
        )
        self.assertEqual(
            evidence.evidence_end_at - evidence.evidence_start_at,
            timedelta(seconds=120),
        )
        self.assertEqual(
            _local_nvr_timestamp(evidence.evidence_start_at),
            "2026-08-03T10:29:30",
        )

    def test_request_uses_encoded_query_and_separate_basic_auth(self):
        config = NvrConfig(
            host="192.0.2.10",
            port=8080,
            username="operator@lab",
            password="p&?=@:ss",
            channel=2,
            video_format="MP4",
        )
        params = {
            "channel": 2,
            "start_time": "2026-08-03T10:29:30",
            "end_time": "2026-08-03T10:31:30",
            "format": "MP4",
        }

        request = _build_nvr_request(config, params, accept="application/json")
        query = parse_qs(urlsplit(request.full_url).query)

        self.assertNotIn(config.username, request.full_url)
        self.assertNotIn(config.password, request.full_url)
        self.assertTrue(request.get_header("Authorization").startswith("Basic "))
        self.assertEqual(query["channel"], ["2"])
        self.assertEqual(query["start_time"], [params["start_time"]])
        self.assertEqual(query["end_time"], [params["end_time"]])
        self.assertEqual(query["format"], ["MP4"])

    def test_nvr_module_has_no_shell_or_subprocess_execution(self):
        from apps.events.services import nvr_recording

        source = inspect.getsource(nvr_recording)
        self.assertNotIn("subprocess", source)
        self.assertNotIn("shell=True", source)

    @patch("apps.events.services.nvr_recording._request_json", return_value={"ID": "job-2"})
    def test_export_request_passes_channel_and_mp4_params(self, request_json):
        evidence = self._evidence()

        request_export(evidence)

        params = request_json.call_args.args[1]
        self.assertEqual(params["channel"], 1)
        self.assertEqual(params["format"], "MP4")
        self.assertEqual(params["start_time"], _local_nvr_timestamp(evidence.evidence_start_at))
        self.assertEqual(params["end_time"], _local_nvr_timestamp(evidence.evidence_end_at))

    def test_missing_channel_mapping_fails_before_network(self):
        self.camera.nvr_channel = None
        self.camera.save(update_fields=["nvr_channel"])

        with patch("apps.events.services.nvr_recording.urlopen") as urlopen:
            with self.assertRaisesMessage(NvrRecordingError, "缺少 NVR Channel"):
                enqueue_recording_evidence(self.event)

        urlopen.assert_not_called()

    @patch("apps.events.services.nvr_recording.urlopen")
    def test_empty_download_is_failed_and_never_completed(self, urlopen):
        urlopen.return_value = FakeNvrResponse(b"", {"Content-Length": "0"})
        evidence = self._evidence(
            status=EventRecordingEvidence.STATUS_READY,
            export_id="empty-job",
        )

        download_completed_export(evidence)

        self.assertEqual(evidence.export_status, EventRecordingEvidence.STATUS_FAILED)
        self.assertFalse(evidence.file)
        self.assertEqual(evidence.file_size, 0)

    @patch("apps.events.services.nvr_recording.urlopen")
    def test_two_export_ids_download_to_isolated_paths(self, urlopen):
        content_a = b"\x00\x00\x00\x18ftypmp42-a"
        content_b = b"\x00\x00\x00\x18ftypmp42-b"
        urlopen.side_effect = [
            FakeNvrResponse(content_a, {"Content-Length": str(len(content_a))}),
            FakeNvrResponse(content_b, {"Content-Length": str(len(content_b))}),
        ]
        evidence_a = self._evidence(
            status=EventRecordingEvidence.STATUS_READY,
            export_id="101",
        )
        second_event = Event.objects.create(
            camera=self.camera,
            camera_code=self.camera.camera_code,
            event_id="NVR-EVENT-002",
            source_event_id="SOURCE-002",
            detected_at=self.event.detected_at + timedelta(seconds=1),
        )
        evidence_b = EventRecordingEvidence.objects.create(
            event=second_event,
            camera=self.camera,
            camera_code=self.camera.camera_code,
            source_event_id=second_event.source_event_id,
            event_time=second_event.detected_at,
            nvr_host="192.0.2.10",
            nvr_port=80,
            nvr_channel=1,
            evidence_start_at=second_event.detected_at - timedelta(seconds=30),
            evidence_end_at=second_event.detected_at + timedelta(seconds=90),
            export_status=EventRecordingEvidence.STATUS_READY,
            export_id="102",
        )

        download_completed_export(evidence_a)
        download_completed_export(evidence_b)

        self.assertNotEqual(evidence_a.file.name, evidence_b.file.name)
        self.assertEqual((self.media_root / evidence_a.file.name).read_bytes(), content_a)
        self.assertEqual((self.media_root / evidence_b.file.name).read_bytes(), content_b)

    @override_settings(
        KRTC_NVR_EXPORT_WARNING_SECONDS=3600,
        KRTC_NVR_EXPORT_TIMEOUT_SECONDS=7200,
    )
    @patch("apps.events.services.recording_worker.refresh_export_status")
    def test_long_running_job_resumes_same_export_id_without_duplicate_request(self, refresh):
        evidence = self._evidence(
            status=EventRecordingEvidence.STATUS_EXPORTING,
            export_id="long-job",
            requested_at=timezone.now() - timedelta(minutes=41),
        )
        self._set_old_updated_at(evidence)

        process_recording_cycle()

        refresh.assert_called_once()
        evidence.refresh_from_db()
        self.assertEqual(evidence.export_id, "long-job")
        self.assertEqual(self.event.recording_evidences.count(), 1)

    def test_field_validation_command_is_dry_run_by_default(self):
        output = io.StringIO()

        with patch("apps.events.services.nvr_recording.urlopen") as urlopen:
            call_command(
                "validate_nvr_recording",
                event_id=self.event.pk,
                stdout=output,
            )

        urlopen.assert_not_called()
        self.assertIn("DRY-RUN", output.getvalue())
        self.assertIn("no database write and no NVR request", output.getvalue())
        self.assertEqual(self.event.recording_evidences.count(), 0)
