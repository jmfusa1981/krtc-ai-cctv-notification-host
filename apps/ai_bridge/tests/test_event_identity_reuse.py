from datetime import timedelta

from django.test import SimpleTestCase
from django.utils import timezone

from apps.events.services.event_identity import build_event_identity


class EventIdentityReuseTests(SimpleTestCase):
    def test_same_source_id_different_timestamp_has_different_identity(self):
        first_time = timezone.now()
        second_time = first_time + timedelta(hours=1)
        first = build_event_identity("INF-001", "20260806000001", first_time)
        second = build_event_identity("INF-001", "20260806000001", second_time)
        self.assertNotEqual(first, second)

    def test_same_payload_identity_is_stable(self):
        detected_at = timezone.now()
        first = build_event_identity("INF-001", "20260806000001", detected_at)
        second = build_event_identity("INF-001", "20260806000001", detected_at)
        self.assertEqual(first, second)
        self.assertLessEqual(len(first), 150)
