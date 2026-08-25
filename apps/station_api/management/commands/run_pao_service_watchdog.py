import time

from django.conf import settings
from django.core.management.base import BaseCommand

from apps.station_api.service_watchdog import evaluate_services


class Command(BaseCommand):
    help = "Run the PAO internal service watchdog as a standalone process."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true", help="Evaluate once and exit.")
        parser.add_argument("--interval", type=int, default=None)

    def handle(self, *args, **options):
        interval = max(
            10,
            int(options["interval"] or getattr(settings, "PAO_SERVICE_WATCHDOG_INTERVAL_SECONDS", 30)),
        )

        while True:
            results = evaluate_services()
            for name, result in results.items():
                state = "OK" if result.get("healthy", True) else "FAULT"
                self.stdout.write(f"{name}: {state} - {result.get('description', '')}")

            if options["once"]:
                return
            time.sleep(interval)
