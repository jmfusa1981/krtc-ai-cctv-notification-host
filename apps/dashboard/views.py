from django.shortcuts import render

from apps.cameras.models import Camera
from apps.events.models import Event, CrowdFlowSetting, CrowdFlowRecord


def dashboard_home(request):
    """
    KRTC AI CCTV 通報主機 Dashboard

    功能：
    1. 顯示啟用中的攝影機資料
    2. 顯示近期 AI 事件
    3. 顯示人流統計設定
    4. 顯示近期人流統計紀錄
    """

    cameras = Camera.objects.filter(is_active=True).order_by("camera_code")

    recent_events = Event.objects.all().order_by("-created_at")[:10]

    crowd_flow_settings = CrowdFlowSetting.objects.filter(is_active=True).order_by("name")

    crowd_flow_records = CrowdFlowRecord.objects.all().order_by("-created_at")[:10]

    context = {
        "cameras": cameras,
        "recent_events": recent_events,
        "crowd_flow_settings": crowd_flow_settings,
        "crowd_flow_records": crowd_flow_records,
    }

    return render(request, "dashboard/index.html", context)


def monitor_wall(request):
    """
    KRTC AI CCTV 純影像監控牆

    功能：
    1. 只顯示啟用中的攝影機
    2. 支援 1 / 4 / 9 / 16 分割畫面
    3. 提供返回 Dashboard 的操作
    """

    cameras = Camera.objects.filter(is_active=True).order_by("camera_code")

    context = {
        "cameras": cameras,
    }

    return render(request, "dashboard/monitor.html", context)