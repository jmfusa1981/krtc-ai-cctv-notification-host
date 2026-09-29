from io import StringIO

from django.conf import settings
from django.core.management import call_command
from django.test import TestCase

from apps.settings_app.models import StationLocalSettings


class ReleaseVersionSynchronizationTests(TestCase):
    def test_command_synchronizes_existing_database_idempotently(self):
        local_settings = StationLocalSettings.load()
        local_settings.system_version = "V6.6.2"
        local_settings.save(update_fields=["system_version", "updated_at"])

        first_output = StringIO()
        call_command("sync_release_version", stdout=first_output)
        local_settings.refresh_from_db()
        first_updated_at = local_settings.updated_at

        second_output = StringIO()
        call_command("sync_release_version", stdout=second_output)
        local_settings.refresh_from_db()

        self.assertEqual(local_settings.system_version, settings.KRTC_APP_VERSION)
        self.assertEqual(local_settings.updated_at, first_updated_at)
        self.assertIn("already synchronized", second_output.getvalue())
        self.assertEqual(settings.KRTC_APP_VERSION, "PAO Notification Host V6.7.0-RC")
