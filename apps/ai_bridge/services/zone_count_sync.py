from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from django.utils import timezone
from django.utils.dateparse import parse_datetime

from apps.ai_bridge.models import InferenceCameraMapping, InferenceHost
from apps.ai_bridge.services.inference_client import InferenceClient
from apps.events.models import ZoneCountState


@dataclass
class ZoneCountSyncResult:
    received: int = 0
    upserted: int = 0
    removed: int = 0
    skipped: int = 0


def _non_negative_int(value: Any, *, allow_none=False):
    if value is None and allow_none:
        return None
    if isinstance(value, bool):
        raise ValueError("boolean is not a valid count")
    number = int(value)
    if number < 0:
        raise ValueError("value must be >= 0")
    return number


def _parse_source_time(value):
    if not value:
        return None
    parsed = parse_datetime(str(value))
    if parsed is None:
        return None
    if timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed, timezone.get_current_timezone())
    return parsed


def sync_zone_counts_for_host(host: InferenceHost) -> ZoneCountSyncResult:
    """Mirror one inference host's current /zone_counts state into PAO."""
    client = InferenceClient(base_url=host.normalized_base_url, timeout=host.timeout_seconds)
    payload = client.get_zone_counts()
    items = payload.get("items", [])
    result = ZoneCountSyncResult(received=len(items))

    mappings = {
        mapping.source_camera_id: mapping.camera
        for mapping in InferenceCameraMapping.objects.select_related("camera").filter(
            inference_host=host
        )
    }
    seen_keys = set()
    now = timezone.now()

    for raw in items:
        if not isinstance(raw, dict):
            result.skipped += 1
            continue

        source_camera_id = str(raw.get("camera_id") or "").strip()
        roi_id = str(raw.get("roi_id") or "").strip()
        if not source_camera_id or not roi_id:
            result.skipped += 1
            continue

        try:
            count = _non_negative_int(raw.get("count", 0))
            threshold = _non_negative_int(raw.get("threshold"), allow_none=True)
        except (TypeError, ValueError):
            result.skipped += 1
            continue

        key = (source_camera_id, roi_id)
        seen_keys.add(key)
        ZoneCountState.objects.update_or_create(
            inference_host=host,
            source_camera_id=source_camera_id,
            roi_id=roi_id,
            defaults={
                "camera": mappings.get(source_camera_id),
                "station": str(raw.get("station") or "").strip(),
                "count": count,
                "threshold": threshold,
                "source_updated_at": _parse_source_time(raw.get("updated_at")),
                "received_at": now,
            },
        )
        result.upserted += 1

    # /zone_counts is a latest-state endpoint. After a successful complete fetch,
    # remove zones that are no longer present in that host's current response.
    existing = ZoneCountState.objects.filter(inference_host=host)
    stale_ids = [
        row.id for row in existing.only("id", "source_camera_id", "roi_id")
        if (row.source_camera_id, row.roi_id) not in seen_keys
    ]
    if stale_ids:
        result.removed, _ = ZoneCountState.objects.filter(id__in=stale_ids).delete()

    return result
