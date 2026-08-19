from datetime import timedelta

from django.test import TestCase, override_settings
from django.utils import timezone

from apps.cameras.models import Camera
from apps.events.models import Event, EventRecordingEvidence
from apps.events.services.nvr_recording import create_recording_evidence


@override_settings(
    KRTC_NVR_RECORDING_MODE="simulation",
    KRTC_NVR_DEFAULT_USERNAME="root",
    KRTC_NVR_DEFAULT_PASSWORD="root",
)
class NvrRecordingEvidenceTests(TestCase):
    def test_simulation_creates_event_window_evidence(self):
        detected_at = timezone.now().replace(microsecond=0)
        camera = Camera.objects.create(
            camera_code="CAM-002",
            name="Platform Camera",
            area="R16",
            nvr_host="192.168.6.30",
            nvr_channel=2,
        )
        event = Event.objects.create(
            camera=camera,
            camera_code="CAM-002",
            event_type="large_luggage_intrusion",
            source_event_id="20260803000230",
            detected_at=detected_at,
        )

        evidence = create_recording_evidence(event)

        self.assertEqual(evidence.export_status, EventRecordingEvidence.STATUS_COMPLETED)
        self.assertEqual(evidence.pre_event_seconds, 30)
        self.assertEqual(evidence.post_event_seconds, 90)
        self.assertEqual(evidence.evidence_start_at, detected_at - timedelta(seconds=30))
        self.assertEqual(evidence.evidence_end_at, detected_at + timedelta(seconds=90))
        self.assertEqual(evidence.nvr_host, "192.168.6.30")
        self.assertEqual(evidence.nvr_channel, 2)
        self.assertTrue(evidence.file.name.endswith(".txt"))
        event.refresh_from_db()
        self.assertTrue(event.video_url)
