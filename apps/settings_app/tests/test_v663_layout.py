from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.urls import reverse

from apps.cameras.models import Camera
from apps.notifications.models import SpeakerDevice


class V663SettingsLayoutTests(TestCase):
    def setUp(self):
        admin_group, _ = Group.objects.get_or_create(name="Administrator")
        self.user = User.objects.create_user("v663-admin", password="pass-123456")
        self.user.groups.add(admin_group)
        self.client.force_login(self.user)
        Camera.objects.create(camera_code="CAM-001", name="Camera 1", area="A1")
        SpeakerDevice.objects.create(
            speaker_code="SPK-001",
            name="Speaker 1",
            ip_address="192.0.2.120",
            port=5060,
            is_active=True,
        )

    def test_local_device_summary_and_two_panel_layout(self):
        response = self.client.get(reverse("settings_app:station_settings"))
        self.assertEqual(response.status_code, 200)
        html = response.content.decode("utf-8")

        self.assertIn("線上攝影機", html)
        self.assertIn("線上廣播喇叭", html)
        self.assertNotIn("已建立映射", html)
        self.assertIn('class="local-device-grid"', html)
        self.assertIn('class="local-device-panel camera-device-panel"', html)
        self.assertIn('class="local-device-panel speaker-device-panel"', html)
