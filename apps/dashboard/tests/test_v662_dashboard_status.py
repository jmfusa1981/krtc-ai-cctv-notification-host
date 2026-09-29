from datetime import timedelta

from django.test import TestCase, override_settings
from django.utils import timezone

from apps.ai_bridge.models import InferenceConnectionState, InferenceHost
from apps.dashboard.views import get_inference_host_summary, get_speaker_summary
from apps.notifications.models import SpeakerDevice


@override_settings(INFERENCE_HEALTH_STALE_SECONDS=20)
class V662DashboardStatusTests(TestCase):
    def create_speaker(self, code, status):
        return SpeakerDevice.objects.create(
            speaker_code=code,
            name=code,
            ip_address=f"192.0.2.{10 + SpeakerDevice.objects.count()}",
            port=5060,
            is_active=True,
            status=status,
        )

    def test_speaker_summary_shows_fraction_when_any_registered_speaker_is_not_online(self):
        self.create_speaker("SPK-001", "online")
        self.create_speaker("SPK-002", "online")
        self.create_speaker("SPK-003", "online")
        self.create_speaker("SPK-004", "offline")
        summary = get_speaker_summary()
        self.assertEqual(summary["registered_count"], 4)
        self.assertEqual(summary["online_count"], 3)
        self.assertEqual(summary["display_value"], "3/4")
        self.assertTrue(summary["is_abnormal"])

    def test_speaker_summary_shows_total_when_all_registered_speakers_are_online(self):
        for index in range(4):
            self.create_speaker(f"SPK-{index + 1:03d}", "online")
        summary = get_speaker_summary()
        self.assertEqual(summary["display_value"], "4")
        self.assertFalse(summary["is_abnormal"])

    def test_inference_summary_returns_abnormal_host_names_for_dashboard_rows(self):
        first = InferenceHost.objects.create(
            host_code="INF-001", name="Physical Inference Host 1",
            base_url="http://192.0.2.20:8000", is_active=True,
        )
        second = InferenceHost.objects.create(
            host_code="INF-002", name="Physical Inference Host 2",
            base_url="http://192.0.2.21:8000", is_active=True,
        )
        InferenceConnectionState.objects.create(
            inference_host=first, health_status="ok", last_heartbeat_at=timezone.now(),
        )
        InferenceConnectionState.objects.create(
            inference_host=second, health_status="offline", last_heartbeat_at=timezone.now(),
        )
        summary = get_inference_host_summary()
        self.assertEqual(summary["abnormal_host_codes"], ["INF-002"])
        self.assertEqual(summary["abnormal_host_names"], ["Physical Inference Host 2"])
        self.assertEqual(summary["detail_label"], "1 台主機異常")
