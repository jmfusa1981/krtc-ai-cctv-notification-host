from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.cameras.models import Camera
from apps.events.models import Event, LocalAlarmPolicy


class PersistentLocalAlarmApiTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="alarm-test",
            password="test-password",
        )
        self.client.force_login(self.user)
        self.camera = Camera.objects.create(
            camera_code="CAM-ALARM-TEST",
            name="Alarm test camera",
            area="Test area",
        )
        self.policy = LocalAlarmPolicy.load()
        self.policy.enabled_at = timezone.now()
        self.policy.save(update_fields=["enabled_at", "updated_at"])

    def live_state(self):
        return self.client.get(reverse("dashboard:dashboard_live_state_api")).json()

    def create_event(self, status="new", created_before_cutoff=False):
        event = Event.objects.create(camera=self.camera, status=status)
        if created_before_cutoff:
            Event.objects.filter(pk=event.pk).update(
                created_at=self.policy.enabled_at - timedelta(seconds=1)
            )
        return event

    def test_new_processing_and_confirmed_events_remain_active(self):
        events = [
            self.create_event("new"),
            self.create_event("processing"),
            self.create_event("confirmed"),
        ]
        state = self.live_state()["local_alarm"]
        self.assertEqual(
            state["active_event_ids"],
            [event.id for event in events],
        )
        self.assertEqual(state["active_count"], 3)

    def test_closed_and_dismissed_events_do_not_alarm(self):
        self.create_event("closed")
        self.create_event("dismissed")
        state = self.live_state()["local_alarm"]
        self.assertEqual(state["active_event_ids"], [])
        self.assertEqual(state["active_count"], 0)

    def test_events_before_activation_cutoff_are_ignored(self):
        old_event = self.create_event("new", created_before_cutoff=True)
        new_event = self.create_event("new")
        state = self.live_state()["local_alarm"]
        self.assertNotIn(old_event.id, state["active_event_ids"])
        self.assertIn(new_event.id, state["active_event_ids"])

    def test_alarm_ids_are_not_limited_to_recent_ten_events(self):
        events = [self.create_event("new") for _ in range(12)]
        state = self.live_state()["local_alarm"]
        self.assertEqual(state["active_count"], 12)
        self.assertEqual(state["active_event_ids"], [event.id for event in events])

    def test_close_active_alarms_closes_every_alarm_event(self):
        self.user.is_superuser = True
        self.user.save(update_fields=["is_superuser"])

        events = [
            self.create_event("new"),
            self.create_event("processing"),
            self.create_event("confirmed"),
        ]
        old_event = self.create_event("new", created_before_cutoff=True)
        dismissed_event = self.create_event("dismissed")
        closed_event = self.create_event("closed")

        response = self.client.post(reverse("events:close_active_alarm_events_api"))
        self.assertEqual(response.status_code, 200)

        data = response.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["closed_count"], 3)
        self.assertEqual(data["closed_event_ids"], [event.id for event in events])

        for event in events:
            event.refresh_from_db()
            self.assertEqual(event.status, "closed")

        old_event.refresh_from_db()
        dismissed_event.refresh_from_db()
        closed_event.refresh_from_db()
        self.assertEqual(old_event.status, "new")
        self.assertEqual(dismissed_event.status, "dismissed")
        self.assertEqual(closed_event.status, "closed")
        self.assertEqual(self.live_state()["local_alarm"]["active_count"], 0)
