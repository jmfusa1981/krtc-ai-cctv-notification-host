from __future__ import annotations

import hashlib
from datetime import datetime, timezone as datetime_timezone

from django.utils import timezone


def normalize_event_time(value: datetime) -> datetime:
    """Return an aware UTC datetime suitable for event identity comparisons."""
    if timezone.is_naive(value):
        value = timezone.make_aware(value, timezone.get_current_timezone())
    return value.astimezone(datetime_timezone.utc)


def build_event_identity(
    inference_host_code: str,
    source_event_id: str,
    detected_at: datetime,
) -> str:
    """Build a stable external event identity.

    KMetro source IDs can restart after backend/database resets.  Timestamp is
    therefore part of the identity.  The digest keeps Event.event_id within its
    150-character database limit even when source IDs are unusually long.
    """
    host_code = str(inference_host_code or "").strip()
    source_id = str(source_event_id or "").strip()
    normalized_time = normalize_event_time(detected_at)
    timestamp_token = normalized_time.strftime("%Y%m%dT%H%M%S%fZ")
    raw_identity = f"{host_code}|{source_id}|{timestamp_token}"
    digest = hashlib.sha256(raw_identity.encode("utf-8")).hexdigest()[:20]

    readable_source = "".join(
        character if character.isalnum() or character in {"-", "_"} else "_"
        for character in source_id
    )[:72]
    readable_host = "".join(
        character if character.isalnum() or character in {"-", "_"} else "_"
        for character in host_code
    )[:40]
    return f"{readable_host}:{readable_source}:{timestamp_token}:{digest}"[:150]
