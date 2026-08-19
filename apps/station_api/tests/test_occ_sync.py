from datetime import datetime, timedelta
from unittest.mock import Mock

import requests
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.ai_bridge.models import InferenceHost
from apps.cameras.models import Camera
from apps.events.models import Event
from apps.station_api.models import OccSyncLog, OccSyncState
from apps.station_api.occ_sync import OccSyncClient, OccSyncError, daily_sync_due


class FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {"status": "accepted"}
        self.content = b"{}"
        self.text = "{}"

    def json(self):
        return self._payload


@override_settings(
    KRTC_OCC_API_TOKEN="occ-secret",
    KRTC_MAINTENANCE_API_BASE_URL="http://occ.example",
    KRTC_STATION_CODE="TEST-STATION",
    KRTC_NOTIFICATION_HOST_CODE="PAO-TEST-001",
    KRTC_NOTIFICATION_HOST_IP="192.168.6.25",
    KRTC_OCC_VERIFY_TLS=True,
    KRTC_OCC_EVENT_BATCH_SIZE=100,
    KRTC_OCC_DAILY_SYNC_HOUR=2,
)
class OccSyncTests(TestCase):
    def setUp(self):
        self.session = Mock()
        self.session.post.return_value = FakeResponse()
        self.sleep = Mock()
        self.client_sync = OccSyncClient(session=self.session, sleep=self.sleep)
        self.camera = Camera.objects.create(camera_code="CAM-001", name="Camera", area="A", status="online")
        InferenceHost.objects.create(host_code="INF-TEST-001", name="Inference", base_url="http://inference.example", status="online")

    def test_heartbeat_matches_occ_1_0_and_advances_sequence(self):
        self.client_sync.send_heartbeat()
        kwargs = self.session.post.call_args.kwargs
        self.assertEqual(kwargs["headers"]["X-KRTC-API-Key"], "occ-secret")
        self.assertNotIn("Authorization", kwargs["headers"])
        self.assertEqual(kwargs["headers"]["Idempotency-Key"], "PAO-TEST-001-0")
        self.assertEqual(kwargs["json"]["schema_version"], "1.0")
        self.assertEqual(kwargs["json"]["sequence"], 0)
        self.assertEqual(kwargs["json"]["host_status"], "online")
        self.assertNotIn("status", kwargs["json"])
        self.assertEqual(kwargs["json"]["host"]["ip_address"], "192.168.6.25")
        self.assertIn("+08:00", kwargs["json"]["sent_at"])
        self.assertIsNotNone(OccSyncState.load().last_heartbeat_at)
        self.assertEqual(OccSyncState.load().heartbeat_sequence, 1)

    def test_failed_heartbeat_reuses_sequence(self):
        self.session.post.side_effect = requests.ConnectionError("offline")
        with self.assertRaises(OccSyncError):
            self.client_sync.send_heartbeat()
        self.assertEqual(OccSyncState.load().heartbeat_sequence, 0)

    def test_duplicate_heartbeat_is_success_and_advances_sequence(self):
        self.session.post.return_value = FakeResponse(200, {"status": "duplicate"})
        result = self.client_sync.send_heartbeat()
        self.assertEqual(result["status"], "duplicate")
        self.assertEqual(OccSyncState.load().heartbeat_sequence, 1)

    def test_occ_validation_body_is_logged_without_token(self):
        response = FakeResponse(400, {"detail": "invalid"})
        response.text = 'field invalid token=occ-secret'
        self.session.post.return_value = response
        with self.assertRaises(OccSyncError):
            self.client_sync.send_heartbeat()
        log = OccSyncLog.objects.get(kind="heartbeat")
        self.assertIn("field invalid", log.error)
        self.assertNotIn("occ-secret", log.error)

    def test_event_cursor_advances_only_after_success(self):
        event = Event.objects.create(camera=self.camera, event_type="luggage_roll", source_host="INF-TEST-001", source_event_id="E-1")
        result = self.client_sync.send_pending_events()
        self.assertEqual(result["count"], 1)
        self.assertEqual(OccSyncState.load().last_event_id, event.id)
        self.assertEqual(self.client_sync.send_pending_events()["count"], 0)

    def test_failed_event_upload_preserves_cursor_and_retries(self):
        Event.objects.create(camera=self.camera, event_type="luggage_roll", source_host="INF-TEST-001", source_event_id="E-2")
        self.session.post.side_effect = requests.ConnectionError("offline token=must-not-be-logged")
        with self.assertRaises(OccSyncError):
            self.client_sync.send_pending_events()
        self.assertEqual(OccSyncState.load().last_event_id, 0)
        self.assertEqual(self.session.post.call_count, 3)
        self.assertEqual(self.sleep.call_count, 2)
        log = OccSyncLog.objects.get()
        self.assertEqual(log.status, "failed")
        self.assertNotIn("must-not-be-logged", log.error)

    def test_device_payload_uses_codes_not_ip_identity(self):
        self.client_sync.send_device_status()
        payload = self.session.post.call_args.kwargs["json"]
        self.assertEqual(payload["notification_host_code"], "PAO-TEST-001")
        self.assertEqual(payload["cameras"][0]["camera_code"], "CAM-001")
        self.assertEqual(payload["inference_hosts"][0]["host_code"], "INF-TEST-001")

    def test_daily_sync_has_stable_idempotency_key(self):
        target = timezone.localdate() - timedelta(days=1)
        self.client_sync.send_daily_sync(target)
        first = self.session.post.call_args.kwargs["json"]
        self.client_sync.send_daily_sync(target)
        second = self.session.post.call_args.kwargs["json"]
        self.assertEqual(first["idempotency_key"], second["idempotency_key"])
        self.assertEqual(first["summary_date"], target.isoformat())

    def test_daily_due_runs_once_after_two_am(self):
        tz = timezone.get_current_timezone()
        now = timezone.make_aware(datetime(2026, 8, 2, 2, 1), tz)
        self.assertTrue(daily_sync_due(now))
        state = OccSyncState.load()
        state.last_daily_sync_at = now
        state.save(update_fields=["last_daily_sync_at"])
        self.assertFalse(daily_sync_due(now + timedelta(hours=1)))
