from pathlib import Path

from django.contrib.auth.models import Group, User
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.notifications.runtime_config import get_broadcast_runtime_config
from apps.settings_app.models import BroadcastEngineeringSettings
from apps.station_api.models import SecurityAuditLog


class BroadcastRuntimeModeResolutionTests(TestCase):
    def setUp(self):
        BroadcastEngineeringSettings.objects.all().delete()

    @override_settings(
        KRTC_PRODUCTION=False,
        BROADCAST_PLAYBACK_MODE="simulation",
    )
    def test_fresh_development_defaults_to_simulation(self):
        runtime = get_broadcast_runtime_config()

        self.assertEqual(runtime.environment, "development")
        self.assertEqual(runtime.operational_backend, "simulation")
        self.assertEqual(runtime.source, "django-settings")

    @override_settings(
        KRTC_PRODUCTION=False,
        BROADCAST_PLAYBACK_MODE="pjsip",
    )
    def test_development_legacy_environment_remains_bootstrap_fallback(self):
        runtime = get_broadcast_runtime_config()

        self.assertEqual(runtime.operational_backend, "pjsip")
        self.assertEqual(runtime.source, "django-settings")

    @override_settings(
        KRTC_PRODUCTION=False,
        BROADCAST_PLAYBACK_MODE="simulation",
    )
    def test_development_engineering_selection_pjsip_uses_database_values(self):
        engineering = BroadcastEngineeringSettings.objects.create(
            broadcast_test_mode=False,
            pjsip_executable_path=r"C:\KRTC\runtime\pjsua.exe",
            pjsip_local_ip="140.124.42.72",
            pjsip_advertise_ip="140.124.42.72",
            pjsip_local_sip_port_base=64882,
            pjsip_local_rtp_port_base=4004,
            pjsip_port_step=2,
            pjsip_audio_gain_percent=100,
        )

        runtime = get_broadcast_runtime_config()

        self.assertEqual(runtime.operational_backend, "pjsip")
        self.assertEqual(runtime.source, "broadcast-engineering-settings")
        self.assertEqual(
            runtime.pjsip_executable_path,
            engineering.pjsip_executable_path,
        )
        self.assertEqual(runtime.pjsip_local_ip, "140.124.42.72")
        self.assertEqual(runtime.pjsip_advertise_ip, "140.124.42.72")
        self.assertEqual(runtime.pjsip_local_sip_port_base, 64882)
        self.assertEqual(runtime.pjsip_local_rtp_port_base, 4004)
        self.assertEqual(runtime.pjsip_port_step, 2)
        self.assertEqual(runtime.pjsip_audio_gain_percent, 100.0)

    @override_settings(
        KRTC_PRODUCTION=False,
        BROADCAST_PLAYBACK_MODE="pjsip",
    )
    def test_development_engineering_test_mode_uses_simulation(self):
        BroadcastEngineeringSettings.objects.create(broadcast_test_mode=True)

        self.assertEqual(
            get_broadcast_runtime_config().operational_backend,
            "simulation",
        )

    @override_settings(
        KRTC_PRODUCTION=True,
        BROADCAST_PLAYBACK_MODE="simulation",
    )
    def test_fresh_production_defaults_to_pjsip(self):
        runtime = get_broadcast_runtime_config()

        self.assertEqual(runtime.environment, "production")
        self.assertEqual(runtime.operational_backend, "pjsip")

    @override_settings(
        KRTC_PRODUCTION=True,
        BROADCAST_PLAYBACK_MODE="pjsip",
    )
    def test_production_engineering_test_mode_uses_simulation(self):
        BroadcastEngineeringSettings.objects.create(broadcast_test_mode=True)

        self.assertEqual(
            get_broadcast_runtime_config().operational_backend,
            "simulation",
        )

    @override_settings(
        KRTC_PRODUCTION=False,
        BROADCAST_PLAYBACK_MODE="simulation",
    )
    def test_switching_back_from_simulation_uses_pjsip(self):
        engineering = BroadcastEngineeringSettings.objects.create(
            broadcast_test_mode=True
        )
        self.assertEqual(
            get_broadcast_runtime_config().operational_backend,
            "simulation",
        )

        engineering.broadcast_test_mode = False
        engineering.save(update_fields=["broadcast_test_mode", "updated_at"])

        self.assertEqual(
            get_broadcast_runtime_config().operational_backend,
            "pjsip",
        )

    def test_production_environment_example_defaults_to_pjsip(self):
        template = (
            Path(__file__).resolve().parents[3]
            / "config"
            / "production.env.example"
        ).read_text(encoding="utf-8")

        self.assertIn("BROADCAST_PLAYBACK_MODE=pjsip", template)
        self.assertNotIn("BROADCAST_PLAYBACK_MODE=simulation", template)


