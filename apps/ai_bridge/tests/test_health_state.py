import json
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.ai_bridge.models import InferenceConnectionState, InferenceHost
from apps.ai_bridge.services.health_state import (
    HEALTHY,
    STALE,
    UNREACHABLE,
    effective_inference_health,
    inference_health_stale_seconds,
    record_inference_health_observation,
)
from apps.ai_bridge.services.inference_client import InferenceConnectionError


@override_settings(
    INFERENCE_POLL_INTERVAL_SECONDS=5,
    INFERENCE_HEALTH_STALE_SECONDS=60,
)
class InferenceHealthStateTests(TestCase):
    """驗證手動、背景與Dashboard共用相同健康觀測語意。"""

    def setUp(self):
        self.host = InferenceHost.objects.create(
            host_code="INF-HEALTH-001",
            name="Inference Health Host",
            base_url="http://192.0.2.20:8000",
            is_active=True,
        )

    def test_success_failure_and_recovery_use_existing_canonical_fields(self):
        observed_at = timezone.now()
        record_inference_health_observation(
            self.host,
            success=True,
            checked_at=observed_at,
            health_status="ok",
        )

        self.host.refresh_from_db()
        state = self.host.connection_state
        self.assertEqual(state.health_status, "ok")
        self.assertEqual(state.last_heartbeat_at, observed_at)
        self.assertEqual(self.host.last_health_at, observed_at)
        self.assertEqual(self.host.last_success_at, observed_at)
        self.assertEqual(
            effective_inference_health(self.host).effective_health,
            HEALTHY,
        )

        record_inference_health_observation(
            self.host,
            success=False,
            health_status="offline",
            failure_reason="connection refused",
        )
        self.host.refresh_from_db()
        self.assertEqual(
            effective_inference_health(self.host).effective_health,
            UNREACHABLE,
        )

        record_inference_health_observation(
            self.host,
            success=True,
            health_status="ok",
        )
        self.host.refresh_from_db()
        self.assertEqual(
            effective_inference_health(self.host).effective_health,
            HEALTHY,
        )

    def test_stale_threshold_is_not_shorter_than_three_poll_cycles(self):
        with override_settings(
            INFERENCE_POLL_INTERVAL_SECONDS=30,
            INFERENCE_HEALTH_STALE_SECONDS=20,
        ):
            self.assertEqual(inference_health_stale_seconds(), 90)

    def test_previous_success_becomes_stale_after_threshold(self):
        checked_at = timezone.now() - timedelta(seconds=61)
        state = InferenceConnectionState.objects.create(
            inference_host=self.host,
            health_status="ok",
            last_heartbeat_at=checked_at,
        )
        self.host.last_success_at = checked_at
        self.host.save(update_fields=["last_success_at"])

        health = effective_inference_health(self.host)

        self.assertEqual(health.effective_health, STALE)
        self.assertGreaterEqual(health.age_seconds, 61)
        self.assertEqual(state.health_status, "ok")

    @patch("apps.settings_app.views.InferenceClient.health")
    def test_manual_health_success_updates_canonical_state(self, health):
        health.return_value = {"status": "ok", "version": "lab-1"}
        user = get_user_model().objects.create_user(
            "health-tester",
            password="test-pass",
        )
        self.client.force_login(user)

        response = self.client.post(
            reverse("settings_app:test_inference_host"),
            data=json.dumps({"id": self.host.id}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["success"])
        self.host.refresh_from_db()
        self.assertEqual(self.host.connection_state.health_status, "ok")
        self.assertEqual(
            effective_inference_health(self.host).effective_health,
            HEALTHY,
        )

    @patch("apps.ai_bridge.services.inference_client.InferenceClient.get_events")
    @patch("apps.ai_bridge.services.inference_client.InferenceClient.health")
    def test_background_poll_success_updates_canonical_state(
        self,
        health,
        get_events,
    ):
        health.return_value = {"status": "ok", "version": "lab-2"}
        get_events.return_value = {"items": []}

        call_command(
            "poll_inference_hosts",
            once=True,
            host_codes=[self.host.host_code],
            verbosity=0,
        )

        self.host.refresh_from_db()
        self.assertEqual(self.host.connection_state.health_status, "ok")
        self.assertEqual(
            effective_inference_health(self.host).effective_health,
            HEALTHY,
        )

    @patch("apps.ai_bridge.services.inference_client.InferenceClient.health")
    def test_background_poll_failure_records_unreachable(self, health):
        health.side_effect = InferenceConnectionError("connection refused")

        call_command(
            "poll_inference_hosts",
            once=True,
            host_codes=[self.host.host_code],
            verbosity=0,
        )

        self.host.refresh_from_db()
        self.assertEqual(self.host.connection_state.health_status, "offline")
        effective = effective_inference_health(self.host)
        self.assertEqual(effective.effective_health, UNREACHABLE)
        self.assertIn("connection refused", effective.failure_reason)

    @patch("apps.ai_bridge.services.inference_client.InferenceClient.get_events")
    @patch("apps.ai_bridge.services.inference_client.InferenceClient.health")
    def test_event_fetch_failure_does_not_overwrite_successful_health(
        self,
        health,
        get_events,
    ):
        health.return_value = {"status": "ok"}
        get_events.side_effect = InferenceConnectionError("events unavailable")

        call_command(
            "poll_inference_hosts",
            once=True,
            host_codes=[self.host.host_code],
            verbosity=0,
        )

        self.host.refresh_from_db()
        self.assertEqual(self.host.connection_state.health_status, "ok")
        self.assertEqual(
            effective_inference_health(self.host).effective_health,
            HEALTHY,
        )
