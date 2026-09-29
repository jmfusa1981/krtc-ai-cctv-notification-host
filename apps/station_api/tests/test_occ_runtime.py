import json
import tempfile
from datetime import timedelta
from pathlib import Path

from django.test import TestCase, override_settings
from django.utils import timezone

from apps.station_api.models import DeviceFaultLog
from apps.station_api.occ_runtime import read_runtime_status, write_runtime_status
from apps.station_api.service_watchdog import (
    _occ_sync_service_health,
    evaluate_services,
)


class OccRuntimeTests(TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.status_path = Path(self.temporary_directory.name) / "occ-status.json"
        self.settings_override = override_settings(
            KRTC_OCC_SERVICE_STATUS_PATH=self.status_path,
            KRTC_OCC_SYNC_ENABLED=True,
            KRTC_OFFLINE_THRESHOLD=90,
            PAO_WATCHDOG_MONITOR_INFERENCE_POLLING=False,
            PAO_WATCHDOG_MONITOR_BROADCAST_SCHEDULER=False,
            PAO_WATCHDOG_MONITOR_OCC_SYNC_SERVICE=True,
            KRTC_NOTIFICATION_HOST_CODE="PAO-TEST-001",
        )
        self.settings_override.enable()

    def tearDown(self):
        self.settings_override.disable()
        self.temporary_directory.cleanup()

    def test_atomic_status_round_trip_contains_only_allowlisted_fields(self):
        write_runtime_status(
            state="running",
            started_at=timezone.now().isoformat(),
            last_error="token=secret password=pw",
            payload={"snapshot": "forbidden"},
            headers={"X-KRTC-API-Key": "forbidden"},
        )
        payload = read_runtime_status()
        raw = self.status_path.read_text(encoding="utf-8")

        self.assertEqual(payload["state"], "running")
        self.assertIn("pid", payload)
        self.assertIn("updated_at", payload)
        self.assertNotIn("payload", payload)
        self.assertNotIn("headers", payload)
        self.assertNotIn("secret", raw)
        self.assertNotIn("pw", raw)

    def test_missing_and_malformed_status_are_unhealthy(self):
        self.assertFalse(_occ_sync_service_health()[0])
        self.status_path.write_text("not-json", encoding="utf-8")
        self.assertFalse(_occ_sync_service_health()[0])

    def test_stale_and_current_status(self):
        stale = {
            "state": "running",
            "updated_at": (timezone.now() - timedelta(seconds=91)).isoformat(),
        }
        self.status_path.write_text(json.dumps(stale), encoding="utf-8")
        self.assertFalse(_occ_sync_service_health()[0])

        write_runtime_status(state="running")
        self.assertTrue(_occ_sync_service_health()[0])

    def test_disabled_sync_skips_liveness_failure(self):
        with override_settings(KRTC_OCC_SYNC_ENABLED=False):
            healthy, description = _occ_sync_service_health()
        self.assertTrue(healthy)
        self.assertIn("disabled", description)

    def test_watchdog_fault_and_recovery(self):
        first = evaluate_services()["occ_sync_service"]
        self.assertFalse(first["healthy"])
        self.assertTrue(
            DeviceFaultLog.objects.filter(
                fault_code="PAO_OCC_SYNC_SERVICE_UNHEALTHY",
                status=DeviceFaultLog.STATUS_ACTIVE,
            ).exists()
        )

        write_runtime_status(state="running")
        second = evaluate_services()["occ_sync_service"]
        self.assertTrue(second["healthy"])
        self.assertTrue(
            DeviceFaultLog.objects.filter(
                fault_code="PAO_OCC_SYNC_SERVICE_UNHEALTHY",
                status=DeviceFaultLog.STATUS_RECOVERED,
            ).exists()
        )
