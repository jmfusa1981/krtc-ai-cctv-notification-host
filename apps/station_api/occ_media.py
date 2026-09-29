from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from apps.events.models import EventRecordingEvidence
from apps.settings_app.models import StationLocalSettings
from apps.station_api.media import resolve_recording


def local_occ_upload_candidates(*, now=None, limit=100):
    """只建立最近七日的本機上傳候選；本函式不發送任何網路請求。"""
    now = now or timezone.now()
    cutoff = now - timedelta(days=7)
    local = StationLocalSettings.load()
    identity = {
        "station_code": settings.KRTC_STATION_CODE or local.station_code,
        "notification_host_code": settings.KRTC_NOTIFICATION_HOST_CODE,
    }
    rows = (
        EventRecordingEvidence.objects.select_related("event")
        .filter(
            export_status=EventRecordingEvidence.STATUS_COMPLETED,
            event__detected_at__gte=cutoff,
            file__gt="",
        )
        .order_by("event__detected_at", "id")[:max(1, min(int(limit), 500))]
    )
    candidates = []
    for evidence in rows:
        if resolve_recording(evidence) is None:
            continue
        candidates.append({
            **identity,
            "pao_event_id": evidence.event_id,
            "event_id": evidence.event.event_id,
            "source_event_id": evidence.event.source_event_id,
            "recording_evidence_id": evidence.id,
            "local_file_name": evidence.file.name,
        })
    return candidates
