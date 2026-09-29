from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from django.conf import settings
from django.db import IntegrityError, models, transaction
from django.utils import timezone

from apps.ai_bridge.models import InferenceHost
from apps.ai_bridge.services.event_mapper import (
    MappingResult,
    map_inference_event,
)
from apps.ai_bridge.services.inference_client import InferenceClient
from apps.events.models import Event
from apps.events.services.event_identity import build_event_identity
from apps.events.services.snapshot_localizer import (
    event_has_local_snapshot,
    schedule_event_snapshot_download,
)
from apps.notifications.models import BroadcastLog, BroadcastRule
from apps.notifications.services import (
    clear_stale_auto_broadcast_locks,
    process_broadcast_logs_for_event_async,
)


@dataclass
class ImportSummary:
    fetched: int = 0
    imported: int = 0
    duplicate: int = 0
    skipped: int = 0
    broadcast_logs_created: int = 0
    broadcast_logs_skipped: int = 0
    errors: int = 0


@dataclass
class ImportItemResult:
    status: str
    reason: str
    source_event_id: str | None
    event_id: int | None = None
    external_event_id: str | None = None
    broadcast_logs_created: int = 0
    broadcast_logs_skipped: int = 0


class EventImporter:
    """
    將指定正式 AI 推論主機事件匯入 Django。

    負責：
    - 依 InferenceHost 執行事件 Mapping
    - 依 InferenceCameraMapping 對應 Django Camera
    - 使用 inference_host_code + source_event_id + detected_at 去重，並以 event_id 作第二唯一鍵
    - 建立 Event
    - 比對 BroadcastRule
    - 建立 pending BroadcastLog

    匯入完成後會建立 pending BroadcastLog，並可立即交給
    notifications playback service 非同步處理。
    """

    def __init__(
        self,
        *,
        client: InferenceClient,
        inference_host: InferenceHost,
    ) -> None:
        self.client = client
        self.inference_host = inference_host
        self.source_host = inference_host.normalized_base_url

    def import_payload(
        self,
        payload: dict[str, Any],
        *,
        ingestion_mode: str = "websocket",
        allow_broadcast: bool = True,
    ) -> ImportItemResult:
        mapping = map_inference_event(
            payload,
            client=self.client,
            inference_host=self.inference_host,
        )

        if not mapping.accepted:
            return ImportItemResult(
                status="skipped",
                reason=mapping.reason,
                source_event_id=mapping.source_event_id,
            )

        return self._import_mapped_event(mapping, ingestion_mode=ingestion_mode, allow_broadcast=allow_broadcast)

    @transaction.atomic
    def _import_mapped_event(
        self,
        mapping: MappingResult,
        *,
        ingestion_mode: str,
        allow_broadcast: bool,
    ) -> ImportItemResult:
        if mapping.source_event_id is None:
            return ImportItemResult(
                status="skipped",
                reason="missing_source_event_id",
                source_event_id=None,
            )

        external_event_id = build_event_identity(
            self.inference_host.host_code,
            mapping.source_event_id,
            mapping.detected_at,
        )
        identity_filter = {
            "inference_host_code": self.inference_host.host_code,
            "station_code": mapping.station_code,
            "source_event_id": mapping.source_event_id,
            "detected_at": mapping.detected_at,
        }
        existing_event = (
            Event.objects.filter(**identity_filter).first()
            or Event.objects.filter(event_id=external_event_id).first()
        )

        if existing_event is not None:
            self._repair_existing_event_mapping(existing_event, mapping)
            schedule_event_snapshot_download(existing_event.pk)
            created_count, skipped_count = self._create_and_process_broadcasts(
                event=existing_event,
                mapping=mapping,
                allow_broadcast=allow_broadcast,
            )
            return ImportItemResult(
                status="duplicate",
                reason="event_already_imported",
                source_event_id=mapping.source_event_id,
                event_id=existing_event.pk,
                external_event_id=existing_event.event_id,
                broadcast_logs_created=created_count,
                broadcast_logs_skipped=skipped_count,
            )

        description = self._build_description(mapping)

        try:
            event = Event.objects.create(
                camera_id=mapping.mapped_camera_id,
                ai_model=None,
                event_type=mapping.mapped_event_type or "other",
                confidence=0.0,
                status="new",
                source_host=self.source_host,
                source_event_id=mapping.source_event_id,
                event_id=external_event_id,
                message_id="",
                station_code=mapping.station_code,
                inference_host_code=self.inference_host.host_code,
                camera_code=mapping.source_camera_id or "",
                event_code=mapping.source_event_code or "",
                source_payload=mapping.source_payload,
                snapshot_url=mapping.snapshot_url or "",
                video_url="",
                severity="",
                mapping_status=mapping.mapping_status,
                ack_status="accepted",
                description=description,
                detected_at=mapping.detected_at,
                external_station_name=mapping.external_station_name,
                roi_id=mapping.roi_id,
                bbox=mapping.bbox,
                ingestion_mode=ingestion_mode,
            )

        except IntegrityError:
            existing_event = (
                Event.objects.filter(**identity_filter).first()
                or Event.objects.filter(event_id=external_event_id).first()
            )

            if existing_event is not None:
                self._repair_existing_event_mapping(existing_event, mapping)
                created_count, skipped_count = self._create_and_process_broadcasts(
                    event=existing_event,
                    mapping=mapping,
                    allow_broadcast=allow_broadcast,
                )
                return ImportItemResult(
                    status="duplicate",
                    reason="event_already_imported",
                    source_event_id=mapping.source_event_id,
                    event_id=existing_event.pk,
                    external_event_id=existing_event.event_id,
                    broadcast_logs_created=created_count,
                    broadcast_logs_skipped=skipped_count,
                )

            raise

        schedule_event_snapshot_download(event.pk)

        created_count, skipped_count = self._create_and_process_broadcasts(
            event=event,
            mapping=mapping,
            allow_broadcast=allow_broadcast,
        )

        return ImportItemResult(
            status="imported",
            reason="event_created",
            source_event_id=mapping.source_event_id,
            event_id=event.pk,
            external_event_id=event.event_id,
            broadcast_logs_created=created_count,
            broadcast_logs_skipped=skipped_count,
        )


    @staticmethod
    def _repair_existing_event_mapping(event: Event, mapping: MappingResult) -> None:
        """Repair a previously imported unmapped event when mapping becomes available."""
        update_fields: list[str] = []

        if event.camera_id is None and mapping.mapped_camera_id is not None:
            event.camera_id = mapping.mapped_camera_id
            update_fields.append("camera")

        if mapping.mapping_status == "resolved" and event.mapping_status != "resolved":
            event.mapping_status = "resolved"
            update_fields.append("mapping_status")

        if not event.camera_code and mapping.source_camera_id:
            event.camera_code = mapping.source_camera_id
            update_fields.append("camera_code")

        if mapping.snapshot_url and event.snapshot_url != mapping.snapshot_url:
            event.snapshot_url = mapping.snapshot_url
            update_fields.append("snapshot_url")

        if mapping.source_payload and event.source_payload != mapping.source_payload:
            event.source_payload = mapping.source_payload
            update_fields.append("source_payload")

        if mapping.bbox is not None and event.bbox != mapping.bbox:
            event.bbox = mapping.bbox
            update_fields.append("bbox")

        if update_fields:
            event.save(update_fields=update_fields + ["updated_at"])

    def _create_and_process_broadcasts(
        self,
        *,
        event: Event,
        mapping: MappingResult,
        allow_broadcast: bool,
    ) -> tuple[int, int]:
        if event.snapshot_url and not event_has_local_snapshot(event):
            schedule_event_snapshot_download(event.pk)

        if not allow_broadcast:
            return 0, 1

        # Only active events may create automatic broadcast work.
        # The inference poller can fetch the same historical event repeatedly;
        # once an operator closes/dismisses it locally, it must never be
        # re-queued for speaker playback during a later poll or server restart.
        if event.status not in {"new", "processing", "confirmed"}:
            return 0, 1

        if event.event_type in {"fire_detected", "smoke_detected"}:
            return 0, 1

        created_count, skipped_count = self._create_broadcast_logs(
            event=event,
            mapping=mapping,
        )
        if created_count and getattr(settings, "AUTO_BROADCAST_PROCESS_ON_IMPORT", True):
            transaction.on_commit(
                lambda event_id=event.pk: process_broadcast_logs_for_event_async(event_id)
            )
        return created_count, skipped_count

    def reconcile_existing_event(
        self,
        event: Event,
        *,
        allow_broadcast: bool = True,
    ) -> ImportItemResult:
        """Apply current BroadcastRules to an event that is already stored.

        This is used for operator-created rules and recovery paths: if an event
        was imported before a rule existed, or a previous listener version
        skipped automatic broadcast creation, the current rules can be applied
        once without duplicating logs already present for the same
        event/rule/speaker.
        """

        mapping = MappingResult(
            accepted=True,
            reason="reconcile_existing_event",
            source_event_id=event.source_event_id,
            source_camera_id=event.camera_code or None,
            source_event_code=event.event_code or None,
            mapped_camera_id=event.camera_id,
            mapped_camera_code=event.camera.camera_code if event.camera else None,
            mapped_event_type=event.event_type,
            detected_at=event.detected_at,
            snapshot_url=event.snapshot_url or None,
            station_code=event.station_code,
            external_station_name=event.external_station_name,
            mapping_status=event.mapping_status,
            roi_id=event.roi_id,
            bbox=event.bbox,
            source_payload=dict(event.source_payload or {}),
        )
        created_count, skipped_count = self._create_and_process_broadcasts(
            event=event,
            mapping=mapping,
            allow_broadcast=allow_broadcast,
        )
        return ImportItemResult(
            status="reconciled",
            reason="existing_event_reconciled",
            source_event_id=event.source_event_id,
            event_id=event.pk,
            external_event_id=event.event_id,
            broadcast_logs_created=created_count,
            broadcast_logs_skipped=skipped_count,
        )

    def _create_broadcast_logs(
        self,
        *,
        event: Event,
        mapping: MappingResult,
    ) -> tuple[int, int]:
        rules = matching_auto_broadcast_rules_for_event(event)

        if not rules:
            return 0, 1

        if event.camera_id is None and not any(rule.camera_id is None for rule in rules):
            return 0, 1

        if event.mapping_status != "resolved" and not any(rule.camera_id is None for rule in rules):
            return 0, 1

        rules = sorted(
            rules,
            key=lambda rule: (
                rule.priority,
                0 if event.camera_id and rule.camera_id == event.camera_id else 1,
                rule.rule_code,
            ),
        )

        created_count = 0
        skipped_count = 0

        for rule in rules:
            speakers = target_speakers_for_rule(rule)
            if not speakers or not rule.audio_file_id:
                skipped_count += 1
                continue

            for speaker in speakers:
                event_rule_log_exists = BroadcastLog.objects.filter(
                    event=event,
                    rule=rule,
                    speaker=speaker,
                ).exists()

                if event_rule_log_exists:
                    skipped_count += 1
                    continue

                if recent_auto_broadcast_exists_for_rule(rule, speaker=speaker):
                    skipped_count += 1
                    continue

                clear_stale_auto_broadcast_locks(
                    speakers=[speaker],
                    reason="auto_recovery_before_next_event_broadcast",
                )

                active_log_exists = BroadcastLog.objects.filter(
                    speaker=speaker,
                    status__in=[
                        BroadcastLog.STATUS_PENDING,
                        BroadcastLog.STATUS_PLAYING,
                    ],
                ).exists()

                if active_log_exists:
                    skipped_count += 1
                    continue

                request_payload = {
                    "source": "formal_inference_host",
                    "inference_host_code": (
                        self.inference_host.host_code
                    ),
                    "source_host": self.source_host,
                    "source_event_id": mapping.source_event_id,
                    "event_id": event.pk,
                    "event_type": event.event_type,
                    "camera_code": (
                        event.camera.camera_code
                        if event.camera
                        else (mapping.mapped_camera_code or mapping.source_camera_id or "")
                    ),
                    "rule_code": rule.rule_code,
                    "speaker_code": speaker.speaker_code,
                    "audio_code": rule.audio_file.audio_code,
                    "cooldown_scope": "rule_speaker_audio_source",
                    "target_speaker_count": len(speakers),
                    "auto_process_on_import": getattr(settings, "AUTO_BROADCAST_PROCESS_ON_IMPORT", True),
                    "cooldown_seconds": get_auto_broadcast_cooldown_seconds(),
                }

                try:
                    BroadcastLog.objects.create(
                        event=event,
                        rule=rule,
                        speaker=speaker,
                        audio_file=rule.audio_file,
                        status=BroadcastLog.STATUS_PENDING,
                        request_payload=request_payload,
                        response_payload=None,
                        message=(
                            "正式 AI 推論主機事件匯入後建立的"
                            "自動廣播工作。"
                        ),
                    )
                    created_count += 1

                except IntegrityError:
                    skipped_count += 1

        return created_count, skipped_count

    def _build_description(
        self,
        mapping: MappingResult,
    ) -> str:
        parts = [
            "Imported from formal AI inference host.",
            f"inference_host={self.inference_host.host_code}",
            f"source_event_id={mapping.source_event_id}",
            f"event_code={mapping.source_event_code}",
            f"source_camera_id={mapping.source_camera_id}",
        ]

        roi_id = mapping.source_payload.get("roi_id")

        if roi_id:
            parts.append(f"roi_id={roi_id}")

        return " | ".join(parts)


