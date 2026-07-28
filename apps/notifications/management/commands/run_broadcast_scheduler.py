import time

from django.core.management.base import BaseCommand

from apps.notifications.scheduler import process_due_broadcast_schedules


class Command(BaseCommand):
    help = "Run the minimal broadcast schedule worker."

    def add_arguments(self, parser):
        parser.add_argument("--interval", type=int, default=15, help="Polling interval in seconds.")
        parser.add_argument("--limit", type=int, default=10)
        parser.add_argument("--once", action="store_true")

    def handle(self, *args, **options):
        interval = max(5, options["interval"])
        limit = max(1, options["limit"])
        self.stdout.write(f"Broadcast scheduler started. interval={interval}s")
        while True:
            result = process_due_broadcast_schedules(limit=limit)
            if result["due_count"] or result["failed"]:
                self.stdout.write(str(result))
            if options["once"]:
                return
            time.sleep(interval)
