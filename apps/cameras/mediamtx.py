from dataclasses import dataclass
from urllib.parse import urlencode, urlsplit, urlunsplit

from django.conf import settings


@dataclass(frozen=True)
class MediaMTXPlayback:
    """提供前端所需且不含攝影機憑證的播放描述。"""

    available: bool
    path_name: str = ""
    player_url: str = ""
    whep_url: str = ""
    reason: str = ""


def camera_path_name(camera_code):
    """將既有攝影機代碼轉為可預測的MediaMTX路徑名稱。"""

    normalized = (
        str(camera_code or "").strip().lower().replace("_", "").replace("-", "")
    )
    if not normalized or any(
        not character.isalnum()
        for character in normalized
    ):
        return ""
    return normalized


def _safe_base_url(value):
    parsed = urlsplit(str(value or "").strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        return ""
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", ""))


def phase1_camera_codes():
    return {
        str(code).strip().upper()
        for code in getattr(settings, "KRTC_MEDIAMTX_PHASE1_CAMERA_CODES", ())
        if str(code).strip()
    }


def player_url_for_path(path_name):
    """以受控MediaMTX path建立不含來源憑證的瀏覽器播放網址。"""

    base_url = _safe_base_url(
        getattr(settings, "KRTC_MEDIAMTX_WEBRTC_BASE_URL", "")
    )
    normalized_path = str(path_name or "").strip().lower()
    if (
        not base_url
        or not normalized_path
        or any(
            not (character.isalnum() or character == "_")
            for character in normalized_path
        )
    ):
        return ""
    player_query = urlencode(
        {
            "controls": "false",
            "muted": "true",
            "autoplay": "true",
            "playsInline": "true",
        }
    )
    return f"{base_url}/{normalized_path}?{player_query}"


def _resolve_camera_path(camera):
    """解析 Camera 目前應使用的 canonical 或切換中 MediaMTX path。"""

    camera_code = str(camera.camera_code).upper()
    path_name = camera_path_name(camera_code)
    try:
        from .monitor_transitions import load_monitor_transition_state

        transition = load_monitor_transition_state()
        transition_path = transition["cameras"].get(camera_code, {}).get(
            "active_path",
            path_name,
        )
        # canonical path 不需掃描 runtime；只有 H265 A/B alternate 才驗證 owner。
        if transition_path != path_name:
            from .bridge_runtime import (
                effective_camera_path,
                load_bridge_statuses,
            )

            path_name = effective_camera_path(
                camera_code,
                load_bridge_statuses([camera_code]),
                transition,
            )
    except (OSError, ValueError, TypeError):
        pass
    return path_name


def get_camera_browser_playback(camera):
    """建立前端可尋址的播放描述，實際 path readiness 另由狀態 API 判定。"""

    if getattr(settings, "KRTC_MONITOR_MEDIA_MODE", "legacy") != "mediamtx":
        return MediaMTXPlayback(False, reason="legacy_mode")
    if not camera.is_active:
        return MediaMTXPlayback(False, reason="inactive")

    path_name = _resolve_camera_path(camera)
    player_url = player_url_for_path(path_name)
    if not player_url or not path_name:
        return MediaMTXPlayback(False, reason="invalid_configuration")

    path_url = player_url.split("?", 1)[0]
    return MediaMTXPlayback(
        True,
        path_name=path_name,
        player_url=player_url,
        whep_url=f"{path_url}/whep",
    )


def get_camera_playback(camera):
    """依伺服器設定建立安全的WebRTC播放資訊，不回傳來源RTSP網址。"""

    if not getattr(settings, "KRTC_MEDIAMTX_ENABLED", False):
        return MediaMTXPlayback(False, reason="disabled")
    if getattr(settings, "KRTC_MONITOR_MEDIA_MODE", "legacy") != "mediamtx":
        return MediaMTXPlayback(False, reason="legacy_mode")
    if str(camera.camera_code).upper() not in phase1_camera_codes():
        return MediaMTXPlayback(False, reason="not_enabled_for_camera")
    if not camera.is_active:
        return MediaMTXPlayback(False, reason="inactive")
    if camera.status != "online" and not camera.is_online:
        return MediaMTXPlayback(False, reason="offline")

    return get_camera_browser_playback(camera)
