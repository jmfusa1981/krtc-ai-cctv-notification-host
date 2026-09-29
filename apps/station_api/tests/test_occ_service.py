import tempfile
import threading
from pathlib import Path
from unittest.mock import Mock, patch

from django.conf import settings
from django.test import TestCase, override_settings

from apps.station_api.management.commands.run_occ_sync_service import (
    OccSyncService,
)
from apps.station_api.models import OccSyncState
from apps.station_api.occ_sync import OccSyncError


@override_settings(KRTC_HEARTBEAT_INTERVAL=5, KRTC_OCC_LOG_RETENTION_DAYS=30)
class OccSyncServiceTests(TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.status_path = Path(self.temporary_directory.name) / "occ-status.json"
        self.settings_override = override_settings(
            KRTC_OCC_SERVICE_STATUS_PATH=self.status_path,
        )
        self.settings_override.enable()
        self.command = Mock()

    def tearDown(self):
        self.settings_override.disable()
        self.temporary_directory.cleanup()

    def test_default_service_uses_separate_clients_and_sessions(self):
        service = OccSyncService()
        self.assertIsNot(service.heartbeat_client, service.worker_client)
        self.assertIsNot(
            service.heartbeat_client.session,
            service.worker_client.session,
        )

    def test_blocked_worker_does_not_block_heartbeat(self):
        heartbeat_called = threading.Event()
        release_worker = threading.Event()
        heartbeat_client = Mock()
        heartbeat_client.send_heartbeat.side_effect = heartbeat_called.set
        worker_client = Mock()
        worker_client.send_pending_events.side_effect = release_worker.wait
        service = OccSyncService(
            heartbeat_client=heartbeat_client,
            worker_client=worker_client,
        )

        with patch(
            "apps.station_api.management.commands.run_occ_sync_service.daily_sync_due",
            return_value=False,
        ):
            runner = threading.Thread(target=service.run, args=(self.command,))
            runner.start()
            self.assertTrue(heartbeat_called.wait(1))
            service.stop_event.set()
            release_worker.set()
            runner.join(2)

        self.assertFalse(runner.is_alive())
        heartbeat_client.send_heartbeat.assert_called()

    def test_unexpected_worker_exception_is_contained(self):
        worker_client = Mock()
        worker_client.send_pending_events.side_effect = RuntimeError("worker failed")
        service = OccSyncService(
            heartbeat_client=Mock(),
            worker_client=worker_client,
        )
        with patch(
            "apps.station_api.management.commands.run_occ_sync_service.daily_sync_due",
            return_value=False,
        ):
            service.worker_cycle(self.command)
        self.command.stderr.write.assert_called_once()

    def test_device_failure_prevents_daily_completion(self):
        worker_client = Mock()
        worker_client.send_device_status.side_effect = OccSyncError("device failed")
        service = OccSyncService(
            heartbeat_client=Mock(),
            worker_client=worker_client,
        )
        with patch(
            "apps.station_api.management.commands.run_occ_sync_service.daily_sync_due",
            return_value=True,
        ):
            service.worker_cycle(self.command)

        worker_client.send_daily_sync.assert_not_called()
        self.assertIsNone(OccSyncState.load().last_daily_sync_at)

    def test_daily_failure_remains_due(self):
        worker_client = Mock()
        worker_client.send_daily_sync.side_effect = OccSyncError("daily failed")
        service = OccSyncService(
            heartbeat_client=Mock(),
            worker_client=worker_client,
        )
        with patch(
            "apps.station_api.management.commands.run_occ_sync_service.daily_sync_due",
            return_value=True,
        ):
            service.worker_cycle(self.command)

        worker_client.send_device_status.assert_called_once()
        self.assertIsNone(OccSyncState.load().last_daily_sync_at)

    def test_full_daily_success_marks_completion(self):
        worker_client = Mock()
        service = OccSyncService(
            heartbeat_client=Mock(),
            worker_client=worker_client,
        )
        with patch(
            "apps.station_api.management.commands.run_occ_sync_service.daily_sync_due",
            return_value=True,
        ):
            service.worker_cycle(self.command)

        worker_client.send_device_status.assert_called_once()
        worker_client.send_daily_sync.assert_called_once()
        self.assertIsNotNone(OccSyncState.load().last_daily_sync_at)

    def test_start_script_uses_persistent_root_without_credentials(self):
        content = (settings.BASE_DIR / "service" / "start_occ_sync.cmd").read_text(
            encoding="utf-8"
        )
        self.assertIn("KRTC_PERSISTENT_ROOT", content)
        self.assertNotIn("KRTC_RUNTIME_ROOT", content)
        self.assertNotIn("KRTC_OCC_API_TOKEN", content)
