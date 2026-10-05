import json
import subprocess
from unittest.mock import Mock, patch

from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.urls import reverse

from apps.notifications.models import SpeakerDevice
from apps.notifications.speaker_health import SPEAKER_FAULT_CODE
from apps.settings_app.views import _speaker_reachability_probe
from apps.station_api.models import DeviceFaultLog


class SpeakerReachabilityHelperTests(TestCase):
    @patch("apps.settings_app.views.subprocess.run")
    def test_icmp_success_uses_safe_windows_ping_arguments(self, run_mock):
        run_mock.return_value = Mock(returncode=0)

        ok, elapsed_ms, message = _speaker_reachability_probe(
            "192.168.6.120", timeout=2
        )

        self.assertTrue(ok)
        self.assertGreaterEqual(elapsed_ms, 0)
        self.assertEqual(message, "Speaker 192.168.6.120 網路可達。")
        run_mock.assert_called_once_with(
            ["ping.exe", "-n", "1", "-w", "2000", "192.168.6.120"],
            shell=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=3.0,
            check=False,
        )

    @patch("apps.settings_app.views.subprocess.run")
    def test_icmp_nonzero_exit_is_unreachable_without_output_parsing(self, run_mock):
        run_mock.return_value = Mock(returncode=1)

        ok, elapsed_ms, message = _speaker_reachability_probe("10.7.57.107")

        self.assertFalse(ok)
        self.assertGreaterEqual(elapsed_ms, 0)
        self.assertEqual(
            message,
            "Speaker 10.7.57.107 無法由目前 AIO 網路到達。",
        )

    @patch(
        "apps.settings_app.views.subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd="ping.exe", timeout=4),
    )
    def test_icmp_process_timeout_is_unreachable(self, _run_mock):
        ok, _elapsed_ms, message = _speaker_reachability_probe("192.0.2.120")

        self.assertFalse(ok)
        self.assertIn("無法由目前 AIO 網路到達", message)


class SpeakerHealthEndpointTests(TestCase):
    def setUp(self):
        admin_group, _ = Group.objects.get_or_create(name="Administrator")
        self.user = User.objects.create_user(
            "speaker-health-admin", password="pass-123456"
        )
        self.user.groups.add(admin_group)
        self.client.force_login(self.user)
        self.speaker = SpeakerDevice.objects.create(
            speaker_code="SPK-001",
            name="314測試用",
            ip_address="192.168.6.120",
            port=5060,
            protocol=SpeakerDevice.PROTOCOL_SIP,
            username="voip",
            status=SpeakerDevice.STATUS_UNKNOWN,
            is_active=True,
            deployment_state=SpeakerDevice.DEPLOYMENT_DEPLOYED,
            health_monitor_enabled=True,
        )

    def _post_test(self):
        return self.client.post(
            reverse("settings_app:test_speaker"),
            data=json.dumps({"id": self.speaker.id}),
            content_type="application/json",
        )

    @patch("apps.settings_app.views.record_speaker_probe_result")
    @patch(
        "apps.settings_app.views._tcp_probe",
        side_effect=AssertionError("Speaker 不應呼叫 TCP probe"),
    )
    @patch(
        "apps.settings_app.views._speaker_reachability_probe",
        return_value=(True, 4, "Speaker 192.168.6.120 網路可達。"),
    )
    def test_icmp_success_marks_online_and_records_result(
        self, reachability_mock, tcp_mock, record_mock
    ):
        record_mock.return_value = "recovered"

        response = self._post_test()

        self.assertEqual(response.status_code, 200)
        self.speaker.refresh_from_db()
        self.assertEqual(self.speaker.status, SpeakerDevice.STATUS_ONLINE)
        self.assertTrue(response.json()["success"])
        self.assertEqual(response.json()["system_log_action"], "recovered")
        reachability_mock.assert_called_once_with("192.168.6.120")
        tcp_mock.assert_not_called()
        record_mock.assert_called_once()
        recorded_speaker, recorded_ok, recorded_message = record_mock.call_args.args
        self.assertEqual(recorded_speaker.pk, self.speaker.pk)
        self.assertTrue(recorded_ok)
        self.assertIn("網路可達", recorded_message)

    @patch(
        "apps.settings_app.views._speaker_reachability_probe",
        return_value=(False, 7, "Speaker 192.168.6.120 無法由目前 AIO 網路到達。"),
    )
    def test_icmp_failure_marks_offline_and_creates_active_fault(self, _probe):
        response = self._post_test()

        self.assertEqual(response.status_code, 200)
        self.speaker.refresh_from_db()
        self.assertEqual(self.speaker.status, SpeakerDevice.STATUS_OFFLINE)
        self.assertFalse(response.json()["success"])
        fault = DeviceFaultLog.objects.get(
            device_type=DeviceFaultLog.DEVICE_SPEAKER,
            device_code=self.speaker.speaker_code,
            fault_code=SPEAKER_FAULT_CODE,
        )
        self.assertEqual(fault.status, DeviceFaultLog.STATUS_ACTIVE)
        self.assertIn("無法由目前 AIO 網路到達", fault.fault_description)

    @patch(
        "apps.settings_app.views._speaker_reachability_probe",
        side_effect=[
            (False, 7, "Speaker network unreachable"),
            (True, 3, "Speaker network reachable"),
        ],
    )
    def test_icmp_success_recovers_existing_fault(self, _probe):
        self._post_test()
        self._post_test()

        fault = DeviceFaultLog.objects.get(
            device_code=self.speaker.speaker_code,
            fault_code=SPEAKER_FAULT_CODE,
        )
        self.assertEqual(fault.status, DeviceFaultLog.STATUS_RECOVERED)
        self.assertIsNotNone(fault.recovered_at)

    @patch(
        "apps.settings_app.views._speaker_reachability_probe",
        return_value=(False, 7, "Speaker network unreachable"),
    )
    def test_disabled_monitoring_does_not_create_active_fault(self, _probe):
        self.speaker.health_monitor_enabled = False
        self.speaker.save(update_fields=["health_monitor_enabled", "updated_at"])

        response = self._post_test()

        self.assertEqual(response.json()["system_log_action"], "skipped")
        self.assertFalse(
            DeviceFaultLog.objects.filter(
                device_code=self.speaker.speaker_code,
                fault_code=SPEAKER_FAULT_CODE,
                status=DeviceFaultLog.STATUS_ACTIVE,
            ).exists()
        )

    @patch("apps.settings_app.views._speaker_reachability_probe")
    def test_routed_and_same_subnet_addresses_use_identical_probe_flow(self, probe):
        probe.return_value = (True, 2, "Speaker network reachable")
        self._post_test()

        self.speaker.ip_address = "10.7.57.107"
        self.speaker.save(update_fields=["ip_address", "updated_at"])
        self._post_test()

        self.assertEqual(
            [call.args[0] for call in probe.call_args_list],
            ["192.168.6.120", "10.7.57.107"],
        )

    @patch(
        "apps.settings_app.views._speaker_reachability_probe",
        return_value=(True, 2, "Speaker network reachable"),
    )
    @patch(
        "apps.settings_app.views._tcp_probe",
        return_value=(False, 1, "TCP 192.168.6.120:5060 連線失敗"),
    )
    def test_closed_sip_tcp_port_does_not_affect_speaker_health(
        self, tcp_mock, _reachability_mock
    ):
        response = self._post_test()

        self.assertTrue(response.json()["success"])
        self.assertEqual(response.json()["status"], SpeakerDevice.STATUS_ONLINE)
        tcp_mock.assert_not_called()
