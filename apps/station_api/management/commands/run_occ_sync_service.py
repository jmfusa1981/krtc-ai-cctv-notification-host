import time

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.station_api.occ_sync import OccSyncClient, OccSyncError, daily_sync_due


class Command(BaseCommand):
    help = "Run the dedicated PAO to OCC heartbeat and synchronization service."

    def handle(self, *args, **options):
        if not settings.KRTC_OCC_SYNC_ENABLED:
            raise CommandError("KRTC_OCC_SYNC_ENABLED must be True.")
        if not settings.KRTC_OCC_API_TOKEN:
            raise CommandError("KRTC_OCC_API_TOKEN is required.")
        client = OccSyncClient()
        self.stdout.write(self.style.SUCCESS("OCC sync service started."))
        while True:
            for action in (client.send_heartbeat, client.send_pending_events):
                try:
                    action()
                except OccSyncError as exc:
                    self.stderr.write(str(exc))
            if daily_sync_due():
                for action in (client.send_device_status, client.send_daily_sync):
                    try:
                        action()
                    except OccSyncError as exc:
                        self.stderr.write(str(exc))
            time.sleep(max(settings.KRTC_HEARTBEAT_INTERVAL, 5))
