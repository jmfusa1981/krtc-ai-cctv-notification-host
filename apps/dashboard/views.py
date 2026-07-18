from django.apps import apps
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone

from apps.accounts.permissions import can_process_events
from apps.notifications.services import (
    PLAYBACK_MODE_PJSIP,
    PLAYBACK_MODE_SIMULATION,
    get_broadcast_playback_mode,
)


def get_model_or_none(app_label, model_name):
    """
    安全取得 Django model。
    如果 model 或 app 尚未建立，回傳 None，避免 Dashboard 直接崩潰。
    """
    try:
        return apps.get_model(app_label, model_name)
    except LookupError:
        return None


Camera = get_model_or_none("cameras", "Camera")
Event = get_model_or_none("events", "Event")
CrowdFlowSetting = get_model_or_none("events", "CrowdFlowSetting")
CrowdFlowRecord = get_model_or_none("events", "CrowdFlowRecord")

SpeakerDevice = get_model_or_none("notifications", "SpeakerDevice")
AudioFile = get_model_or_none("notifications", "AudioFile")
BroadcastRule = get_model_or_none("notifications", "BroadcastRule")
BroadcastLog = get_model_or_none("notifications", "BroadcastLog")


def get_playback_mode_display():
    playback_mode = get_broadcast_playback_mode()

    if playback_mode == PLAYBACK_MODE_PJSIP:
        return playback_mode, "LIVE", True

    if playback_mode == PLAYBACK_MODE_SIMULATION:
        return playback_mode, "模擬測試", False

    return playback_mode, playback_mode.upper(), False


@login_required
def dashboard_home(request):
    """
    Dashboard 首頁。

    Step 19:
    Dashboard 只顯示近期 AI Event 相關 Camera。
    Monitor Wall 則顯示所有啟用 Camera。
    """

    recent_events = get_recent_events()
    recent_event_camera_ids = get_recent_event_camera_ids(recent_events)
    cameras = get_event_related_cameras(recent_event_camera_ids)
    playback_mode, playback_mode_label, playback_mode_is_live = (
        get_playback_mode_display()
    )

    context = {
        "cameras": cameras,
        "recent_events": recent_events,
        "recent_event_camera_ids": recent_event_camera_ids,

        "crowd_flow_settings": get_crowd_flow_settings(),
        "crowd_flow_records": get_crowd_flow_records(),

        "active_speakers": get_active_count(SpeakerDevice),
        "active_audio_files": get_active_count(AudioFile),
        "active_broadcast_rules": get_active_count(BroadcastRule),
        "pending_broadcast_logs": get_pending_broadcast_log_count(),
        "recent_broadcast_logs": get_recent_broadcast_logs(),
        "can_process_events": can_process_events(request.user),
        "broadcast_playback_mode": playback_mode,
        "broadcast_playback_mode_label": playback_mode_label,
        "broadcast_playback_mode_is_live": playback_mode_is_live,
    }

    return render(request, "dashboard/index.html", context)


@login_required
def monitor_wall(request):
    """
    Monitor Wall。

    顯示所有啟用 Camera，不只顯示事件相關 Camera。
    """

    cameras = []

    if Camera is not None:
        cameras = (
            Camera.objects
            .filter(is_active=True)
            .order_by("id")
        )

    context = {
        "cameras": cameras,
    }

    return render(request, "dashboard/monitor.html", context)


