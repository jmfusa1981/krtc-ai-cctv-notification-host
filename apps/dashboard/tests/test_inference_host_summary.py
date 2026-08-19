from datetime import timedelta

from django.test import TestCase, override_settings
from django.utils import timezone

from apps.ai_bridge.models import InferenceConnectionState, InferenceHost
from apps.dashboard.views import get_inference_host_summary


@override_settings(INFERENCE_HEALTH_STALE_SECONDS=20)
class InferenceHostSummaryTests(TestCase):
    def create_host(self, *, code, active=True, generic_status=InferenceHost.STATUS_UNKNOWN):
        return InferenceHost.objects.create(
            host_code=code,
            name=code,
            base_url=f"http://127.0.0.1:{8100 + InferenceHost.objects.count()}",
            status=generic_status,
            is_active=active,
        )

    def set_health(self, host, *, status, checked_at=None, websocket_status="disconnected"):
        return InferenceConnectionState.objects.update_or_create(
            inference_host=host,
            defaults={
                "health_status": status,
                "last_heartbeat_at": checked_at or timezone.now(),
                "websocket_status": websocket_status,
                "connected": websocket_status == "connected",
            },
        )[0]

    def test_no_active_hosts_returns_unconfigured(self):
        self.create_host(code="INF-DISABLED", active=False)
        summary = get_inference_host_summary()
        self.assertEqual(summary["status_label"], "未設定主機")
        self.assertEqual(summary["detail_label"], "尚未設定推論主機")
        self.assertTrue(summary["is_unconfigured"])

    def test_fresh_health_ok_returns_normal_even_if_generic_status_is_offline(self):
        host = self.create_host(code="INF-001", generic_status=InferenceHost.STATUS_OFFLINE)
        self.set_health(host, status="ok")
        summary = get_inference_host_summary()
        self.assertEqual(summary["status_label"], "正常")
        self.assertEqual(summary["healthy_count"], 1)

    def test_websocket_connected_does_not_hide_failed_health(self):
        host = self.create_host(code="INF-001", generic_status=InferenceHost.STATUS_ONLINE)
        self.set_health(host, status="offline", websocket_status="connected")
        summary = get_inference_host_summary()
        self.assertEqual(summary["status_label"], "異常")
        self.assertEqual(summary["abnormal_host_codes"], ["INF-001"])

    def test_health_ok_remains_normal_when_websocket_is_disconnected(self):
        host = self.create_host(code="INF-001")
        self.set_health(host, status="ok", websocket_status="disconnected")
        summary = get_inference_host_summary()
        self.assertEqual(summary["status_label"], "正常")

    def test_missing_health_result_is_abnormal(self):
        self.create_host(code="INF-001", generic_status=InferenceHost.STATUS_ONLINE)
        summary = get_inference_host_summary()
        self.assertEqual(summary["status_label"], "異常")
        self.assertEqual(summary["abnormal_host_codes"], ["INF-001"])

    def test_stale_health_result_is_abnormal(self):
        host = self.create_host(code="INF-001")
        self.set_health(
            host,
            status="ok",
            checked_at=timezone.now() - timedelta(seconds=21),
        )
        summary = get_inference_host_summary()
        self.assertEqual(summary["status_label"], "異常")
        self.assertEqual(summary["abnormal_host_codes"], ["INF-001"])

    def test_only_failed_hosts_are_listed(self):
        first = self.create_host(code="INF-001")
        second = self.create_host(code="INF-002")
        third = self.create_host(code="INF-003")
        self.set_health(first, status="ok")
        self.set_health(second, status="offline")
        self.set_health(third, status="error")
        summary = get_inference_host_summary()
        self.assertEqual(summary["detail_label"], "異常：INF-002、INF-003")
        self.assertEqual(summary["abnormal_host_codes"], ["INF-002", "INF-003"])
