from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from django.utils.dateparse import parse_datetime

from apps.ai_bridge.models import (
    InferenceCameraMapping,
    InferenceHost,
)
from apps.ai_bridge.services.inference_client import InferenceClient


EVENT_TYPE_MAPPING = {
    "EVT_FALL": "escalator_fall",
    "EVT_DWELL": "passenger_loitering",
    "EVT_CROWD": "crowd_count_abnormal",
    "EVT_LUGGAGE_ROLL": "luggage_roll",
    "EVT_LUGGAGE_LARGE": "large_luggage_intrusion",
    "EVT_WHEELCHAIR": "wheelchair_detected",
}


UNSUPPORTED_EVENT_CODES = {
    "EVT_FIRE",
    "EVT_SMOKE",
}


class EventMappingError(Exception):
    """正式推論主機事件無法映射。"""


@dataclass(frozen=True)
class MappingResult:
    accepted: bool
    reason: str

    source_event_id: str | None
    source_camera_id: str | None
    source_event_code: str | None

    inference_host_id: int | None
    inference_host_code: str | None
    source_host: str | None

    mapped_camera_id: int | None
    mapped_camera_code: str | None
    mapped_event_type: str | None

    detected_at: datetime | None
    snapshot_url: str | None
    severity: str | None
    confidence: float | None

    source_payload: dict[str, Any]


def map_inference_event(
    payload: dict[str, Any],
    *,
    client: InferenceClient,
    inference_host: InferenceHost,
) -> MappingResult:
    """
    將正式推論主機事件轉換成 Django Event 可使用的資料。

    Camera Mapping 來源：

        InferenceHost + source_camera_id
            -> InferenceCameraMapping
            -> Django Camera

    此函式不建立 Event，也不寫入資料庫。
    """

    source_event_id = _normalize_string(payload.get("id"))
    source_camera_id = _normalize_string(payload.get("camera_id"))
    source_event_code = _normalize_string(payload.get("event_code"))

    source_host = inference_host.normalized_base_url

    if source_event_id is None:
        return _reject(
            payload=payload,
            inference_host=inference_host,
            reason="missing_source_event_id",
            source_event_id=None,
            source_camera_id=source_camera_id,
            source_event_code=source_event_code,
        )

    if source_event_code is None:
        return _reject(
            payload=payload,
            inference_host=inference_host,
            reason="missing_event_code",
            source_event_id=source_event_id,
            source_camera_id=source_camera_id,
            source_event_code=None,
        )

    if source_event_code in UNSUPPORTED_EVENT_CODES:
        return _reject(
            payload=payload,
            inference_host=inference_host,
            reason="unsupported_event_code",
            source_event_id=source_event_id,
            source_camera_id=source_camera_id,
            source_event_code=source_event_code,
        )

    mapped_event_type = EVENT_TYPE_MAPPING.get(source_event_code)

    if mapped_event_type is None:
        return _reject(
            payload=payload,
            inference_host=inference_host,
            reason="unknown_event_code",
            source_event_id=source_event_id,
            source_camera_id=source_camera_id,
            source_event_code=source_event_code,
        )

    if source_camera_id is None:
        return _reject(
            payload=payload,
            inference_host=inference_host,
            reason="missing_camera_id",
            source_event_id=source_event_id,
            source_camera_id=None,
            source_event_code=source_event_code,
        )

    camera_mapping = (
        InferenceCameraMapping.objects
        .select_related(
            "inference_host",
            "camera",
        )
        .filter(
            inference_host=inference_host,
            source_camera_id=source_camera_id,
            is_active=True,
            camera__is_active=True,
        )
        .first()
    )

    if camera_mapping is None:
        return _reject(
            payload=payload,
            inference_host=inference_host,
            reason="camera_mapping_not_found",
            source_event_id=source_event_id,
            source_camera_id=source_camera_id,
            source_event_code=source_event_code,
        )

    detected_at = _parse_created_at(payload.get("created_at"))

    if detected_at is None:
        return _reject(
            payload=payload,
            inference_host=inference_host,
            reason="invalid_created_at",
            source_event_id=source_event_id,
            source_camera_id=source_camera_id,
            source_event_code=source_event_code,
        )

    confidence = _normalize_float(payload.get("confidence"))
    severity = _normalize_string(payload.get("severity"))

    snapshot_url = client.build_snapshot_url(
        _normalize_string(payload.get("snapshot_path"))
    )

    return MappingResult(
        accepted=True,
        reason="accepted",
        source_event_id=source_event_id,
        source_camera_id=source_camera_id,
        source_event_code=source_event_code,
        inference_host_id=inference_host.pk,
        inference_host_code=inference_host.host_code,
        source_host=source_host,
        mapped_camera_id=camera_mapping.camera_id,
        mapped_camera_code=camera_mapping.camera.camera_code,
        mapped_event_type=mapped_event_type,
        detected_at=detected_at,
        snapshot_url=snapshot_url,
        severity=severity,
        confidence=confidence,
        source_payload=payload,
    )


def _reject(
    *,
    payload: dict[str, Any],
    inference_host: InferenceHost,
    reason: str,
    source_event_id: str | None,
    source_camera_id: str | None,
    source_event_code: str | None,
) -> MappingResult:
    return MappingResult(
        accepted=False,
        reason=reason,
        source_event_id=source_event_id,
        source_camera_id=source_camera_id,
        source_event_code=source_event_code,
        inference_host_id=inference_host.pk,
        inference_host_code=inference_host.host_code,
        source_host=inference_host.normalized_base_url,
        mapped_camera_id=None,
        mapped_camera_code=None,
        mapped_event_type=None,
        detected_at=None,
        snapshot_url=None,
        severity=_normalize_string(payload.get("severity")),
        confidence=_normalize_float(payload.get("confidence")),
        source_payload=payload,
    )


def _parse_created_at(value: Any) -> datetime | None:
    normalized = _normalize_string(value)

    if normalized is None:
        return None

    return parse_datetime(normalized)


def _normalize_string(value: Any) -> str | None:
    if value is None:
        return None

    normalized = str(value).strip()

    if not normalized:
        return None

    return normalized


def _normalize_float(value: Any) -> float | None:
    if value is None:
        return None

    try:
        return float(value)
    except (TypeError, ValueError):
        return None