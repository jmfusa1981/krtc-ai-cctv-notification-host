from datetime import timedelta

from django.apps import apps
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone
from apps.events.services.snapshot_localizer import event_has_local_snapshot, local_snapshot_url

from apps.accounts.permissions import can_manage_frontend_settings, can_process_events
from apps.notifications.services import (
    PLAYBACK_MODE_PJSIP,
    PLAYBACK_MODE_SIMULATION,
    get_broadcast_playback_mode,
)


EVENT_STATUS_LABELS = {
    "new": "待處理",
    "processing": "處理中",
    "confirmed": "已確認",
    "false_alarm": "誤報",
    "notified": "已通報",
    "closed": "已解除",
}

CAMERA_STATUS_LABELS = {
    "online": "連線正常",
    "offline": "離線",
    "maintenance": "維護中",
    "error": "連線異常",
    "unknown": "狀態未知",
}

BROADCAST_STATUS_LABELS = {
    "pending": "待處理",
    "playing": "播放中",
    "success": "完成",
    "failed": "失敗",
    "skipped": "已略過",
}


def get_model_or_none(app_label, model_name):
    """安全取得 Django model；不存在時回傳 None。"""
    try:
        return apps.get_model(app_label, model_name)
    except LookupError:
        return None


Camera = get_model_or_none("cameras", "Camera")
Event = get_model_or_none("events", "Event")
LocalAlarmPolicy = get_model_or_none("events", "LocalAlarmPolicy")
CrowdFlowSetting = get_model_or_none("events", "CrowdFlowSetting")
CrowdFlowRecord = get_model_or_none("events", "CrowdFlowRecord")
ZoneCountState = get_model_or_none("events", "ZoneCountState")

SpeakerDevice = get_model_or_none("notifications", "SpeakerDevice")
AudioFile = get_model_or_none("notifications", "AudioFile")
BroadcastRule = get_model_or_none("notifications", "BroadcastRule")
BroadcastLog = get_model_or_none("notifications", "BroadcastLog")
BroadcastSchedule = get_model_or_none("notifications", "BroadcastSchedule")

InferenceHost = (
    get_model_or_none("ai_bridge", "InferenceHost")
    or get_model_or_none("inference", "InferenceHost")
)


def get_playback_mode_display():
    playback_mode = get_broadcast_playback_mode()

    if playback_mode == PLAYBACK_MODE_PJSIP:
        return playback_mode, "正式廣播", True

    if playback_mode == PLAYBACK_MODE_SIMULATION:
        return playback_mode, "模擬測試", False

    return playback_mode, "廣播模式", False


