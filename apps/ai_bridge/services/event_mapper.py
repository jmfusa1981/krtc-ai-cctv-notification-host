from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from django.conf import settings
from django.utils.dateparse import parse_datetime

from apps.ai_bridge.models import InferenceCameraMapping, InferenceHost
from apps.cameras.models import Camera

EVENT_TYPE_MAPPING = {
    "EVT_FALL": "escalator_fall",
    "EVT_LUGGAGE_ROLL": "luggage_roll",
    "EVT_LUGGAGE_LARGE": "large_luggage_intrusion",
    "EVT_WHEELCHAIR": "wheelchair_detected",
    "EVT_DWELL": "passenger_loitering",
    "EVT_CROWD": "crowd_count_abnormal",
    "EVT_FIRE": "fire_detected",
    "EVT_SMOKE": "smoke_detected",
}


@dataclass(frozen=True)
class MappingResult:
    accepted: bool
    reason: str
    source_event_id: str | None
    source_camera_id: str | None
    source_event_code: str | None
    mapped_camera_id: int | None
    mapped_camera_code: str | None
    mapped_event_type: str | None
    detected_at: datetime | None
    snapshot_url: str | None
    station_code: str
    external_station_name: str
    mapping_status: str
    roi_id: str | None
    bbox: list | None
    source_payload: dict[str, Any]


def map_inference_event(payload: dict[str, Any], *, client, inference_host: InferenceHost) -> MappingResult:
    def text(name):
        value = payload.get(name)
        return str(value).strip() if value is not None and str(value).strip() else None

    source_id, camera_id, event_code = text("id"), text("camera_id"), text("event_code")
    station_name = text("station") or ""
    timestamp = parse_datetime(text("timestamp") or "")
    bbox = payload.get("bbox")
    base = dict(source_event_id=source_id, source_camera_id=camera_id,
                source_event_code=event_code, station_code=inference_host.station_code,
                external_station_name=station_name, roi_id=text("roi_id"), bbox=bbox,
                source_payload=dict(payload))
    if source_id is None:
        return _reject("missing_id", **base)
    if timestamp is None or timestamp.utcoffset() is None:
        return _reject("invalid_timestamp", **base)
    if camera_id is None:
        return _reject("missing_camera_id", **base)
    mapped_type = EVENT_TYPE_MAPPING.get(event_code or "")
    if mapped_type is None:
        return _reject("unknown_event_code", **base)
    if bbox is not None and (not isinstance(bbox, list) or len(bbox) != 4 or any(not isinstance(v, (int, float)) for v in bbox)):
        return _reject("invalid_bbox", **base)

    station_map = getattr(settings, "KRTC_EXTERNAL_STATION_MAPPING", {})
    station_ok = not station_name or station_map.get(station_name) == inference_host.station_code
    camera_mapping = InferenceCameraMapping.objects.select_related("camera").filter(
        inference_host=inference_host,
        source_camera_id__iexact=camera_id,
        is_active=True,
        camera__is_active=True,
    ).first()

    # KMetro v1.3 emits canonical camera IDs such as CAM-003.  Older PAO
    # databases may still contain legacy aliases (for example
    # cam_escalator_down), so allow a safe fallback to the local Camera
    # camera_code.  This keeps the event linked to the correct camera even
    # before an explicit InferenceCameraMapping row is created.
    mapped_camera = camera_mapping.camera if camera_mapping else Camera.objects.filter(
        camera_code__iexact=camera_id,
        is_active=True,
    ).first()

    resolved = station_ok and mapped_camera is not None
    return MappingResult(True, "accepted", source_id, camera_id, event_code,
                         mapped_camera.pk if mapped_camera else None,
                         mapped_camera.camera_code if mapped_camera else None,
                         mapped_type, timestamp, text("snapshot_url"), inference_host.station_code,
                         station_name, "resolved" if resolved else "unmapped", text("roi_id"), bbox,
                         dict(payload))


def _reject(reason, **values):
    return MappingResult(False, reason, values["source_event_id"], values["source_camera_id"],
                         values["source_event_code"], None, None, None, None, None,
                         values["station_code"], values["external_station_name"], "unmapped",
                         values["roi_id"], values["bbox"], values["source_payload"])
