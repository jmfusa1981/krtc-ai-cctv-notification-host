from __future__ import annotations

from typing import Any


EVENT_CODE_TO_SOURCE_EVENT_TYPE = {
    "EVT_FALL": "fall_detected",
    "EVT_FIRE": "fire_detected",
    "EVT_SMOKE": "smoke_detected",
    "EVT_DWELL": "dwell_alert",
    "EVT_CROWD": "crowd_alert",
    "EVT_LUGGAGE_ROLL": "luggage_roll_detected",
    "EVT_LUGGAGE_LARGE": "large_luggage_detected",
    "EVT_WHEELCHAIR": "wheelchair_detected",
}


def normalize_notify_event(
    payload: dict[str, Any],
) -> dict[str, Any]:
    """
    將 /api/notify/events 的精簡事件格式轉換成
    /api/events 的完整事件格式。

    此函式只做格式轉換，不寫入資料庫。
    """

    event_code = payload.get("event_code")

    return {
        "id": payload.get("id"),
        "event_type": (
            EVENT_CODE_TO_SOURCE_EVENT_TYPE.get(event_code)
            if event_code
            else None
        ),
        "event_code": event_code,
        "camera_id": payload.get("camera_id"),
        "roi_id": payload.get("roi_id"),
        "severity": None,
        "confidence": 0.0,
        "snapshot_path": payload.get("snapshot_url"),
        "extra": {
            "station": payload.get("station"),
            "offline_replay": True,
            "source_endpoint": "/api/notify/events",
            "original_notify_payload": payload,
        },
        "created_at": payload.get("timestamp"),
    }


def normalize_notify_event_list(
    payload: dict[str, Any],
) -> list[dict[str, Any]]:
    items = payload.get("items", [])

    if not isinstance(items, list):
        raise ValueError("notify events payload 的 items 必須為 list。")

    normalized_items: list[dict[str, Any]] = []

    for item in items:
        if not isinstance(item, dict):
            raise ValueError("notify events 中每一筆 item 必須為 object。")

        normalized_items.append(
            normalize_notify_event(item)
        )

    return normalized_items