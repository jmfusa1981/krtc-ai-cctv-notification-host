from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from apps.cameras.models import Camera
from apps.dashboard.views import get_recent_events
from apps.events.models import Event


class V663RecentEventOrderingTests(TestCase):
    def setUp(self):
        self.cam002 = Camera.objects.create(
            camera_code="CAM-002",
            name="CAM-002 test camera",
            area="A2",
        )
        self.cam004 = Camera.objects.create(
            camera_code="CAM-004",
            name="CAM-004 test camera",
            area="A4",
        )

    def test_recent_events_use_detected_time_not_import_created_time(self):
        now = timezone.now()

        # Create ten genuinely recent events first.
        expected_ids = []
        for index in range(10):
            event = Event.objects.create(
                camera=self.cam004 if index == 0 else self.cam002,
                event_type="large_luggage_intrusion" if index == 0 else "smoke_detected",
                detected_at=now - timedelta(seconds=index),
            )
            expected_ids.append(event.id)

        # Simulate a late/batch synchronisation: old detections arrive later and
        # therefore have newer created_at values.  They must not displace the
        # genuinely latest detections from the Dashboard's 10-row list.
        for index in range(4):
            Event.objects.create(
                camera=self.cam002,
                event_type="smoke_detected",
                detected_at=now - timedelta(days=1, seconds=index),
            )

        recent = get_recent_events()
        self.assertEqual([event.id for event in recent], expected_ids)
        self.assertEqual(recent[0].camera.camera_code, "CAM-004")
