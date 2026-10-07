import json
import os
import uuid
from pathlib import Path

from django.conf import settings


def monitor_profile_config_path():
    """回傳集中管理的Monitor profile設定路徑。"""

    return Path(
        getattr(
            settings,
            "KRTC_MONITOR_PROFILE_CONFIG_PATH",
            Path(settings.BASE_DIR) / "config" / "monitor_profiles.json",
        )
    )


def monitor_profile_state_path():
    """回傳bridge supervisor監看的runtime狀態路徑。"""

    return Path(
        getattr(
            settings,
            "KRTC_MONITOR_PROFILE_STATE_PATH",
            Path(settings.BASE_DIR)
            / "runtime"
            / "mediamtx"
            / "monitor_profile.json",
        )
    )


def load_monitor_profile_config():
    """載入並驗證layout對應及輸出尺寸/FPS。"""

    payload = json.loads(
        monitor_profile_config_path().read_text(encoding="utf-8")
    )
    profiles = payload.get("profiles") or {}
    layout_map = payload.get("layout_map") or {}
    if not profiles or not layout_map:
        raise ValueError("monitor_profile_configuration_empty")
    for profile_name, profile in profiles.items():
        width = int(profile.get("width") or 0)
        height = int(profile.get("height") or 0)
        fps = int(profile.get("fps") or 0)
        if (
            not profile_name
            or width <= 0
            or height <= 0
            or fps <= 0
            or width * 9 != height * 16
        ):
            raise ValueError("monitor_profile_configuration_invalid")
    if any(name not in profiles for name in layout_map.values()):
        raise ValueError("monitor_profile_layout_mapping_invalid")
    return payload


def get_active_monitor_profile():
    """讀取目前要求的profile，無有效狀態時使用集中設定預設值。"""

    config = load_monitor_profile_config()
    default_profile = config.get("default_profile", "grid4")
    try:
        payload = json.loads(
            monitor_profile_state_path().read_text(encoding="ascii")
        )
    except (OSError, ValueError, json.JSONDecodeError):
        return default_profile
    profile_name = str(payload.get("profile", ""))
    return profile_name if profile_name in config["profiles"] else default_profile


def request_monitor_profile(profile_name):
    """原子寫入含唯一識別碼的profile請求，支援取代進行中的轉場。"""

    config = load_monitor_profile_config()
    if profile_name not in config["profiles"]:
        raise ValueError("monitor_profile_unknown")
    changed = get_active_monitor_profile() != profile_name

    state_path = monitor_profile_state_path()
    state_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = state_path.with_name(
        f"{state_path.name}.{uuid.uuid4().hex}.tmp"
    )
    temporary_path.write_text(
        json.dumps(
            {
                "profile": profile_name,
                "request_id": str(uuid.uuid4()),
            },
            ensure_ascii=True,
        ),
        encoding="ascii",
    )
    os.replace(temporary_path, state_path)
    return changed
