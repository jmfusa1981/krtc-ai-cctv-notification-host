from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils.dateparse import parse_datetime

from apps.events.models import Event
from apps.events.services.event_identity import build_event_identity, normalize_event_time
from apps.events.services.snapshot_localizer import event_has_local_snapshot


class Command(BaseCommand):
    help = (
        "Recover events whose source_payload timestamp differs from detected_at "
        "because a reused inference source_event_id overwrote an older PAO event."
    )

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Create recovered Event rows.")
        parser.add_argument("--limit", type=int, default=1000)
        parser.add_argument(
            "--move-local-snapshot",
            action="store_true",
            help="Move the currently attached local snapshot to the recovered event.",
        )

    def handle(self, *args, **options):
        apply_changes = bool(options["apply"])
        limit = max(1, int(options["limit"]))
        move_snapshot = bool(options["move_local_snapshot"])

        candidates = 0
        created = 0
        skipped = 0

        queryset = Event.objects.exclude(source_event_id__isnull=True).order_by("-updated_at")[:limit]
        for event in queryset:
            payload = dict(event.source_payload or {})
            payload_timestamp = parse_datetime(str(payload.get("timestamp") or ""))
            if payload_timestamp is None or event.detected_at is None:
                continue

            if normalize_event_time(payload_timestamp) == normalize_event_time(event.detected_at):
                continue

            candidates += 1
            recovered_event_id = build_event_identity(
                event.inference_host_code,
                event.source_event_id,
                payload_timestamp,
            )

            if Event.objects.filter(event_id=recovered_event_id).exists():
                skipped += 1
                self.stdout.write(
                    f"[SKIP] old_event={event.pk} recovered_event_id already exists"
                )
                continue

            self.stdout.write(
                f"[CANDIDATE] old_event={event.pk} source_event_id={event.source_event_id} "
                f"old_time={event.detected_at.isoformat()} payload_time={payload_timestamp.isoformat()}"
            )
            if not apply_changes:
                continue

            with transaction.atomic():
                recovered = Event.objects.create(
                    camera=event.camera,
                    ai_model=event.ai_model,
                    event_type=event.event_type,
                    confidence=event.confidence,
                    status="new",
                    source_host=event.source_host,
                    source_event_id=event.source_event_id,
                    event_id=recovered_event_id,
                    message_id=event.message_id,
                    station_code=event.station_code,
                    inference_host_code=event.inference_host_code,
                    camera_code=event.camera_code,
                    event_code=event.event_code,
                    video_url=event.video_url,
                    mapping_status=event.mapping_status,
                    ack_status="accepted",
                    received_at=event.updated_at,
                    external_station_name=payload.get("station") or event.external_station_name,
                    roi_id=payload.get("roi_id"),
                    bbox=payload.get("bbox"),
                    ingestion_mode="recovered",
                    source_payload=deepcopy(payload),
                    snapshot_url=str(payload.get("snapshot_url") or event.snapshot_url or ""),
                    severity=event.severity,
                    description=(
                        f"Recovered from reused inference source_event_id. old_event={event.pk}"
                    ),
                    detected_at=payload_timestamp,
                )

                if move_snapshot and event_has_local_snapshot(event):
                    old_name = event.snapshot.name
                    with event.snapshot.storage.open(old_name, "rb") as source_file:
                        content = source_file.read()
                    recovered.snapshot.save(Path(old_name).name, ContentFile(content), save=True)
                    event.snapshot.delete(save=False)
                    event.snapshot = None
                    event.save(update_fields=["snapshot", "updated_at"])

                created += 1
                self.stdout.write(
                    self.style.SUCCESS(
                        f"[CREATED] old_event={event.pk} recovered_event={recovered.pk}"
                    )
                )

        mode = "APPLY" if apply_changes else "DRY-RUN"
        self.stdout.write(
            self.style.SUCCESS(
                f"{mode} complete: candidates={candidates}, created={created}, skipped={skipped}"
            )
        )
