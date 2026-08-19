from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
import json

from apps.station_api.occ_sync import OccSyncClient, OccSyncError


class Command(BaseCommand):
    help = "Send one PAO synchronization cycle to OCC."

    def add_arguments(self, parser):
        parser.add_argument("--kind", choices=["heartbeat", "events", "devices", "daily", "all"], default="all")
        parser.add_argument("--force", action="store_true", help="Run even when KRTC_OCC_SYNC_ENABLED is false.")
        parser.add_argument(
            "--forced-host-status",
            choices=["online", "degraded", "offline"],
            default=None,
            help="Diagnostic override for OCC online/degraded/offline status testing.",
        )

    def handle(self, *args, **options):
        if not settings.KRTC_OCC_SYNC_ENABLED and not options["force"]:
            raise CommandError("OCC sync is disabled. Set KRTC_OCC_SYNC_ENABLED=True or use --force.")
        if not settings.KRTC_OCC_API_TOKEN:
            raise CommandError("KRTC_OCC_API_TOKEN is required.")
        client = OccSyncClient()
        actions = {
            "heartbeat": lambda: client.send_heartbeat(options["forced_host_status"]),
            "events": client.send_pending_events,
            "devices": client.send_device_status,
            "daily": client.send_daily_sync,
        }
        selected = actions if options["kind"] == "all" else {options["kind"]: actions[options["kind"]]}
        try:
            for name, action in selected.items():
                result = action()
                self.stdout.write(self.style.SUCCESS(f"{name}:"))
                self.stdout.write(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        except OccSyncError as exc:
            raise CommandError(f"OCC synchronization failed: {exc}") from exc