@login_required
def dashboard_home(request):
    recent_events = get_recent_events()
    recent_event_camera_ids = get_recent_event_camera_ids(recent_events)
    cameras = get_event_related_cameras(recent_event_camera_ids)
    playback_mode, playback_mode_label, playback_mode_is_live = (
        get_playback_mode_display()
    )

    crowd_flow_summary = get_crowd_flow_summary()
    crowd_flow_items = get_area_crowd_flow_items()

    context = {
        "cameras": cameras,
        "station_camera_count": get_station_camera_count(),
        "recent_events": recent_events,
        "recent_event_camera_ids": recent_event_camera_ids,
        "crowd_flow_settings": get_crowd_flow_settings(),
        "crowd_flow_records": get_crowd_flow_records(),
        "crowd_flow_summary": crowd_flow_summary,
        "crowd_flow_items": crowd_flow_items,
        "inference_host_summary": get_inference_host_summary(),
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
def station_broadcast_console(request):
    """Single-station PA broadcast console for manual prerecorded playback."""
    StationLocalSettings = get_model_or_none("settings_app", "StationLocalSettings")
    station_name = "KRTC Demo Station"
    if StationLocalSettings is not None:
        try:
            station_name = StationLocalSettings.load().station_name
        except Exception:
            pass

    speakers = []
    if SpeakerDevice is not None:
        speakers = list(
            SpeakerDevice.objects.filter(is_active=True).order_by("area", "speaker_code")
        )

    audio_files = []
    if AudioFile is not None:
        audio_files = list(AudioFile.objects.filter(is_active=True).order_by("audio_code"))
        for audio in audio_files:
            try:
                audio.file_available = bool(audio.file and audio.file.storage.exists(audio.file.name))
            except Exception:
                audio.file_available = False

    recent_logs = []
    if BroadcastLog is not None:
        recent_logs = list(
            BroadcastLog.objects.select_related("speaker", "audio_file")
            .order_by("-created_at")[:10]
        )

    schedules = []
    if BroadcastSchedule is not None:
        schedules = list(
            BroadcastSchedule.objects.select_related("audio_file")
            .prefetch_related("speakers")
            .order_by("next_run_at", "name")[:20]
        )

    broadcast_rules = []
    if BroadcastRule is not None:
        broadcast_rules = list(
            BroadcastRule.objects.select_related("camera", "speaker", "audio_file")
            .prefetch_related("speakers")
            .order_by("priority", "rule_code")
        )
        for rule in broadcast_rules:
            rule.speaker_targets_label = "、".join(
                speaker.speaker_code for speaker in rule.target_speakers_queryset()
            ) or "—"

    playback_mode, playback_mode_label, playback_mode_is_live = get_playback_mode_display()
    speaker_areas = sorted({(speaker.area or "未設定") for speaker in speakers})

    context = {
        "station_name": station_name,
        "speakers": speakers,
        "speaker_areas": speaker_areas,
        "audio_files": audio_files,
        "recent_broadcast_logs": recent_logs,
        "broadcast_schedules": schedules,
        "broadcast_rules": broadcast_rules,
        "active_broadcast_rule_count": sum(1 for rule in broadcast_rules if rule.is_active),
        "auto_broadcast_rule_count": sum(1 for rule in broadcast_rules if rule.is_active and rule.auto_broadcast),
        "can_edit_broadcast_rules": can_manage_frontend_settings(request.user),
        "active_speaker_count": len(speakers),
        "available_audio_count": sum(1 for audio in audio_files if audio.file_available),
        "broadcast_playback_mode": playback_mode,
        "broadcast_playback_mode_label": playback_mode_label,
        "broadcast_playback_mode_is_live": playback_mode_is_live,
        "can_process_events": can_process_events(request.user),
        "live_microphone_max_speakers": int(getattr(settings, "PJSIP_MIC_MAX_SPEAKERS", 4)),
        "live_microphone_max_duration_seconds": int(getattr(settings, "PJSIP_MIC_MAX_DURATION_SECONDS", 300)),
    }
    return render(request, "dashboard/station_broadcast.html", context)


@login_required
def device_list(request):
    """站區設備清單：唯讀顯示攝影機與廣播喇叭設定。"""
    cameras = []
    speakers = []

    if Camera is not None:
        cameras = list(Camera.objects.all().order_by("camera_code"))
        for camera in cameras:
            camera.connection_status_label = CAMERA_STATUS_LABELS.get(
                getattr(camera, "status", "unknown"),
                "狀態未知",
            )
            camera.active_status_label = (
                "已啟用" if getattr(camera, "is_active", False) else "已停用"
            )
            camera.stream_status_label = get_camera_stream_status_label(camera)

    if SpeakerDevice is not None:
        speakers = list(SpeakerDevice.objects.all().order_by("speaker_code"))
        for speaker in speakers:
            speaker.device_area = (
                getattr(speaker, "area", "")
                or getattr(speaker, "location", "")
                or getattr(speaker, "location_note", "")
                or "未設定"
            )
            speaker.active_status_label = (
                "已啟用" if getattr(speaker, "is_active", False) else "已停用"
            )
            speaker.device_status_label = get_speaker_status_label(speaker)

    context = {
        "cameras": cameras,
        "speakers": speakers,
        "camera_count": len(cameras),
        "speaker_count": len(speakers),
        "camera_abnormal_count": sum(
            1
            for camera in cameras
            if getattr(camera, "status", "unknown") != "online"
        ),
        "speaker_abnormal_count": sum(
            1
            for speaker in speakers
            if getattr(speaker, "status", "unknown") != "online"
        ),
    }

    return render(request, "dashboard/device_list.html", context)


def get_camera_stream_status_label(camera):
    if not getattr(camera, "is_active", False):
        return "未啟用"

    status = getattr(camera, "status", "unknown")
    return {
        "online": "正常",
        "offline": "無法連線",
        "maintenance": "暫停檢查",
        "error": "檢查異常",
    }.get(status, "未檢查")


def get_speaker_status_label(speaker):
    return {
        "online": "線上",
        "offline": "離線",
        "unknown": "未知",
        "maintenance": "維護中",
        "error": "異常",
    }.get(getattr(speaker, "status", "unknown"), "未知")


@login_required
def event_snapshot_list(request):
    """Show only PAO-local event snapshots from the most recent 30 days."""
    snapshot_events = []
    snapshot_since = timezone.now() - timedelta(days=30)

    if Event is not None:
        candidates = list(
            Event.objects.select_related("camera")
            .filter(detected_at__gte=snapshot_since)
            .exclude(snapshot="")
            .order_by("-detected_at", "-created_at")[:500]
        )

        for event in candidates:
            if not event_has_local_snapshot(event):
                continue
            event.snapshot_display_url = local_snapshot_url(event)
            event.snapshot_storage_label = "通報主機本地"
            event.snapshot_is_local = True
            event.status_display_zh = EVENT_STATUS_LABELS.get(
                getattr(event, "status", ""),
                get_display_value(event, "status") or "未知",
            )
            snapshot_events.append(event)
            if len(snapshot_events) >= 200:
                break

    context = {
        "snapshot_events": snapshot_events,
        "snapshot_count": len(snapshot_events),
        "local_snapshot_count": len(snapshot_events),
        "remote_snapshot_count": 0,
        "snapshot_since": snapshot_since,
    }

    return render(request, "dashboard/event_snapshot_list.html", context)


@login_required
def monitor_wall(request):
    cameras = []

    if Camera is not None:
        cameras = Camera.objects.filter(is_active=True).order_by("id")

    return render(request, "dashboard/monitor.html", {"cameras": cameras})


@login_required
def dashboard_live_state_api(request):
    recent_events = get_recent_events()
    recent_event_camera_ids = get_recent_event_camera_ids(recent_events)
    cameras = get_event_related_cameras(recent_event_camera_ids)
    recent_broadcast_logs = get_recent_broadcast_logs()

    latest_event = recent_events[0] if recent_events else None
    highlighted_camera_id = (
        getattr(latest_event, "camera_id", None) if latest_event else None
    )

    playback_mode, playback_mode_label, playback_mode_is_live = (
        get_playback_mode_display()
    )
    crowd_flow_summary = get_crowd_flow_summary()
    crowd_flow_items = get_area_crowd_flow_items()
    local_alarm = get_local_alarm_state()
    event_alert_active = local_alarm["active_count"] > 0
    inference_host_maps = get_inference_host_display_maps()

    return JsonResponse(
        {
            "server_time": timezone.localtime(timezone.now()).strftime(
                "%Y-%m-%d %H:%M:%S"
            ),
            "highlighted_camera_id": highlighted_camera_id,
            "station_camera_count": get_station_camera_count(),
            "pending_broadcast_count": get_pending_broadcast_log_count(),
            "crowd_flow": crowd_flow_summary,
            "crowd_flow_items": crowd_flow_items,
            "inference_hosts": get_inference_host_summary(),
            "event_alert_active": event_alert_active,
            "local_alarm": local_alarm,
            "can_process_events": can_process_events(request.user),
            "broadcast_playback_mode": playback_mode,
            "broadcast_playback_mode_label": playback_mode_label,
            "broadcast_playback_mode_is_live": playback_mode_is_live,
            "cameras": [serialize_camera(camera) for camera in cameras],
            "events": [serialize_event(event, inference_host_maps) for event in recent_events],
            "broadcast_logs": [
                serialize_broadcast_log(log) for log in recent_broadcast_logs
            ],
        }
    )


def get_local_alarm_state():
    """Return every alarm-relevant event ID, independent of the 10-row UI list."""
    if Event is None or LocalAlarmPolicy is None:
        return {
            "enabled": False,
            "enabled_at": None,
            "active_count": 0,
            "active_event_ids": [],
        }

    policy = LocalAlarmPolicy.load()
    active_event_ids = []

    if policy.is_enabled:
        active_event_ids = list(
            Event.objects.filter(
                created_at__gte=policy.enabled_at,
                status__in={"new", "processing", "confirmed"},
            )
            .order_by("id")
            .values_list("id", flat=True)
        )

    return {
        "enabled": policy.is_enabled,
        "enabled_at": policy.enabled_at.isoformat(),
        "active_count": len(active_event_ids),
        "active_event_ids": active_event_ids,
    }


def get_recent_events():
    if Event is None:
        return []

    events = list(
        Event.objects.select_related("camera").order_by("-created_at")[:10]
    )

    for event in events:
        event.dashboard_broadcast_rule = get_matching_broadcast_rule(event)

    return events


def get_matching_broadcast_rule(event):
    if BroadcastRule is None or getattr(event, "camera_id", None) is None:
        return None

    rules = list(
        BroadcastRule.objects.select_related(
            "camera", "speaker", "audio_file"
        ).prefetch_related(
            "speakers"
        ).filter(
            Q(camera=event.camera) | Q(camera__isnull=True),
            event_type=event.event_type,
            is_active=True,
            audio_file__is_active=True,
        ).filter(Q(speakers__is_active=True) | Q(speaker__is_active=True)).distinct()
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
    camera_ids = []

    for event in recent_events:
        camera_id = getattr(event, "camera_id", None)
        if camera_id and camera_id not in camera_ids:
            camera_ids.append(camera_id)

    return camera_ids


def get_station_camera_count():
    """
    回傳目前站區啟用中的攝影機總數。

    現階段以 Camera.is_active 統計。
    後續建立站區設定頁後，可改為由站區設定資料或設備清單 API 提供。
    """
    if Camera is None:
        return 0

    field_names = {field.name for field in Camera._meta.get_fields()}

    if "is_active" in field_names:
        return Camera.objects.filter(is_active=True).count()

    return Camera.objects.count()


def get_event_related_cameras(camera_ids):
    if Camera is None or not camera_ids:
        return []

    return list(
        Camera.objects.filter(id__in=camera_ids, is_active=True).order_by("id")
    )


def get_crowd_flow_settings():
    if CrowdFlowSetting is None:
        return []

    return list(
        CrowdFlowSetting.objects.select_related("camera")
        .filter(is_active=True)
        .order_by("id")[:10]
    )


def get_crowd_flow_records():
    if CrowdFlowRecord is None:
        return []

    return list(
        CrowdFlowRecord.objects.select_related("camera")
        .order_by("-created_at")[:10]
    )


def _aggregate_zone_count_rows(rows):
    """Aggregate current ZoneCountState rows by station + roi_id.

    One physical zone can be observed by multiple cameras. In that case PAO
    sums the counts before rendering the Dashboard. Camera IDs remain secondary
    source metadata.
    """
    groups = {}
    for row in rows:
        zone_label = (row.roi_id or "").strip() or "未命名區域"
        station = (row.station or "").strip()
        key = (station, zone_label)
        group = groups.setdefault(
            key,
            {
                "station": station,
                "zone_label": zone_label,
                "count": 0,
                "thresholds": [],
                "source_cameras": [],
                "camera_codes": [],
                "latest_at": None,
            },
        )

        group["count"] += int(row.count or 0)
        if row.threshold is not None:
            group["thresholds"].append(int(row.threshold))

        source_id = (row.source_camera_id or "").strip()
        if source_id and source_id not in group["source_cameras"]:
            group["source_cameras"].append(source_id)

        local_code = getattr(row.camera, "camera_code", "") if getattr(row, "camera_id", None) else ""
        display_code = (local_code or source_id).strip()
        if display_code and display_code not in group["camera_codes"]:
            group["camera_codes"].append(display_code)

        current_at = row.source_updated_at or row.received_at
        if current_at is not None and (group["latest_at"] is None or current_at > group["latest_at"]):
            group["latest_at"] = current_at

    items = []
    for (station, zone_label), group in groups.items():
        threshold = max(group["thresholds"]) if group["thresholds"] else None
        camera_codes = group["camera_codes"]
        if len(camera_codes) <= 2:
            camera_summary = " + ".join(camera_codes) or "--"
        else:
            camera_summary = f"{len(camera_codes)} 台攝影機"

        latest_at = group["latest_at"]
        items.append(
            {
                "zone_key": f"{station}:{zone_label}",
                "zone_label": zone_label,
                "camera_id": ",".join(group["source_cameras"]),
                "camera_code": camera_summary,
                "source_cameras": list(group["source_cameras"]),
                "station": station,
                "count": group["count"],
                "threshold": threshold,
                "is_abnormal": threshold is not None and group["count"] >= threshold,
                "recorded_at": (
                    timezone.localtime(latest_at).strftime("%Y-%m-%d %H:%M:%S")
                    if latest_at else ""
                ),
            }
        )

    return sorted(items, key=lambda item: (item["station"], item["zone_label"]))


def get_area_crowd_flow_items():
    """Return fresh zone telemetry aggregated by station + Zone label."""
    if ZoneCountState is None:
        return []

    stale_seconds = max(15, int(getattr(settings, "ZONE_COUNT_STALE_SECONDS", 45)))
    fresh_after = timezone.now() - timedelta(seconds=stale_seconds)
    rows = list(
        ZoneCountState.objects.select_related("camera", "inference_host")
        .filter(received_at__gte=fresh_after)
        .order_by("station", "roi_id", "source_camera_id")
    )
    return _aggregate_zone_count_rows(rows)


def get_crowd_flow_summary():
    """
    回傳 Dashboard 狀態列使用的人流摘要。

    CrowdFlowRecord 欄位：
    - count
    - is_abnormal
    - camera
    - recorded_at / created_at

    CrowdFlowSetting 欄位：
    - min_count
    - max_count
    - camera
    - is_active
    """
    default_summary = {
        "count": None,
        "min_count": None,
        "max_count": None,
        "is_abnormal": False,
        "status_label": "尚無資料",
        "range_label": "尚未設定",
    }

    if CrowdFlowRecord is None:
        return default_summary

    record = (
        CrowdFlowRecord.objects.select_related("camera")
        .order_by("-created_at")
        .first()
    )

    if record is None:
        return default_summary

    setting = None

    if CrowdFlowSetting is not None:
        setting = (
            CrowdFlowSetting.objects.filter(
                camera_id=getattr(record, "camera_id", None),
                is_active=True,
            )
            .order_by("id")
            .first()
        )

        if setting is None:
            setting = (
                CrowdFlowSetting.objects.filter(is_active=True)
                .order_by("id")
                .first()
            )

    count = getattr(record, "count", None)
    min_count = getattr(setting, "min_count", None) if setting else None
    max_count = getattr(setting, "max_count", None) if setting else None

    is_abnormal = bool(getattr(record, "is_abnormal", False))

    if (
        count is not None
        and min_count is not None
        and max_count is not None
    ):
        is_abnormal = count < min_count or count > max_count

    if min_count is not None and max_count is not None:
        range_label = f"設定 {min_count}–{max_count} 人"
    else:
        range_label = "尚未設定正常範圍"

    return {
        "count": count,
        "min_count": min_count,
        "max_count": max_count,
        "is_abnormal": is_abnormal,
        "status_label": "異常" if is_abnormal else "正常",
        "range_label": range_label,
    }


def get_inference_host_summary():
    """Return the station inference-host summary from the real GET /health result.

    The Dashboard must not infer API health from the WebSocket connection or from
    the generic InferenceHost.status field. Each active host is healthy only when
    its InferenceConnectionState contains a fresh ``health_status == "ok"`` result.
    """
    default_summary = {
        "configured_count": 0,
        "healthy_count": 0,
        "abnormal_count": 0,
        "is_abnormal": False,
        "is_unconfigured": True,
        "status_label": "未設定主機",
        "detail_label": "尚未設定推論主機",
        "abnormal_host_codes": [],
    }

    if InferenceHost is None:
        return default_summary

    hosts = list(
        InferenceHost.objects.filter(is_active=True)
        .select_related("connection_state")
        .order_by("id")
    )
    if not hosts:
        return default_summary

    stale_seconds = max(
        1,
        int(getattr(settings, "INFERENCE_HEALTH_STALE_SECONDS", 20)),
    )
    stale_before = timezone.now() - timedelta(seconds=stale_seconds)

    abnormal_host_codes = []
    healthy_count = 0

    for host in hosts:
        host_code = host.host_code or host.name or f"HOST-{host.pk}"
        try:
            state = host.connection_state
        except Exception:
            state = None

        health_status = str(
            getattr(state, "health_status", "unknown") or "unknown"
        ).strip().lower()
        checked_at = getattr(state, "last_heartbeat_at", None)

        is_fresh_ok = (
            health_status == "ok"
            and checked_at is not None
            and checked_at >= stale_before
        )

        if is_fresh_ok:
            healthy_count += 1
        else:
            abnormal_host_codes.append(str(host_code))

    configured_count = len(hosts)
    abnormal_count = len(abnormal_host_codes)
    is_abnormal = abnormal_count > 0

    return {
        "configured_count": configured_count,
        "healthy_count": healthy_count,
        "abnormal_count": abnormal_count,
        "is_abnormal": is_abnormal,
        "is_unconfigured": False,
        "status_label": "異常" if is_abnormal else "正常",
        "detail_label": (
            "異常：" + "、".join(abnormal_host_codes)
            if is_abnormal
            else "全部推論主機狀態正常"
        ),
        "abnormal_host_codes": abnormal_host_codes,
    }


def get_recent_broadcast_logs():
    if BroadcastLog is None:
        return []

    return list(
        BroadcastLog.objects.select_related(
            "event",
            "event__camera",
            "rule",
            "speaker",
            "audio_file",
        ).order_by("-created_at")[:10]
    )


def get_active_count(model_class):
    if model_class is None:
        return 0

    field_names = {field.name for field in model_class._meta.get_fields()}

    if "is_active" in field_names:
        return model_class.objects.filter(is_active=True).count()

    return model_class.objects.count()


def get_pending_broadcast_log_count():
    if BroadcastLog is None:
        return 0

    return BroadcastLog.objects.filter(status="pending").count()


def serialize_camera(camera):
    camera_id = getattr(camera, "id", None)
    status = getattr(camera, "status", "unknown")

    return {
        "id": camera_id,
        "camera_code": getattr(camera, "camera_code", f"CAM-{camera_id}"),
        "name": getattr(camera, "name", ""),
        "area": getattr(camera, "area", ""),
        "status": status,
        "status_display": localize_choice(
            camera,
            "status",
            CAMERA_STATUS_LABELS,
        ),
        "description": getattr(camera, "description", ""),
        "stream_url": f"/api/cameras/{camera_id}/stream/",
    }


def resolve_event_snapshot_url(event):
    """Return only a verified PAO-local snapshot URL."""
    return local_snapshot_url(event)


def get_inference_host_display_maps():
    """Return inference-host display names keyed by code and normalized base URL."""
    by_code = {}
    by_url = {}
    if InferenceHost is None:
        return by_code, by_url

    for host in InferenceHost.objects.all().only("host_code", "name", "base_url"):
        display_name = (getattr(host, "name", "") or getattr(host, "host_code", "")).strip()
        host_code = (getattr(host, "host_code", "") or "").strip()
        base_url = (getattr(host, "base_url", "") or "").strip().rstrip("/")
        if host_code:
            by_code[host_code] = display_name or host_code
        if base_url:
            by_url[base_url] = display_name or host_code or base_url

    return by_code, by_url


def serialize_event(event, inference_host_maps=None):
    camera = getattr(event, "camera", None)
    rule = getattr(event, "dashboard_broadcast_rule", None)
    speaker = getattr(rule, "speaker", None) if rule else None
    audio_file = getattr(rule, "audio_file", None) if rule else None

    source_host = (getattr(event, "source_host", "") or "").strip()
    host_code = (getattr(event, "inference_host_code", "") or "").strip()
    by_code, by_url = inference_host_maps or ({}, {})
    normalized_source_host = source_host.rstrip("/")
    host_name = (
        by_code.get(host_code, "")
        or by_url.get(normalized_source_host, "")
        or host_code
        or source_host
    )

    detected_at = getattr(event, "detected_at", None)
    created_at = getattr(event, "created_at", None)

    return {
        "id": getattr(event, "id", None),
        "external_event_id": getattr(event, "external_event_id", ""),
        "source_event_id": getattr(event, "source_event_id", ""),
        "source_host_code": host_code,
        "source_host_name": host_name,
        "event_type": getattr(event, "event_type", ""),
        "event_type_display": get_display_value(event, "event_type"),
        "status": getattr(event, "status", ""),
        "status_display": localize_choice(
            event,
            "status",
            EVENT_STATUS_LABELS,
        ),
        "severity": getattr(event, "severity", ""),
        "confidence": getattr(event, "confidence", None),
        "camera_id": getattr(event, "camera_id", None),
        "camera_code": getattr(camera, "camera_code", "") if camera else "",
        "camera_name": getattr(camera, "name", "") if camera else "",
        "camera_area": getattr(camera, "area", "") if camera else "",
        "station": getattr(event, "station", ""),
        "area": getattr(event, "area", ""),
        "roi_id": getattr(event, "roi_id", ""),
        "detected_at": format_datetime(detected_at),
        "created_at": format_datetime(created_at),
        "snapshot_url": local_snapshot_url(event),
        "annotated_snapshot_url": getattr(
            event,
            "annotated_snapshot_url",
            "",
        ),
        "video_url": getattr(event, "video_url", ""),
        "broadcast_rule_code": getattr(rule, "rule_code", "") if rule else "",
        "speaker_code": getattr(speaker, "speaker_code", "") if speaker else "",
        "speaker_name": getattr(speaker, "name", "") if speaker else "",
        "audio_code": getattr(audio_file, "audio_code", "") if audio_file else "",
        "audio_name": getattr(audio_file, "name", "") if audio_file else "",
    }


def serialize_broadcast_log(log):
    event = getattr(log, "event", None)
    rule = getattr(log, "rule", None)
    speaker = getattr(log, "speaker", None)
    audio_file = getattr(log, "audio_file", None)
    event_camera = getattr(event, "camera", None) if event else None

    return {
        "id": getattr(log, "id", None),
        "created_at": format_datetime(getattr(log, "created_at", None)),
        "event_id": getattr(event, "id", None) if event else None,
        "event_type": getattr(event, "event_type", "") if event else "",
        "event_type_display": (
            get_display_value(event, "event_type") if event else "無事件"
        ),
        "event_camera_code": (
            getattr(event_camera, "camera_code", "") if event_camera else ""
        ),
        "event_camera_name": (
            getattr(event_camera, "name", "") if event_camera else ""
        ),
        "rule_id": getattr(rule, "id", None) if rule else None,
        "rule_code": getattr(rule, "rule_code", "") if rule else "無規則",
        "rule_name": getattr(rule, "name", "") if rule else "",
        "speaker_id": getattr(speaker, "id", None) if speaker else None,
        "speaker_code": (
            getattr(speaker, "speaker_code", "") if speaker else "無廣播喇叭"
        ),
        "speaker_name": getattr(speaker, "name", "") if speaker else "",
        "sip_uri": getattr(speaker, "sip_uri", "") if speaker else "",
        "resolved_sip_uri": (
            getattr(speaker, "resolved_sip_uri", "") if speaker else ""
        ),
        "audio_file_id": getattr(audio_file, "id", None) if audio_file else None,
        "audio_code": (
            getattr(audio_file, "audio_code", "") if audio_file else "無音檔"
        ),
        "audio_file_name": getattr(audio_file, "name", "") if audio_file else "",
        "status": getattr(log, "status", "unknown"),
        "status_display": localize_choice(
            log,
            "status",
            BROADCAST_STATUS_LABELS,
        ),
        "error_message": (
            getattr(log, "error_message", "")
            or getattr(log, "failure_reason", "")
        ),
    }


def localize_choice(instance, field_name, mapping):
    raw_value = getattr(instance, field_name, "")
    return mapping.get(raw_value, get_display_value(instance, field_name))


def get_display_value(instance, field_name):
    if instance is None:
        return ""

    display_method = getattr(instance, f"get_{field_name}_display", None)

    if callable(display_method):
        return display_method()

    return getattr(instance, field_name, "")


def format_datetime(value):
    if value is None:
        return ""

    return timezone.localtime(value).strftime("%Y-%m-%d %H:%M:%S")