@login_required
def dashboard_live_state_api(request):
    """
    Step 19 Dashboard polling API。

    前端每 5 秒呼叫一次：
    1. 更新近期 AI Event。
    2. 更新事件相關 Camera。
    3. 更新 BroadcastLog。
    4. 更新 pending 任務數量。
    5. 回傳 highlighted_camera_id。
    """

    recent_events = get_recent_events()
    recent_event_camera_ids = get_recent_event_camera_ids(recent_events)
    cameras = get_event_related_cameras(recent_event_camera_ids)
    recent_broadcast_logs = get_recent_broadcast_logs()

    latest_event = recent_events[0] if recent_events else None
    highlighted_camera_id = None

    if latest_event is not None:
        highlighted_camera_id = getattr(latest_event, "camera_id", None)

    playback_mode, playback_mode_label, playback_mode_is_live = (
        get_playback_mode_display()
    )

    data = {
        "server_time": timezone.localtime(timezone.now()).strftime("%Y-%m-%d %H:%M:%S"),
        "highlighted_camera_id": highlighted_camera_id,
        "pending_broadcast_count": get_pending_broadcast_log_count(),
        "can_process_events": can_process_events(request.user),
        "broadcast_playback_mode": playback_mode,
        "broadcast_playback_mode_label": playback_mode_label,
        "broadcast_playback_mode_is_live": playback_mode_is_live,
        "cameras": [
            serialize_camera(camera)
            for camera in cameras
        ],
        "events": [
            serialize_event(event)
            for event in recent_events
        ],
        "broadcast_logs": [
            serialize_broadcast_log(log)
            for log in recent_broadcast_logs
        ],
    }

    return JsonResponse(data)


def get_recent_events():
    """
    取得最近 10 筆 AI Event。
    """

    if Event is None:
        return []

    events = list(
        Event.objects
        .select_related("camera")
        .order_by("-created_at")[:10]
    )

    for event in events:
        event.dashboard_broadcast_rule = get_matching_broadcast_rule(event)

    return events


def get_matching_broadcast_rule(event):
    """Return the same highest-priority rule used by manual broadcasting."""

    if BroadcastRule is None or getattr(event, "camera_id", None) is None:
        return None

    rules = list(
        BroadcastRule.objects
        .select_related("camera", "speaker", "audio_file")
        .filter(
            Q(camera=event.camera) | Q(camera__isnull=True),
            event_type=event.event_type,
            is_active=True,
            speaker__is_active=True,
            audio_file__is_active=True,
        )
    )
    rules.sort(
        key=lambda rule: (
            0 if rule.camera_id == event.camera_id else 1,
            rule.priority,
            rule.rule_code,
        )
    )
    return rules[0] if rules else None


def get_recent_event_camera_ids(recent_events):
    """
    從最近事件中整理出 Camera ID。
    保留事件順序，並避免重複。
    """

    camera_ids = []

    for event in recent_events:
        camera_id = getattr(event, "camera_id", None)

        if camera_id and camera_id not in camera_ids:
            camera_ids.append(camera_id)

    return camera_ids


def get_event_related_cameras(camera_ids):
    """
    Dashboard 只顯示近期 AI Event 相關 Camera。
    """

    if Camera is None:
        return []

    if not camera_ids:
        return []

    return list(
        Camera.objects
        .filter(id__in=camera_ids, is_active=True)
        .order_by("id")
    )


def get_crowd_flow_settings():
    """
    取得人流設定。
    """

    if CrowdFlowSetting is None:
        return []

    return list(
        CrowdFlowSetting.objects
        .select_related("camera")
        .filter(is_active=True)
        .order_by("id")[:10]
    )


def get_crowd_flow_records():
    """
    取得近期人流紀錄。
    """

    if CrowdFlowRecord is None:
        return []

    return list(
        CrowdFlowRecord.objects
        .select_related("camera")
        .order_by("-created_at")[:10]
    )


def get_recent_broadcast_logs():
    """
    取得最近 10 筆 BroadcastLog。
    """

    if BroadcastLog is None:
        return []

    return list(
        BroadcastLog.objects
        .select_related("event", "event__camera", "rule", "speaker", "audio_file")
        .order_by("-created_at")[:10]
    )


def get_active_count(model_class):
    """
    計算 is_active=True 的資料數量。
    如果 model 沒有 is_active 欄位，則改算全部資料。
    """

    if model_class is None:
        return 0

    try:
        return model_class.objects.filter(is_active=True).count()
    except Exception:
        return model_class.objects.count()


def get_pending_broadcast_log_count():
    """
    計算 pending BroadcastLog 數量。
    """

    if BroadcastLog is None:
        return 0

    return BroadcastLog.objects.filter(status="pending").count()


