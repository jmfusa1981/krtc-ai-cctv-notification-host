import os
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.events.models import Event


def _safe_local_path(name):
    media_root = Path(settings.MEDIA_ROOT).resolve()
    if not name:
        return None
    try:
        path = (media_root / str(name)).resolve()
        path.relative_to(media_root)
    except (OSError, RuntimeError, ValueError):
        return None
    return path


def _delete_local_file(name):
    path = _safe_local_path(name)
    if path is None or not path.is_file():
        return False
    try:
        path.unlink()
    except OSError:
        return False
    return True


def prune_expired_event_media(*, now=None, batch_size=None):
    """刪除逾期本機媒體但保留事件與錄影證據的稽核資料。"""
    now = now or timezone.now()
    retention_days = max(1, int(getattr(settings, "KRTC_EVENT_MEDIA_RETENTION_DAYS", 30)))
    batch_size = max(
        1,
        int(batch_size or getattr(settings, "KRTC_EVENT_MEDIA_RETENTION_BATCH_SIZE", 100)),
    )
    cutoff = now - timedelta(days=retention_days)
    event_ids = list(
        Event.objects.filter(detected_at__lt=cutoff)
        .filter(Q(snapshot__gt="") | Q(recording_evidences__file__gt=""))
        .distinct()
        .order_by("id")
        .values_list("id", flat=True)[:batch_size]
    )
    events_processed = snapshots_deleted = videos_deleted = 0

    for event in Event.objects.filter(pk__in=event_ids).prefetch_related("recording_evidences"):
        local_video_urls = set()
        with transaction.atomic():
            if event.snapshot and event.snapshot.name:
                _delete_local_file(event.snapshot.name)
                event.snapshot = None
                event.save(update_fields=["snapshot", "updated_at"])
                snapshots_deleted += 1

            for evidence in event.recording_evidences.all():
                if not evidence.file or not evidence.file.name:
                    continue
                try:
                    local_video_urls.add(evidence.file.url)
                except (AttributeError, ValueError):
                    pass
                _delete_local_file(evidence.file.name)
                evidence.file = ""
                evidence.save(update_fields=["file", "updated_at"])
                videos_deleted += 1

            if event.video_url and event.video_url in local_video_urls:
                event.video_url = ""
                event.save(update_fields=["video_url", "updated_at"])
        events_processed += 1

    partial_deleted = prune_stale_partial_files(now=now, limit=batch_size)
    return {
        "events_processed": events_processed,
        "snapshots_deleted": snapshots_deleted,
        "videos_deleted": videos_deleted,
        "partial_deleted": partial_deleted,
    }


def prune_stale_partial_files(*, now=None, limit=100):
    """清除超過一天且仍位於受控暫存目錄的未完成下載。"""
    now = now or timezone.now()
    partial_dir = _safe_local_path("event_recordings/.partial")
    if partial_dir is None or not partial_dir.is_dir():
        return 0
    cutoff_timestamp = (now - timedelta(days=1)).timestamp()
    deleted = 0
    for path in partial_dir.iterdir():
        if deleted >= max(1, int(limit)):
            break
        try:
            resolved = path.resolve()
            resolved.relative_to(partial_dir.resolve())
            if resolved.is_file() and resolved.stat().st_mtime < cutoff_timestamp:
                resolved.unlink()
                deleted += 1
        except (OSError, RuntimeError, ValueError):
            continue
    return deleted


def run_daily_media_retention(*, now=None):
    """以持久日期標記確保服務重啟後同一天不重複執行完整清理。"""
    now = now or timezone.now()
    media_root = Path(settings.MEDIA_ROOT).resolve()
    media_root.mkdir(parents=True, exist_ok=True)
    marker = media_root / ".event_media_retention_date"
    today = timezone.localtime(now).date().isoformat()
    try:
        if marker.read_text(encoding="ascii").strip() == today:
            return None
    except (OSError, UnicodeError):
        pass

    result = prune_expired_event_media(now=now)
    temporary_marker = marker.with_suffix(".tmp")
    temporary_marker.write_text(today, encoding="ascii")
    os.replace(temporary_marker, marker)
    return result
