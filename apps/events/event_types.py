"""KRTC AI 事件代碼與事件類型的唯一權威定義。"""

CANONICAL_EVENT_CODE_TO_TYPE = {
    "EVT_FALL": "fall_detected",
    "EVT_FIRE": "fire_detected",
    "EVT_SMOKE": "smoke_detected",
    "EVT_DWELL": "dwell_alert",
    "EVT_CROWD": "crowd_alert",
    "EVT_LUGGAGE_ROLL": "luggage_roll_detected",
    "EVT_LUGGAGE_LARGE": "large_luggage_detected",
    "EVT_WHEELCHAIR": "wheelchair_detected",
}

CANONICAL_EVENT_TYPE_CHOICES = (
    ("fall_detected", "人員跌倒"),
    ("fire_detected", "火光偵測"),
    ("smoke_detected", "煙霧偵測"),
    ("dwell_alert", "旅客滯留"),
    ("crowd_alert", "人潮聚集"),
    ("luggage_roll_detected", "行李箱滾落（電扶梯功能）"),
    ("large_luggage_detected", "大件行李（禁制區功能）"),
    ("wheelchair_detected", "輪椅偵測（禁制區功能）"),
)

LEGACY_EVENT_TYPE_TO_CANONICAL = {
    "escalator_fall": "fall_detected",
    "luggage_roll": "luggage_roll_detected",
    "large_luggage_intrusion": "large_luggage_detected",
    "passenger_loitering": "dwell_alert",
    "crowd_count_abnormal": "crowd_alert",
}

LEGACY_EVENT_TYPE_LABELS = {
    "escalator_fall": "人員跌倒（歷史值）",
    "luggage_roll": "行李箱滾落（歷史值）",
    "large_luggage_intrusion": "大件行李（歷史值）",
    "passenger_loitering": "旅客滯留（歷史值）",
    "crowd_count_abnormal": "人潮聚集（歷史值）",
}

EVENT_TYPE_LABELS = dict(CANONICAL_EVENT_TYPE_CHOICES)
EVENT_TYPE_LABELS.update(LEGACY_EVENT_TYPE_LABELS)
EVENT_TYPE_LABELS["other"] = "其他"


def canonicalize_event_type(event_type: str) -> str:
    """將歷史事件類型轉為 canonical 值，未知值維持原樣。"""

    return LEGACY_EVENT_TYPE_TO_CANONICAL.get(event_type, event_type)


def compatible_event_types(event_type: str) -> tuple[str, ...]:
    """回傳查詢時可相容 canonical 與既有歷史規則的事件類型。"""

    canonical_type = canonicalize_event_type(event_type)
    legacy_types = tuple(
        legacy_type
        for legacy_type, mapped_type in LEGACY_EVENT_TYPE_TO_CANONICAL.items()
        if mapped_type == canonical_type
    )
    return tuple(dict.fromkeys((canonical_type, event_type, *legacy_types)))


def event_type_label(event_type: str) -> str:
    """取得 canonical 或歷史事件類型的繁體中文顯示名稱。"""

    return EVENT_TYPE_LABELS.get(event_type, event_type)
