from django.conf import settings
from django.core.management.base import BaseCommand

from apps.settings_app.models import StationLocalSettings


class Command(BaseCommand):
    help = "Synchronize the persistent station display version with this release."

    def handle(self, *args, **options):
        local_settings = StationLocalSettings.load()
        target_version = settings.KRTC_APP_VERSION
        if local_settings.system_version == target_version:
            self.stdout.write(f"Release version already synchronized: {target_version}")
            return

        local_settings.system_version = target_version
        local_settings.save(update_fields=["system_version", "updated_at"])
        self.stdout.write(self.style.SUCCESS(f"Release version synchronized: {target_version}"))
