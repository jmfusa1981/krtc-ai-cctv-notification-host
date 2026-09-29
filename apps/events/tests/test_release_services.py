import tempfile
from pathlib import Path
from unittest import mock

from django.apps import apps
from django.conf import settings
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, override_settings

from apps.ai_bridge.apps import AiBridgeConfig
from apps.events.services.recording_service_lock import (
    RecordingServiceAlreadyRunning,
    RecordingServiceProcessLock,
)


class RecordingServiceReleaseTests(SimpleTestCase):
    def test_singleton_rejects_second_owner_and_releases_cleanly(self):
        with tempfile.TemporaryDirectory() as directory:
            lock_path = Path(directory) / "recording.lock"
            with RecordingServiceProcessLock(lock_path):
                with self.assertRaises(RecordingServiceAlreadyRunning):
                    RecordingServiceProcessLock(lock_path).acquire()

            with RecordingServiceProcessLock(lock_path):
                self.assertTrue(lock_path.exists())

    def test_duplicate_command_returns_nonzero_command_error(self):
        with tempfile.TemporaryDirectory() as directory:
            lock_path = Path(directory) / "recording.lock"
            with RecordingServiceProcessLock(lock_path), override_settings(
                KRTC_EVENT_RECORDING_LOCK_PATH=lock_path
            ), mock.patch("signal.signal"):
                with self.assertRaises(CommandError):
                    call_command("run_event_recording_service", verbosity=0)

    @override_settings(
        INFERENCE_POLL_AUTOSTART=True,
        ZONE_COUNT_POLL_AUTOSTART=True,
        INFERENCE_WS_AUTOSTART=True,
    )
    @mock.patch("apps.ai_bridge.background_websocket.start_inference_websocket_listener")
    @mock.patch("apps.ai_bridge.background_zone_counts.start_zone_count_polling")
    @mock.patch("apps.ai_bridge.background_polling.start_inference_polling")
    def test_recording_command_does_not_start_inference_workers(
        self,
        start_polling,
        start_zone_count,
        start_websocket,
    ):
        config = AiBridgeConfig(
            "apps.ai_bridge",
            apps.get_app_config("ai_bridge").module,
        )
        with mock.patch("sys.argv", ["manage.py", "run_event_recording_service"]):
            config.ready()

        start_polling.assert_not_called()
        start_zone_count.assert_not_called()
        start_websocket.assert_not_called()

    def test_service_files_use_frozen_runtime_without_credentials(self):
        service_dir = Path(settings.BASE_DIR) / "service"
        web_script = (service_dir / "start_notification_host.cmd").read_text(
            encoding="utf-8"
        )
        recording_script = (service_dir / "start_event_recording.cmd").read_text(
            encoding="utf-8"
        )
        web_xml = (service_dir / "KRTCNotificationHost.xml").read_text(
            encoding="utf-8"
        )
        recording_xml = (service_dir / "KRTCEventRecordingService.xml").read_text(
            encoding="utf-8"
        )

        self.assertIn("--listen=0.0.0.0:8000 --threads=8", web_script)
        self.assertIn("config.settings_production", web_script)
        self.assertIn("KRTC_PERSISTENT_ROOT", web_script)
        self.assertNotIn("runserver", web_script)
        self.assertIn("run_event_recording_service", recording_script)
        self.assertIn("config.settings_production", recording_script)
        self.assertIn("KRTC_PERSISTENT_ROOT", recording_script)
        self.assertNotIn("PASSWORD", recording_script.upper())
        self.assertIn("<id>KRTCNotificationHost</id>", web_xml)
        self.assertIn("<startmode>Automatic</startmode>", web_xml)
        self.assertIn("<id>KRTCEventRecordingService</id>", recording_xml)
        self.assertIn("<startmode>Automatic</startmode>", recording_xml)

    def test_production_template_disables_fixed_password_bootstrap(self):
        project_root = Path(settings.BASE_DIR)
        template = (project_root / "config" / "production.env.example").read_text(
            encoding="utf-8"
        )
        production_settings = (project_root / "config" / "settings_production.py").read_text(
            encoding="utf-8"
        )

        self.assertIn("KRTC_DEFAULT_ADMIN_ENABLED=False", template)
        self.assertIn("KRTC_DEFAULT_ADMIN_PASSWORD=", template)
        self.assertIn("KRTC_DEFAULT_SUPERUSER_ENABLED=False", template)
        self.assertIn("KRTC_DEFAULT_SUPERUSER_PASSWORD=", template)
        self.assertNotIn("KrtcAdmin@2026", template)
        self.assertNotIn("ntut1234", template)
        self.assertIn('os.getenv("KRTC_DEFAULT_ADMIN_ENABLED", "False")', production_settings)
        self.assertIn(
            'os.getenv("KRTC_DEFAULT_SUPERUSER_ENABLED", "False")',
            production_settings,
        )
