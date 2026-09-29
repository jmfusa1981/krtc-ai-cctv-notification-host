from django.core.management.base import BaseCommand

from apps.notifications.scheduler import process_due_broadcast_schedules


class Command(BaseCommand):
    help = "Process currently due broadcast schedules once."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=10)

    def handle(self, *args, **options):
        result = process_due_broadcast_schedules(limit=max(1, options["limit"]))
        self.stdout.write(self.style.SUCCESS(str(result)))
