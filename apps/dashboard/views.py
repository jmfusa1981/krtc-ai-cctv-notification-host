from django.shortcuts import render
from apps.cameras.models import Camera
from apps.events.models import Event, CrowdFlowRecord, CrowdFlowSetting


def dashboard_home(request):
    cameras = Camera.objects.all().order_by("id")

    latest_events = (
        Event.objects.select_related("camera", "ai_model")
        .all()
        .order_by("-detected_at", "-created_at")[:8]
    )

    latest_crowd_records = (
        CrowdFlowRecord.objects.select_related("camera")
        .all()
        .order_by("-recorded_at", "-created_at")[:8]
    )

    active_crowd_settings = (
        CrowdFlowSetting.objects.select_related("camera")
        .filter(is_active=True)
        .order_by("id")
    )

    latest_crowd_record = (
        CrowdFlowRecord.objects.select_related("camera")
        .all()
        .order_by("-recorded_at", "-created_at")
        .first()
    )

    camera_count = cameras.count()
    event_count = Event.objects.count()
    new_event_count = Event.objects.filter(status="new").count()
    abnormal_crowd_count = CrowdFlowRecord.objects.filter(is_abnormal=True).count()

    # For first-stage monitoring layout, show up to 4 camera tiles.
    camera_tiles = cameras[:4]

    context = {
        "cameras": cameras,
        "camera_tiles": camera_tiles,
        "latest_events": latest_events,
        "latest_crowd_records": latest_crowd_records,
        "active_crowd_settings": active_crowd_settings,
        "latest_crowd_record": latest_crowd_record,
        "camera_count": camera_count,
        "event_count": event_count,
        "new_event_count": new_event_count,
        "abnormal_crowd_count": abnormal_crowd_count,
    }

    return render(request, "dashboard/dashboard.html", context)