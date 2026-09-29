import json
from unittest.mock import patch

from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.urls import reverse

from apps.ai_bridge.models import AIModel, InferenceHost
from apps.cameras.models import Camera
from apps.notifications.models import SpeakerDevice


class V662SettingsAdjustmentTests(TestCase):
    def setUp(self):
        admin_group, _ = Group.objects.get_or_create(name="Administrator")
        self.user = User.objects.create_user("v662-admin", password="pass-123456")
        self.user.groups.add(admin_group)
        self.client.force_login(self.user)
        self.host = InferenceHost.objects.create(
            host_code="INF-KRTC-ST-001-01",
            name="Physical Inference Host",
            base_url="http://192.168.6.20:8000",
            ip_address="192.168.6.20",
            status="online",
            is_active=True,
        )
        self.camera = Camera.objects.create(
            camera_code="CAM-001", name="Camera 1", area="A1",
            rtsp_url="rtsp://192.0.2.90:554/live", status="online",
            is_online=True, is_active=True,
        )
        self.speaker = SpeakerDevice.objects.create(
            speaker_code="SPK-001", name="Speaker 1", ip_address="192.0.2.120",
            port=5060, status="online", is_active=True,
        )
        AIModel.objects.create(
            model_code="MODEL-001", name="Model 1", confidence_threshold=0.8, is_active=True,
        )

    def test_settings_page_uses_v662_labels_and_network_location(self):
        response = self.client.get(reverse("settings_app:station_settings"))
        self.assertEqual(response.status_code, 200)
        html = response.content.decode("utf-8")
        self.assertIn("連線主機", html)
        self.assertIn("網路位置", html)
        self.assertIn("192.168.6.20", html)
        self.assertIn("網路端點", html)
        self.assertIn("執行操作", html)
        self.assertIn("IP 廣播喇叭", html)
        self.assertNotIn("<th>測試端點</th>", html)
        self.assertNotIn("<th>映射</th>", html)
        self.assertIn("static-diagnostic-integrity-items", html)

    @patch("apps.settings_app.views._tcp_probe", return_value=(False, 12, "TCP test failed"))
    def test_speaker_probe_persists_offline_status_and_returns_dynamic_status(self, _probe):
        response = self.client.post(
            reverse("settings_app:test_speaker"),
            data=json.dumps({"id": self.speaker.id}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.speaker.refresh_from_db()
        self.assertFalse(payload["success"])
        self.assertEqual(payload["status"], "offline")
        self.assertEqual(payload["status_label"], "離線")
        self.assertEqual(self.speaker.status, "offline")

    def test_settings_summary_counts_enabled_speakers_even_when_health_monitor_is_disabled(self):
        SpeakerDevice.objects.create(
            speaker_code="SPK-002", name="Speaker 2", ip_address="192.0.2.121",
            port=5060, status="offline", is_active=True, health_monitor_enabled=False,
        )
        response = self.client.get(reverse("settings_app:station_settings"))
        self.assertEqual(response.context["active_speaker_count"], 2)
        self.assertEqual(response.context["online_speaker_count"], 1)
