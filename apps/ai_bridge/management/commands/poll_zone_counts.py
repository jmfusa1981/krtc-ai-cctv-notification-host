from __future__ import annotations

import time

from django.core.management.base import BaseCommand, CommandError
from django.db import close_old_connections

from apps.ai_bridge.models import InferenceHost
from apps.ai_bridge.services.inference_client import InferenceClientError
from apps.ai_bridge.services.zone_count_sync import sync_zone_counts_for_host


class Command(BaseCommand):
    help = "Poll /api/notify/zone_counts and mirror current zone people counts into PAO."

    def add_arguments(self, parser):
        parser.add_argument("--interval", type=float, default=15.0)
        parser.add_argument("--host-code", action="append", dest="host_codes", default=None)
        parser.add_argument("--once", action="store_true")

    def handle(self, *args, **options):
        interval = float(options["interval"])
        if interval <= 0:
            raise CommandError("--interval must be greater than 0")

        while True:
            close_old_connections()
            qs = InferenceHost.objects.filter(is_active=True).order_by("host_code")
            if options["host_codes"]:
                qs = qs.filter(host_code__in=options["host_codes"])

            for host in qs:
                try:
                    result = sync_zone_counts_for_host(host)
                    self.stdout.write(
                        f"[{host.host_code}] zone_counts received={result.received} "
                        f"upserted={result.upserted} removed={result.removed} skipped={result.skipped}"
                    )
                except InferenceClientError as exc:
                    self.stderr.write(f"[{host.host_code}] zone_counts unavailable: {exc}")
                except Exception as exc:
                    self.stderr.write(f"[{host.host_code}] zone_counts sync error: {type(exc).__name__}: {exc}")

            close_old_connections()
            if options["once"]:
                return
            time.sleep(interval)
