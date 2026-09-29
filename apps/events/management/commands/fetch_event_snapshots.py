from __future__ import annotations

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.events.models import Event
from apps.events.services.snapshot_localizer import (
    download_event_snapshot,
    event_has_local_snapshot,
)


class Command(BaseCommand):
    help = "Download KMetro API v1.5 remote event snapshots into PAO local storage."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=500)
        parser.add_argument("--timeout", type=float, default=3.0)
        parser.add_argument("--max-bytes", type=int, default=12 * 1024 * 1024)
        parser.add_argument("--retry-count", type=int, default=1)
        parser.add_argument("--overwrite", action="store_true")
        parser.add_argument("--event-id", type=int)
        parser.add_argument("--recent-days", type=int, default=60)

    def handle(self, *args, **options):
        limit = max(1, int(options["limit"]))
        timeout = max(1.0, float(options["timeout"]))
        max_bytes = max(1024, int(options["max_bytes"]))
        retry_count = max(0, int(options["retry_count"]))
        overwrite = bool(options["overwrite"])
        recent_days = max(1, int(options["recent_days"]))

        queryset = (
            Event.objects.exclude(snapshot_url="")
            .filter(detected_at__gte=timezone.now() - timedelta(days=recent_days))
            .order_by("-detected_at", "-created_at")
        )
        if options.get("event_id"):
            queryset = queryset.filter(pk=options["event_id"])

        attempted = downloaded = already_local = failed = not_found = timeout_count = 0

        try:
            for event in queryset.iterator(chunk_size=100):
                if attempted >= limit:
                    break
                if not overwrite and event_has_local_snapshot(event):
                    already_local += 1
                    continue

                attempted += 1
                result = download_event_snapshot(
                    event,
                    timeout=timeout,
                    max_bytes=max_bytes,
                    overwrite=overwrite,
                    retry_count=retry_count,
                )

                if result.ok:
                    if result.status == "already_local":
                        already_local += 1
                    else:
                        downloaded += 1
                        self.stdout.write(self.style.SUCCESS(
                            f"[OK] event={event.pk} local={result.local_name}"
                        ))
                    continue

                failed += 1
                if result.status == "not_found":
                    not_found += 1
                if result.status == "timeout":
                    timeout_count += 1
                self.stderr.write(
                    f"[FAILED] event={event.pk} status={result.status} "
                    f"message={result.message} url={result.source_url}"
                )
        except KeyboardInterrupt:
            self.stderr.write(self.style.WARNING("Interrupted by user; completed items remain saved."))

        self.stdout.write(
            self.style.SUCCESS(
                "SUMMARY "
                f"attempted={attempted} downloaded={downloaded} "
                f"already_local={already_local} failed={failed} "
                f"not_found={not_found} timeout={timeout_count}"
            )
        )
