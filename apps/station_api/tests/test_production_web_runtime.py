from unittest import mock

from django.test import SimpleTestCase, override_settings

from apps.notifications import scheduler_runtime
from apps.station_api import service_watchdog


@override_settings(
    KRTC_PRODUCTION=True,
    BROADCAST_SCHEDULER_AUTOSTART=True,
    PAO_SERVICE_WATCHDOG_ENABLED=True,
)
class ProductionWebRuntimeTests(SimpleTestCase):
    def test_waitress_starts_scheduler_once(self):
        thread = mock.Mock()
        waitress_argv = ["waitress/__main__.py", "config.wsgi:application"]
        with mock.patch("sys.argv", waitress_argv), mock.patch.object(
            scheduler_runtime.threading,
            "Thread",
            return_value=thread,
        ), mock.patch.object(
            scheduler_runtime,
            "_scheduler_started",
            False,
        ), mock.patch.object(
            scheduler_runtime,
            "_scheduler_thread",
            None,
        ):
            self.assertTrue(scheduler_runtime.start_scheduler_for_current_process())
            self.assertFalse(scheduler_runtime.start_scheduler_for_current_process())

        thread.start.assert_called_once_with()

    def test_waitress_starts_watchdog_once(self):
        thread = mock.Mock()
        waitress_argv = ["waitress/__main__.py", "config.wsgi:application"]
        with mock.patch("sys.argv", waitress_argv), mock.patch.object(
            service_watchdog.threading,
            "Thread",
            return_value=thread,
        ), mock.patch.object(
            service_watchdog,
            "_watchdog_started",
            False,
        ), mock.patch.object(
            service_watchdog,
            "_watchdog_thread",
            None,
        ):
            self.assertTrue(service_watchdog.start_service_watchdog_for_current_process())
            self.assertFalse(service_watchdog.start_service_watchdog_for_current_process())

        thread.start.assert_called_once_with()

    def test_management_command_is_not_treated_as_waitress(self):
        with mock.patch("sys.argv", ["manage.py", "run_event_recording_service"]):
            self.assertFalse(scheduler_runtime._is_runserver_worker())
            self.assertFalse(service_watchdog._is_runserver_worker())
