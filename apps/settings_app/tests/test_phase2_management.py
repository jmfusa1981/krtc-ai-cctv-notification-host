from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.urls import reverse

from apps.notifications.models import AudioFile, BroadcastSchedule, SpeakerDevice


class Phase2ManagementTests(TestCase):
    def setUp(self):
        self.admin_group = Group.objects.create(name="Administrator")
        self.maintainer_group = Group.objects.create(name="Maintainer")
        self.operator_group = Group.objects.create(name="Operator")
        self.admin = User.objects.create_user("admin-ui", password="test-pass-123")
        self.admin.groups.add(self.admin_group)
        self.maintainer = User.objects.create_user("maintainer-ui", password="test-pass-123")
        self.maintainer.groups.add(self.maintainer_group)
        self.operator = User.objects.create_user("operator-ui", password="test-pass-123")
        self.operator.groups.add(self.operator_group)
        self.audio = AudioFile.objects.create(audio_code="AUD-TEST", name="Test", audio_type="prerecorded")
        self.speaker = SpeakerDevice.objects.create(
            speaker_code="SPK-TEST", name="Test Speaker", ip_address="127.0.0.1", port=5060,
            username="spk-test", is_active=True,
        )

    def test_administrator_can_open_account_management(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("settings_app:user_new"))
        self.assertEqual(response.status_code, 200)

    def test_maintainer_cannot_open_account_management(self):
        self.client.force_login(self.maintainer)
        response = self.client.get(reverse("settings_app:user_new"))
        self.assertEqual(response.status_code, 403)

    def test_administrator_can_create_operator(self):
        self.client.force_login(self.admin)
        response = self.client.post(reverse("settings_app:user_new"), {
            "username": "new-operator",
            "first_name": "New Operator",
            "email": "operator@example.com",
            "role": "Operator",
            "password": "strong-pass-123",
            "is_active": "on",
        })
        self.assertEqual(response.status_code, 302)
        user = User.objects.get(username="new-operator")
        self.assertTrue(user.groups.filter(name="Operator").exists())
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)

    def test_maintainer_can_create_broadcast_schedule(self):
        self.client.force_login(self.maintainer)
        response = self.client.post(reverse("settings_app:manage_new", args=["broadcast-schedule"]), {
            "name": "Daily test",
            "schedule_type": "daily",
            "audio_file": self.audio.pk,
            "speakers": [self.speaker.pk],
            "daily_time": "09:30",
            "volume_percent": 80,
            "is_active": "on",
        })
        self.assertEqual(response.status_code, 302)
        schedule = BroadcastSchedule.objects.get(name="Daily test")
        self.assertEqual(schedule.created_by, self.maintainer)
        self.assertIsNotNone(schedule.next_run_at)
