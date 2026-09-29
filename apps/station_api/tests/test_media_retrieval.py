import json
import tempfile
from datetime import timedelta
from pathlib import Path

from django.test import TestCase, override_settings
from django.utils import timezone

from apps.cameras.models import Camera
from apps.events.models import Event, EventRecordingEvidence


class OccMediaRetrievalTests(TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.media_root = Path(self.temp_dir.name) / "media"
        self.media_root.mkdir()
        self.settings_override = override_settings(
            MEDIA_ROOT=self.media_root,
            KRTC_OCC_API_TOKEN="occ-secret",
            KRTC_STATION_CODE="TEST-STATION",
            KRTC_NOTIFICATION_HOST_CODE="PAO-TEST-001",
        )
        self.settings_override.enable()
        self.addCleanup(self.settings_override.disable)
        self.addCleanup(self.temp_dir.cleanup)
        self.auth = {"HTTP_AUTHORIZATION": "Bearer occ-secret"}
        self.camera = Camera.objects.create(
            camera_code="CAM-MEDIA-001",
            name="Media Camera",
            area="A",
        )
        self.event = Event.objects.create(
            camera=self.camera,
            camera_code=self.camera.camera_code,
            event_type="other",
            event_id="media-event-001",
            snapshot_url="http://inference.example/private/snapshot.jpg",
            video_url="http://nvr.example/private/video.mp4",
        )

    def _write_media(self, relative_name, content):
        path = self.media_root / relative_name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return path

    def _create_evidence(self, status=EventRecordingEvidence.STATUS_COMPLETED, **values):
        detected_at = self.event.detected_at
        defaults = {
            "event": self.event,
            "camera": self.camera,
            "evidence_start_at": detected_at - timedelta(seconds=30),
            "evidence_end_at": detected_at + timedelta(seconds=90),
            "export_status": status,
            "completed_at": timezone.now() if status == EventRecordingEvidence.STATUS_COMPLETED else None,
        }
        defaults.update(values)
        return EventRecordingEvidence.objects.create(**defaults)

    @staticmethod
    def _response_body(response):
        try:
            return b"".join(response.streaming_content)
        finally:
            response.close()

    def test_snapshot_requires_token(self):
        url = f"/api/v1/events/{self.event.id}/snapshot/"
        self.assertEqual(self.client.get(url).status_code, 401)
        self.assertEqual(
            self.client.get(url, HTTP_AUTHORIZATION="Bearer wrong").status_code,
            401,
        )

    def test_media_endpoints_are_get_only(self):
        evidence = self._create_evidence()
        self.assertEqual(
            self.client.post(
                f"/api/v1/events/{self.event.id}/snapshot/", **self.auth
            ).status_code,
            405,
        )
        self.assertEqual(
            self.client.post(
                f"/api/v1/recordings/{evidence.id}/download/", **self.auth
            ).status_code,
            405,
        )

    def test_valid_snapshot_returns_local_image_with_safe_headers(self):
        content = b"\xff\xd8\xff\xe0local-jpeg"
        self._write_media("event_snapshots/event.jpg", content)
        self.event.snapshot = "event_snapshots/event.jpg"
        self.event.save(update_fields=["snapshot"])

        response = self.client.get(
            f"/api/v1/events/{self.event.id}/snapshot/", **self.auth
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "image/jpeg")
        self.assertEqual(response["X-Content-Type-Options"], "nosniff")
        self.assertEqual(response["Cache-Control"], "no-store")
        self.assertEqual(self._response_body(response), content)

    def test_snapshot_unknown_event_is_404_and_missing_file_is_409(self):
        self.assertEqual(
            self.client.get("/api/v1/events/999999/snapshot/", **self.auth).status_code,
            404,
        )
        response = self.client.get(
            f"/api/v1/events/{self.event.id}/snapshot/", **self.auth
        )
        self.assertEqual(response.status_code, 409)

    def test_media_extension_without_valid_content_is_not_ready(self):
        self._write_media("event_snapshots/invalid.jpg", b"not-an-image")
        self.event.snapshot = "event_snapshots/invalid.jpg"
        self.event.save(update_fields=["snapshot"])
        evidence = self._create_evidence(file="event_recordings/invalid.mp4")
        self._write_media("event_recordings/invalid.mp4", b"not-a-video")

        snapshot_response = self.client.get(
            f"/api/v1/events/{self.event.id}/snapshot/", **self.auth
        )
        video_response = self.client.get(
            f"/api/v1/recordings/{evidence.id}/download/", **self.auth
        )

        self.assertEqual(snapshot_response.status_code, 409)
        self.assertEqual(video_response.status_code, 409)

    def test_snapshot_cannot_escape_media_root_or_accept_client_path(self):
        outside = Path(self.temp_dir.name) / "outside.jpg"
        outside.write_bytes(b"\xff\xd8\xffoutside-secret")
        self.event.snapshot = "../outside.jpg"
        self.event.save(update_fields=["snapshot"])
        url = f"/api/v1/events/{self.event.id}/snapshot/"

        response = self.client.get(url, {"path": str(outside)}, **self.auth)

        self.assertEqual(response.status_code, 409)
        self.assertNotIn(str(outside), response.content.decode())
        self.assertNotIn("outside-secret", response.content.decode())

    def test_video_requires_token(self):
        evidence = self._create_evidence()
        url = f"/api/v1/recordings/{evidence.id}/download/"
        self.assertEqual(self.client.get(url).status_code, 401)
        self.assertEqual(
            self.client.get(url, HTTP_AUTHORIZATION="Bearer wrong").status_code,
            401,
        )

    def test_valid_video_is_attachment_with_sanitized_filename(self):
        content = b"\x00\x00\x00\x18ftypmp42local-video"
        self._write_media("event_recordings/event clip.mp4", content)
        evidence = self._create_evidence(file="event_recordings/event clip.mp4")

        response = self.client.get(
            f"/api/v1/recordings/{evidence.id}/download/", **self.auth
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "video/mp4")
        self.assertEqual(response["X-Content-Type-Options"], "nosniff")
        self.assertEqual(response["Cache-Control"], "no-store")
        self.assertIn("attachment;", response["Content-Disposition"])
        self.assertIn("event_clip.mp4", response["Content-Disposition"])
        self.assertNotIn(str(self.media_root), response["Content-Disposition"])
        self.assertEqual(self._response_body(response), content)

    def test_video_unknown_evidence_is_404(self):
        self.assertEqual(
            self.client.get("/api/v1/recordings/999999/download/", **self.auth).status_code,
            404,
        )

    def test_video_does_not_redirect_to_external_download_url(self):
        evidence = self._create_evidence(
            download_url="http://nvr.example/credential-bearing/video.mp4"
        )

        response = self.client.get(
            f"/api/v1/recordings/{evidence.id}/download/", **self.auth
        )

        self.assertEqual(response.status_code, 409)
        self.assertNotIn("Location", response)
        self.assertNotIn("nvr.example", response.content.decode())

    def test_pending_or_missing_local_video_is_409(self):
        self._write_media("event_recordings/pending.mp4", b"\x00\x00\x00\x18ftypmp42")
        pending = self._create_evidence(
            status=EventRecordingEvidence.STATUS_PENDING,
            file="event_recordings/pending.mp4",
        )
        completed_missing = self._create_evidence(file="event_recordings/missing.mp4")

        for evidence in (pending, completed_missing):
            response = self.client.get(
                f"/api/v1/recordings/{evidence.id}/download/", **self.auth
            )
            self.assertEqual(response.status_code, 409)

    def test_event_list_is_backward_compatible_and_adds_media_readiness(self):
        self._write_media("event_snapshots/event.jpg", b"\xff\xd8\xfflocal")
        self.event.snapshot = "event_snapshots/event.jpg"
        self.event.save(update_fields=["snapshot"])
        self._write_media("event_recordings/event.mp4", b"\x00\x00\x00\x18ftypmp42")
        evidence = self._create_evidence(file="event_recordings/event.mp4")

        response = self.client.get("/api/v1/events/", **self.auth)
        item = response.json()["items"][0]

        self.assertEqual(response.status_code, 200)
        existing_fields = {
            "id", "source_host", "source_event_id", "camera_code", "event_id",
            "inference_host_code", "event_code", "mapping_status", "video_url",
            "event_type", "severity", "status", "detected_at", "snapshot_url",
        }
        self.assertTrue(existing_fields.issubset(item))
        self.assertEqual(item["pao_event_id"], self.event.id)
        self.assertTrue(item["snapshot_ready"])
        self.assertEqual(
            item["snapshot_download_url"],
            f"/api/v1/events/{self.event.id}/snapshot/",
        )
        self.assertEqual(item["recording_evidence_id"], evidence.id)
        self.assertEqual(item["recording_status"], "completed")
        self.assertTrue(item["video_ready"])
        self.assertEqual(
            item["video_download_url"],
            f"/api/v1/recordings/{evidence.id}/download/",
        )
        serialized = json.dumps(response.json())
        self.assertNotIn(str(self.media_root), serialized)
        self.assertNotIn("occ-secret", serialized)

    def test_event_list_chooses_latest_ready_completed_recording(self):
        self._write_media("event_recordings/old.mp4", b"\x00\x00\x00\x18ftypmp42old")
        ready = self._create_evidence(
            file="event_recordings/old.mp4",
            completed_at=timezone.now() - timedelta(minutes=1),
        )
        self._create_evidence(
            status=EventRecordingEvidence.STATUS_PENDING,
            created_at=timezone.now(),
        )

        item = self.client.get("/api/v1/events/", **self.auth).json()["items"][0]

        self.assertEqual(item["recording_evidence_id"], ready.id)
        self.assertEqual(item["recording_status"], "completed")
        self.assertTrue(item["video_ready"])

    def test_event_list_reports_not_ready_without_exposing_remote_media(self):
        evidence = self._create_evidence(
            download_url="http://user:password@nvr.example/video.mp4"
        )

        item = self.client.get("/api/v1/events/", **self.auth).json()["items"][0]

        self.assertFalse(item["snapshot_ready"])
        self.assertIsNone(item["snapshot_download_url"])
        self.assertEqual(item["recording_evidence_id"], evidence.id)
        self.assertEqual(item["recording_status"], "completed")
        self.assertFalse(item["video_ready"])
        self.assertIsNone(item["video_download_url"])
        self.assertNotIn("nvr.example", json.dumps({
            "snapshot_download_url": item["snapshot_download_url"],
            "video_download_url": item["video_download_url"],
        }))
