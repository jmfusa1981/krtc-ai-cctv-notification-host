from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.urls import reverse

from apps.ai_bridge.models import InferenceHost


class FrontendManagementPermissionTests(TestCase):
    def setUp(self):
        self.operator_group = Group.objects.create(name="Operator")
        self.maintainer_group = Group.objects.create(name="Maintainer")
        self.operator = User.objects.create_user("operator", password="test-pass")
        self.operator.groups.add(self.operator_group)
        self.maintainer = User.objects.create_user("maintainer", password="test-pass")
        self.maintainer.groups.add(self.maintainer_group)
        self.superuser = User.objects.create_superuser("root", "root@example.com", "test-pass")

    def test_operator_cannot_open_management_form(self):
        self.client.force_login(self.operator)
        response = self.client.get(reverse("settings_app:manage_new", args=["inference-host"]))
        self.assertEqual(response.status_code, 403)

    def test_maintainer_can_open_management_form(self):
        self.client.force_login(self.maintainer)
        response = self.client.get(reverse("settings_app:manage_new", args=["inference-host"]))
        self.assertEqual(response.status_code, 200)

    def test_superuser_can_create_inference_host(self):
        self.client.force_login(self.superuser)
        response = self.client.post(reverse("settings_app:manage_new", args=["inference-host"]), {
            "host_code": "INF-UI-001",
            "name": "UI managed host",
            "station_code": "KRTC-ST-001",
            "host_type": "physical",
            "ip_address": "192.168.6.30",
            "port": 8000,
            "base_url": "http://192.168.6.30:8000",
            "health_url": "http://192.168.6.30:8000/health",
            "events_url": "http://192.168.6.30:8000/api/notify/events",
            "websocket_url": "ws://192.168.6.30:8000/ws/alerts",
            "websocket_auth_mode": "none",
            "timeout_seconds": 10,
            "is_active": "on",
            "description": "created by frontend test",
        })
        self.assertEqual(response.status_code, 302)
        self.assertTrue(InferenceHost.objects.filter(host_code="INF-UI-001").exists())
