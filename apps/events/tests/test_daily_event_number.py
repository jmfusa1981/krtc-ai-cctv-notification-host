from datetime import datetime

from django.test import TestCase, override_settings
from django.utils import timezone

from apps.events.models import Event


@override_settings(TIME_ZONE='Asia/Taipei', USE_TZ=True)
class DailyEventNumberTests(TestCase):
    def create_event(self, dt):
        return Event.objects.create(
            event_type='other',
            status='new',
            detected_at=dt,
        )

    def test_sequence_increments_and_resets_each_local_day(self):
        tz = timezone.get_current_timezone()
        e1 = self.create_event(timezone.make_aware(datetime(2026, 8, 7, 8, 0, 0), tz))
        e2 = self.create_event(timezone.make_aware(datetime(2026, 8, 7, 8, 0, 1), tz))
        e3 = self.create_event(timezone.make_aware(datetime(2026, 8, 8, 0, 0, 1), tz))

        self.assertEqual(e1.record_number, '08070001')
        self.assertEqual(e2.record_number, '08070002')
        self.assertEqual(e3.record_number, '08080001')