def serialize_camera(camera):
    """
    Camera JSON。
    對應 index.html 裡 renderCameraGrid() 使用的欄位。
    """

    camera_id = getattr(camera, "id", None)

    return {
        "id": camera_id,
        "camera_code": getattr(camera, "camera_code", f"CAM-{camera_id}"),
        "name": getattr(camera, "name", ""),
        "area": getattr(camera, "area", ""),
        "status": getattr(camera, "status", "unknown"),
        "status_display": get_display_value(camera, "status"),
        "description": getattr(camera, "description", ""),
        "stream_url": f"/api/cameras/{camera_id}/stream/",
    }


def serialize_event(event):
    """
    Event JSON。
    對應 index.html 裡 renderEventList() 使用的欄位。
    """

    camera = getattr(event, "camera", None)
    rule = getattr(event, "dashboard_broadcast_rule", None)
    speaker = getattr(rule, "speaker", None) if rule else None
    audio_file = getattr(rule, "audio_file", None) if rule else None

    return {
        "id": getattr(event, "id", None),
        "event_type": getattr(event, "event_type", ""),
        "event_type_display": get_display_value(event, "event_type"),
        "status": getattr(event, "status", ""),
        "status_display": get_display_value(event, "status"),
        "confidence": getattr(event, "confidence", None),
        "camera_id": getattr(event, "camera_id", None),
        "camera_code": getattr(camera, "camera_code", "") if camera else "",
        "camera_name": getattr(camera, "name", "") if camera else "",
        "created_at": format_datetime(getattr(event, "created_at", None)),
        "broadcast_rule_code": getattr(rule, "rule_code", "") if rule else "",
        "speaker_code": getattr(speaker, "speaker_code", "") if speaker else "",
        "speaker_name": getattr(speaker, "name", "") if speaker else "",
        "audio_code": getattr(audio_file, "audio_code", "") if audio_file else "",
        "audio_name": getattr(audio_file, "name", "") if audio_file else "",
    }


def serialize_broadcast_log(log):
    """
    BroadcastLog JSON。
    對應 index.html 裡 renderBroadcastLogs() 使用的欄位。
    """

    event = getattr(log, "event", None)
    rule = getattr(log, "rule", None)
    speaker = getattr(log, "speaker", None)
    audio_file = getattr(log, "audio_file", None)

    event_camera = None
    if event is not None:
        event_camera = getattr(event, "camera", None)

    return {
        "id": getattr(log, "id", None),
        "created_at": format_datetime(getattr(log, "created_at", None)),

        "event_id": getattr(event, "id", None) if event else None,
        "event_type": getattr(event, "event_type", "") if event else "",
        "event_type_display": get_display_value(event, "event_type") if event else "無事件",
        "event_camera_code": getattr(event_camera, "camera_code", "") if event_camera else "",
        "event_camera_name": getattr(event_camera, "name", "") if event_camera else "",

        "rule_id": getattr(rule, "id", None) if rule else None,
        "rule_code": getattr(rule, "rule_code", "") if rule else "無規則",
        "rule_name": getattr(rule, "name", "") if rule else "",

        "speaker_id": getattr(speaker, "id", None) if speaker else None,
        "speaker_code": getattr(speaker, "speaker_code", "") if speaker else "無 Speaker",
        "speaker_name": getattr(speaker, "name", "") if speaker else "",
        "sip_uri": getattr(speaker, "sip_uri", "") if speaker else "",
        "resolved_sip_uri": getattr(speaker, "resolved_sip_uri", "") if speaker else "",

        "audio_file_id": getattr(audio_file, "id", None) if audio_file else None,
        "audio_code": getattr(audio_file, "audio_code", "") if audio_file else "無音檔",
        "audio_file_name": getattr(audio_file, "name", "") if audio_file else "",

        "status": getattr(log, "status", "unknown"),
        "status_display": get_display_value(log, "status"),
    }


def get_display_value(instance, field_name):
    """
    安全取得 Django choices 的 display value。
    """

    if instance is None:
        return ""

    method_name = f"get_{field_name}_display"
    display_method = getattr(instance, method_name, None)

    if callable(display_method):
        return display_method()

    return getattr(instance, field_name, "")


def format_datetime(value):
    """
    統一 datetime 輸出格式。
    """

    if value is None:
        return ""

    return timezone.localtime(value).strftime("%Y-%m-%d %H:%M:%S")
