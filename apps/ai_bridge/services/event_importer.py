from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from django.db import IntegrityError, transaction

from apps.ai_bridge.models import InferenceHost
from apps.ai_bridge.services.event_mapper import (
    MappingResult,
    map_inference_event,
)
from apps.ai_bridge.services.inference_client import InferenceClient
from apps.events.models import Event
from apps.notifications.models import BroadcastLog, BroadcastRule


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
    broadcast_logs_created: int = 0
    broadcast_logs_skipped: int = 0


class EventImporter:
    """
    將指定正式 AI 推論主機事件匯入 Django。

    負責：
    - 依 InferenceHost 執行事件 Mapping
    - 依 InferenceCameraMapping 對應 Django Camera
    - 使用 source_host + source_event_id 去重
    - 建立 Event
    - 比對 BroadcastRule
    - 建立 pending BroadcastLog

    不負責：
    - Speaker 實際播放
    - PJSIP
    - MicroSIP
    - 修改 Broadcast playback mode
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

        return self._import_mapped_event(mapping)

    @transaction.atomic
    def _import_mapped_event(
        self,
        mapping: MappingResult,
    ) -> ImportItemResult:
        if mapping.source_event_id is None:
            return ImportItemResult(
                status="skipped",
                reason="missing_source_event_id",
                source_event_id=None,
            )

        existing_event = Event.objects.filter(
            source_host=self.source_host,
            source_event_id=mapping.source_event_id,
        ).first()

        if existing_event is not None:
            return ImportItemResult(
                status="duplicate",
                reason="event_already_imported",
                source_event_id=mapping.source_event_id,
                event_id=existing_event.pk,
            )

        if mapping.mapped_camera_id is None:
            return ImportItemResult(
                status="skipped",
                reason="mapped_camera_not_found",
                source_event_id=mapping.source_event_id,
            )

        description = self._build_description(mapping)

        try:
            event = Event.objects.create(
                camera_id=mapping.mapped_camera_id,
                ai_model=None,
                event_type=mapping.mapped_event_type or "other",
                confidence=mapping.confidence or 0.0,
                status="new",
                source_host=self.source_host,
                source_event_id=mapping.source_event_id,
                source_payload=mapping.source_payload,
                snapshot_url=mapping.snapshot_url or "",
                severity=mapping.severity or "",
                description=description,
                detected_at=mapping.detected_at,
            )

        except IntegrityError:
            existing_event = Event.objects.filter(
                source_host=self.source_host,
                source_event_id=mapping.source_event_id,
            ).first()

            if existing_event is not None:
                return ImportItemResult(
                    status="duplicate",
                    reason="event_already_imported",
                    source_event_id=mapping.source_event_id,
                    event_id=existing_event.pk,
                )

            raise

        created_count, skipped_count = self._create_broadcast_logs(
            event=event,
            mapping=mapping,
        )

        return ImportItemResult(
            status="imported",
            reason="event_created",
            source_event_id=mapping.source_event_id,
            event_id=event.pk,
            broadcast_logs_created=created_count,
            broadcast_logs_skipped=skipped_count,
        )

    def _create_broadcast_logs(
        self,
        *,
        event: Event,
        mapping: MappingResult,
    ) -> tuple[int, int]:
        global_rules = BroadcastRule.objects.filter(
            event_type=event.event_type,
            is_active=True,
            auto_broadcast=True,
            camera__isnull=True,
        )

        camera_rules = BroadcastRule.objects.filter(
            event_type=event.event_type,
            is_active=True,
            auto_broadcast=True,
            camera=event.camera,
        )

        rules = (
            (global_rules | camera_rules)
            .select_related(
                "speaker",
                "audio_file",
                "camera",
            )
            .distinct()
            .order_by(
                "priority",
                "rule_code",
            )
        )

        created_count = 0
        skipped_count = 0

        for rule in rules:
            if not rule.speaker_id or not rule.audio_file_id:
                skipped_count += 1
                continue

            active_log_exists = BroadcastLog.objects.filter(
                speaker=rule.speaker,
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
                "camera_code": event.camera.camera_code,
                "rule_code": rule.rule_code,
                "speaker_code": rule.speaker.speaker_code,
                "audio_code": rule.audio_file.audio_code,
                "playback_mode": "simulation",
            }

            try:
                BroadcastLog.objects.create(
                    event=event,
                    rule=rule,
                    speaker=rule.speaker,
                    audio_file=rule.audio_file,
                    status=BroadcastLog.STATUS_PENDING,
                    request_payload=request_payload,
                    response_payload=None,
                    message=(
                        "正式 AI 推論主機事件匯入後建立的"
                        "模擬廣播工作。"
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

        if mapping.severity:
            parts.append(f"severity={mapping.severity}")

        return " | ".join(parts)