class BroadcastRuntimeModeAdminTests(TestCase):
    def setUp(self):
        self.engineering = BroadcastEngineeringSettings.objects.create(
            broadcast_test_mode=True,
            pjsip_executable_path=r"C:\KRTC\runtime\pjsua.exe",
            pjsip_local_ip="140.124.42.72",
            pjsip_advertise_ip="140.124.42.72",
            pjsip_local_sip_port_base=64882,
            pjsip_local_rtp_port_base=4004,
            pjsip_port_step=2,
            pjsip_audio_gain_percent=100,
        )
        self.change_url = reverse(
            "admin:settings_app_broadcastengineeringsettings_change",
            args=[self.engineering.pk],
        )

    def _post_mode(self, mode):
        return self.client.post(
            self.change_url,
            {
                "broadcast_test_mode": mode,
                "pjsip_executable_path": (
                    self.engineering.pjsip_executable_path
                ),
                "pjsip_local_ip": self.engineering.pjsip_local_ip,
                "pjsip_advertise_ip": self.engineering.pjsip_advertise_ip,
                "pjsip_local_sip_port_base": (
                    self.engineering.pjsip_local_sip_port_base
                ),
                "pjsip_local_rtp_port_base": (
                    self.engineering.pjsip_local_rtp_port_base
                ),
                "pjsip_port_step": self.engineering.pjsip_port_step,
                "pjsip_audio_gain_percent": (
                    self.engineering.pjsip_audio_gain_percent
                ),
                "_save": "儲存",
            },
        )

    def test_superuser_can_switch_to_pjsip_and_change_is_audited(self):
        superuser = User.objects.create_superuser(
            username="skynet",
            password="test-only-password",
        )
        self.client.force_login(superuser)

        form_response = self.client.get(self.change_url)
        self.assertContains(form_response, "正式模式（PJSIP）")
        self.assertContains(form_response, "測試模式（Simulation）")
        self.assertContains(form_response, "會實際呼叫站區 IP Speaker")
        self.assertContains(form_response, "不呼叫實體 Speaker")

        response = self._post_mode("formal")

        self.assertEqual(response.status_code, 302)
        self.engineering.refresh_from_db()
        self.assertFalse(self.engineering.broadcast_test_mode)
        self.assertEqual(
            get_broadcast_runtime_config().operational_backend,
            "pjsip",
        )
        audit = SecurityAuditLog.objects.get(
            action="BROADCAST_RUNTIME_MODE_CHANGED"
        )
        self.assertEqual(audit.username, "skynet")
        self.assertEqual(audit.role, "Superuser")
        self.assertEqual(audit.metadata["old_mode"], "simulation")
        self.assertEqual(audit.metadata["new_mode"], "pjsip")
        self.assertIsNotNone(audit.occurred_at)

    def test_non_superuser_roles_cannot_mutate_engineering_mode(self):
        for role in ("Administrator", "Maintainer", "Operator"):
            group, _ = Group.objects.get_or_create(name=role)
            user = User.objects.create_user(
                username=f"runtime-{role.lower()}",
                password="test-only-password",
                is_staff=True,
            )
            user.groups.add(group)
            self.client.force_login(user)

            response = self._post_mode("formal")

            self.assertEqual(response.status_code, 404)
            self.engineering.refresh_from_db()
            self.assertTrue(self.engineering.broadcast_test_mode)

        self.assertFalse(
            SecurityAuditLog.objects.filter(
                action="BROADCAST_RUNTIME_MODE_CHANGED"
            ).exists()
        )
