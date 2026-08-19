from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Count, Q

from apps.ai_bridge.models import InferenceHost
from apps.ai_bridge.services.event_importer import (
    EventImporter,
    matching_auto_broadcast_rules_for_event,
)
from apps.ai_bridge.services.inference_client import InferenceClient
from apps.events.models import Event
from apps.notifications.models import BroadcastLog


class Command(BaseCommand):
    help = (
        "Find stored events that match current BroadcastRules but have no "
        "BroadcastLog yet, then optionally create/process those logs."
    )

    def add_arguments(self, parser):
        parser.add_argument("--event-id", type=int, default=None)
        parser.add_argument("--source-event-id", default="")
        parser.add_argument("--limit", type=int, default=20)
        parser.add_argument(
            "--process",
            action="store_true",
            help="Create missing BroadcastLogs and process them immediately.",
        )
        parser.add_argument(
            "--include-unmapped",
            action="store_true",
            help=(
                "Allow global camera-empty rules to apply to unmapped events. "
                "Camera-specific rules still require a mapped camera."
            ),
        )

    def handle(self, *args, **options):
        events = self._get_events(options)
        process = bool(options["process"])
        include_unmapped = bool(options["include_unmapped"])

        self.stdout.write("Auto broadcast reconciliation")
        self.stdout.write(f"Mode: {'process' if process else 'dry-run'}")
        self.stdout.write("")

        total_candidates = 0
        total_created = 0
        total_skipped = 0

        for event in events:
            rules = matching_auto_broadcast_rules_for_event(event)
            if not rules:
                continue

            if event.mapping_status != "resolved" and not include_unmapped:
                continue

            missing_rules = [
                rule
                for rule in rules
                if any(
                    not BroadcastLog.objects.filter(
                        event=event,
                        rule=rule,
                        speaker=speaker,
                    ).exists()
                    for speaker in rule.target_speakers_queryset(active_only=True)
                )
            ]
            if not missing_rules:
                continue

            total_candidates += 1
            self.stdout.write(
                self.style.HTTP_INFO(
                    f"Event #{event.pk} source_event_id={event.source_event_id} "
                    f"type={event.event_type} camera={event.camera_code or '(none)'} "
                    f"missing_rules={len(missing_rules)}"
                )
            )
            for rule in missing_rules:
                speaker_codes = ", ".join(
                    rule.target_speakers_queryset(active_only=True).values_list(
                        "speaker_code",
                        flat=True,
                    )
                ) or "(no active speaker)"
                self.stdout.write(
                    "  "
                    f"{rule.rule_code} -> {speaker_codes} / "
                    f"{rule.audio_file.audio_code}"
                )

            if not process:
                continue

            importer = self._build_importer(event)
            result = importer.reconcile_existing_event(event)
            total_created += result.broadcast_logs_created
            total_skipped += result.broadcast_logs_skipped
            self.stdout.write(
                self.style.SUCCESS(
                    "  processed: "
                    f"broadcast_created={result.broadcast_logs_created}, "
                    f"broadcast_skipped={result.broadcast_logs_skipped}"
                )
            )

        self.stdout.write("")
        self.stdout.write(
            self.style.SUCCESS(
                "Summary: "
                f"candidate_events={total_candidates}, "
                f"broadcast_created={total_created}, "
                f"broadcast_skipped={total_skipped}"
            )
        )

    def _get_events(self, options):
        queryset = (
            Event.objects
            .select_related("camera")
            .annotate(auto_broadcast_log_count=Count(
                "broadcast_logs",
                filter=Q(broadcast_logs__rule__isnull=False),
            ))
            .order_by("-detected_at", "-created_at")
        )

        event_id = options["event_id"]
        source_event_id = str(options["source_event_id"] or "").strip()
        if event_id is not None:
            queryset = queryset.filter(pk=event_id)
        elif source_event_id:
            queryset = queryset.filter(source_event_id=source_event_id)
        else:
            queryset = queryset[: max(1, int(options["limit"]))]

        events = list(queryset)
        if not events:
            raise CommandError("No matching Event rows found.")
        return events

    @staticmethod
    def _build_importer(event):
        host = None
        if event.inference_host_code:
            host = InferenceHost.objects.filter(
                host_code=event.inference_host_code
            ).first()
        if host is None:
            host = InferenceHost.objects.filter(is_active=True).order_by("host_code").first()
        if host is None:
            raise CommandError(
                "No InferenceHost is available for reconciliation."
            )
        client = InferenceClient(
            base_url=host.normalized_base_url,
            timeout=host.timeout_seconds,
        )
        return EventImporter(client=client, inference_host=host)
