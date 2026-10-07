import json
import os
import threading
import uuid
from pathlib import Path

from django.conf import settings

from .mediamtx import camera_path_name, phase1_camera_codes


_ack_lock = threading.Lock()


def monitor_transition_state_path():
    """回傳bridge supervisor寫入的profile轉場狀態路徑。"""

    return Path(
        getattr(
            settings,
            "KRTC_MONITOR_TRANSITION_STATE_PATH",
            Path(settings.BASE_DIR)
            / "runtime"
            / "mediamtx"
            / "profile_transition.json",
        )
    )


def monitor_transition_ack_path():
    """回傳瀏覽器完成雙緩衝預載後的確認檔路徑。"""

    return Path(
        getattr(
            settings,
            "KRTC_MONITOR_TRANSITION_ACK_PATH",
            Path(settings.BASE_DIR)
            / "runtime"
            / "mediamtx"
            / "profile_transition_ack.json",
        )
    )


def _default_camera_states():
    return {
        camera_code: {
            "camera_code": camera_code,
            "active_path": camera_path_name(camera_code),
            "next_path": None,
            "transition_state": "idle",
        }
        for camera_code in sorted(phase1_camera_codes())
    }


def load_monitor_transition_state():
    """載入不含來源憑證的A/B path轉場快照，無效內容安全降級為idle。"""

    result = {
        "transition_id": "",
        "active_profile": "",
        "profile_transition_state": "idle",
        "profile_transition_from": "",
        "profile_transition_to": "",
        "profile_transition_started_at": "",
        "profile_transition_camera_count": 0,
        "cameras": _default_camera_states(),
        "last_error": "",
    }
    try:
        payload = json.loads(
            monitor_transition_state_path().read_text(encoding="ascii")
        )
    except (OSError, ValueError, json.JSONDecodeError):
        return result

    transition_state = str(payload.get("ProfileTransitionState", "idle"))
    if transition_state not in {
        "idle",
        "starting",
        "preloading",
        "committing",
        "failed",
        "cancelled",
    }:
        return result

    allowed_codes = phase1_camera_codes()
    cameras = _default_camera_states()
    for item in payload.get("Cameras") or []:
        camera_code = str(item.get("CameraCode", "")).strip().upper()
        active_path = str(item.get("ActivePath", "")).strip().lower()
        next_path = str(item.get("NextPath", "")).strip().lower()
        camera_state = str(item.get("TransitionState", "idle")).strip().lower()
        if camera_code not in allowed_codes:
            continue
        valid_paths = {
            camera_path_name(camera_code),
            f"{camera_path_name(camera_code)}_b",
        }
        if active_path not in valid_paths:
            continue
        cameras[camera_code] = {
            "camera_code": camera_code,
            "active_path": active_path,
            "next_path": next_path if next_path in valid_paths else None,
            "transition_state": camera_state,
        }

    try:
        transition_camera_count = max(0, int(payload.get("CameraCount") or 0))
    except (TypeError, ValueError):
        transition_camera_count = 0

    result.update(
        {
            "transition_id": str(payload.get("TransitionId", ""))[:64],
            "active_profile": str(payload.get("ActiveProfile", ""))[:32],
            "profile_transition_state": transition_state,
            "profile_transition_from": str(payload.get("FromProfile", ""))[:32],
            "profile_transition_to": str(payload.get("ToProfile", ""))[:32],
            "profile_transition_started_at": str(payload.get("StartedAt", ""))[:64],
            "profile_transition_camera_count": transition_camera_count,
            "cameras": cameras,
            "last_error": str(payload.get("LastError", ""))[:200],
        }
    )
    return result


def acknowledge_monitor_transition(transition_id, camera_codes):
    """原子寫入一次全組預載確認，避免部分Camera先切換造成黑畫面。"""

    state = load_monitor_transition_state()
    if (
        state["profile_transition_state"] != "preloading"
        or not transition_id
        or transition_id != state["transition_id"]
    ):
        return False

    expected_codes = {
        camera_code
        for camera_code, item in state["cameras"].items()
        if item["next_path"]
    }
    acknowledged_codes = {
        str(camera_code).strip().upper()
        for camera_code in camera_codes
        if str(camera_code).strip().upper() in phase1_camera_codes()
    }
    if not expected_codes or acknowledged_codes != expected_codes:
        return False

    payload = {
        "TransitionId": transition_id,
        "CameraCodes": sorted(acknowledged_codes),
        "Acknowledged": True,
    }
    ack_path = monitor_transition_ack_path()
    with _ack_lock:
        ack_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = ack_path.with_name(
            f"{ack_path.name}.{uuid.uuid4().hex}.tmp"
        )
        temporary_path.write_text(
            json.dumps(payload, ensure_ascii=True),
            encoding="ascii",
        )
        os.replace(temporary_path, ack_path)
    return True