def matching_auto_broadcast_rules_for_event(event: Event):
    """Return active automatic rules that apply to an imported event.

    A blank rule camera means station-wide/global for that event type.  Global
    rules should still work when an external event could not be mapped to a
    local Camera, because the operator explicitly chose a non-camera-specific
    rule.
    """

    queryset = (
        BroadcastRule.objects
        .select_related("speaker", "audio_file", "camera")
        .prefetch_related("speakers")
        .filter(
            event_type=event.event_type,
            is_active=True,
            auto_broadcast=True,
            audio_file__is_active=True,
        )
        .filter(
            models.Q(speakers__is_active=True) | models.Q(speaker__is_active=True)
        )
    )

    if event.camera_id is None:
        queryset = queryset.filter(camera__isnull=True)
    else:
        queryset = queryset.filter(
            models.Q(camera__isnull=True) | models.Q(camera=event.camera)
        )

    return list(queryset.distinct().order_by("priority", "rule_code"))


def target_speakers_for_rule(rule: BroadcastRule):
    if hasattr(rule, "target_speakers_queryset"):
        return list(rule.target_speakers_queryset(active_only=True))
    if rule.speaker_id and rule.speaker and rule.speaker.is_active:
        return [rule.speaker]
    return []


def get_auto_broadcast_cooldown_seconds() -> int:
    value = getattr(settings, "AUTO_BROADCAST_COOLDOWN_SECONDS", 15)
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 15


def recent_auto_broadcast_exists_for_rule(rule: BroadcastRule, *, speaker) -> bool:
    """Avoid repeatedly playing the same automatic rule for event bursts.

    The cooldown scope is intentionally rule-based: another BroadcastRule can
    still create its own BroadcastLog, while the speaker workflow lock prevents
    overlapping playback on the same physical speaker.
    """

    cooldown_seconds = get_auto_broadcast_cooldown_seconds()
    if cooldown_seconds <= 0:
        return False

    cutoff = timezone.now() - timedelta(seconds=cooldown_seconds)
    return BroadcastLog.objects.filter(
        rule=rule,
        speaker=speaker,
        audio_file=rule.audio_file,
        request_payload__source="formal_inference_host",
        created_at__gte=cutoff,
    ).exists()
