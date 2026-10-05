from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase, override_settings

from apps.notifications.models import SpeakerDevice


class PjsipPlaybackCommandSafetyTests(SimpleTestCase):
    @patch(
        "apps.notifications.management.commands.pjsip_play_test."
        "execute_pjsip_playback_plan"
    )
    def test_real_playback_requires_execute_flag(self, execute):
        with self.assertRaisesRegex(CommandError, "--execute is required"):
            call_command(
                "pjsip_play_test",
                speaker="LAB-SPK-001",
                audio="TEST-004",
            )

        execute.assert_not_called()

    @patch(
        "apps.notifications.management.commands.pjsip_play_test."
        "execute_pjsip_playback_plan"
    )
    def test_real_playback_requires_matching_speaker_confirmation(self, execute):
        with self.assertRaisesRegex(CommandError, "must exactly match"):
            call_command(
                "pjsip_play_test",
                speaker="LAB-SPK-001",
                audio="TEST-004",
                execute=True,
                confirm_speaker="OTHER-SPK",
                stdout=StringIO(),
            )

        execute.assert_not_called()


class SpeakerSetupCommandTests(TestCase):
    def setUp(self):
        self.speaker = SpeakerDevice.objects.create(
            speaker_code="LAB-SPK-001",
            name="Lab Speaker",
            ip_address="192.0.2.10",
            port=5060,
            protocol=SpeakerDevice.PROTOCOL_SIP,
            username="legacy",
        )

    def test_explicit_lab_values_resolve_expected_uri(self):
        call_command(
            "apply_verified_speaker_config",
            speaker_code="LAB-SPK-001",
            speaker_ip="192.168.6.120",
            sip_user="voip",
            sip_port=5060,
            apply=True,
            confirm_speaker="LAB-SPK-001",
            stdout=StringIO(),
        )

        self.speaker.refresh_from_db()
        self.assertEqual(str(self.speaker.ip_address), "192.168.6.120")
        self.assertEqual(self.speaker.username, "voip")
        self.assertEqual(
            self.speaker.resolved_sip_uri,
            "sip:voip@192.168.6.120:5060",
        )

    def test_apply_requires_matching_confirmation(self):
        with self.assertRaisesRegex(CommandError, "must exactly match"):
            call_command(
                "apply_verified_speaker_config",
                speaker_code="LAB-SPK-001",
                speaker_ip="192.168.6.120",
                sip_user="voip",
                apply=True,
                confirm_speaker="OTHER-SPK",
                stdout=StringIO(),
            )

        self.speaker.refresh_from_db()
        self.assertEqual(str(self.speaker.ip_address), "192.0.2.10")

    @override_settings(KRTC_PRODUCTION=True)
    def test_demo_apply_is_forbidden_in_production(self):
        with self.assertRaisesRegex(CommandError, "forbidden in production"):
            call_command(
                "initialize_notification_demo",
                apply=True,
                confirm_demo="INITIALIZE-DEMO-DATA",
                stdout=StringIO(),
            )

