from django.conf import settings
from django.utils import timezone


NETWORK_REACHABLE = "network_reachable"
STALE = "stale"
UNREACHABLE = "unreachable"
MEDIA_READY = "media_ready"
MEDIA_UNAVAILABLE = "media_unavailable"
PLAYBACK_READY = "playback_ready"


def camera_network_snapshot(camera, now=None):
    """將既有 Camera probe 欄位解讀為純網路快照，不延伸代表媒體狀態。"""

    reachable = bool(
        getattr(camera, "is_online", False)
        or getattr(camera, "status", "") == "online"
    )
    checked_at = getattr(camera, "last_checked_at", None)
    stale_seconds = max(
        1,
        int(getattr(settings, "KRTC_CAMERA_HEALTH_STALE_SECONDS", 300)),
    )
    current_time = now or timezone.now()
    if checked_at is None:
        state = STALE
    elif (current_time - checked_at).total_seconds() > stale_seconds:
        state = STALE
    else:
        state = NETWORK_REACHABLE if reachable else UNREACHABLE
    return {
        "network_reachable": reachable,
        "network_state": state,
        "network_checked_at": checked_at,
    }


def evaluate_media_availability(
    *,
    camera_code,
    canonical_path,
    effective_path,
    effective_bridge_state,
    mediamtx_reachable,
    path_ready,
    metadata_available,
    network_reachable=None,
    network_state=STALE,
):
    """以 bridge 與 MediaMTX path 作為播放真相，網路 probe 僅保留為警示。"""

    bridge_ready = effective_bridge_state == "running"
    media_ready = bool(
        metadata_available
        and mediamtx_reachable
        and bridge_ready
        and path_ready
    )
    if not metadata_available:
        playback_reason = "playback_metadata_unavailable"
    elif not mediamtx_reachable:
        playback_reason = "mediamtx_unreachable"
    elif not bridge_ready:
        playback_reason = f"bridge_{effective_bridge_state or 'unknown'}"
    elif not path_ready:
        playback_reason = "path_not_ready"
    else:
        playback_reason = "ready"
    return {
        "camera": str(camera_code or "").upper(),
        "canonical_path": canonical_path,
        "effective_path": effective_path,
        "effective_state": effective_bridge_state or "unknown",
        "network_reachable": network_reachable,
        "network_state": network_state,
        "path_ready": bool(path_ready),
        "media_state": MEDIA_READY if media_ready else MEDIA_UNAVAILABLE,
        "media_ready": media_ready,
        "playback_state": PLAYBACK_READY if media_ready else MEDIA_UNAVAILABLE,
        "playback_allowed": media_ready,
        "playback_reason": playback_reason,
    }
