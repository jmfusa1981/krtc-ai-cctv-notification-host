from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from apps.cameras.models import Camera
from apps.events.models import Event, CrowdFlowSetting, CrowdFlowRecord
from apps.notifications.models import BroadcastLog, BroadcastRule, SpeakerDevice, AudioFile


@login_required(login_url="/login/")
def dashboard_home(request):
    """
    KRTC AI CCTV 通報主機 Dashboard

    功能：
    1. 顯示近期 AI 事件
    2. 僅顯示近期 AI 事件相關的攝影機即時影像
    3. 支援 Dashboard 端事件攝影機定位與紅框標示
    4. 顯示人流統計設定
    5. 顯示近期人流統計紀錄
    6. 顯示 IP Speaker / PAO 廣播任務狀態
    """

    recent_events = (
        Event.objects
        .select_related("camera")
        .all()
        .order_by("-created_at")[:10]
    )

    recent_event_camera_ids = []

    for event in recent_events:
        if event.camera_id and event.camera_id not in recent_event_camera_ids:
            recent_event_camera_ids.append(event.camera_id)

    event_cameras = list(
        Camera.objects
        .filter(
            is_active=True,
            id__in=recent_event_camera_ids,
        )
    )

    cameras = sorted(
        event_cameras,
        key=lambda camera: recent_event_camera_ids.index(camera.id),
    )

    crowd_flow_settings = (
        CrowdFlowSetting.objects
        .filter(is_active=True)
        .order_by("name")
    )

    crowd_flow_records = (
        CrowdFlowRecord.objects
        .all()
        .order_by("-created_at")[:10]
    )

    recent_broadcast_logs = (
        BroadcastLog.objects
        .select_related("event", "rule", "speaker", "audio_file")
        .order_by("-created_at")[:10]
    )

    active_broadcast_rules = BroadcastRule.objects.filter(is_active=True).count()
    active_speakers = SpeakerDevice.objects.filter(is_active=True).count()
    active_audio_files = AudioFile.objects.filter(is_active=True).count()

    pending_broadcast_logs = BroadcastLog.objects.filter(
        status=BroadcastLog.STATUS_PENDING
    ).count()

    context = {
        "page_title": "KRTC AI CCTV 通報主機 Dashboard",

        # Dashboard 左側事件影像區：
        # 僅顯示近期 AI 事件相關的 Camera。
        "cameras": cameras,
        "recent_event_camera_ids": recent_event_camera_ids,

        # 右側近期 AI 事件列表。
        "recent_events": recent_events,

        # 人流統計。
        "crowd_flow_settings": crowd_flow_settings,
        "crowd_flow_records": crowd_flow_records,

        # IP Speaker / PAO 廣播任務。
        "recent_broadcast_logs": recent_broadcast_logs,
        "active_broadcast_rules": active_broadcast_rules,
        "active_speakers": active_speakers,
        "active_audio_files": active_audio_files,
        "pending_broadcast_logs": pending_broadcast_logs,
    }

    return render(request, "dashboard/index.html", context)


@login_required(login_url="/login/")
def monitor_wall(request):
    """
    KRTC AI CCTV 純影像監控牆

    功能：
    1. 顯示所有啟用中的攝影機
    2. 支援 1 / 4 / 9 / 16 分割畫面
    3. 提供返回 Dashboard 的操作
    4. 顯示目前登入的操作員資訊
    """

    cameras = (
        Camera.objects
        .filter(is_active=True)
        .order_by("camera_code")
    )

    context = {
        "page_title": "KRTC AI CCTV Monitor Wall",
        "cameras": cameras,
    }

    return render(request, "dashboard/monitor.html", context)