import logging
import threading
import time
from datetime import timedelta

from django.conf import settings
from django.db import close_old_connections
from django.utils import timezone

from apps.events.models import Event, EventRecordingEvidence
from apps.events.services.media_retention import run_daily_media_retention
from apps.events.services.nvr_recording import (
    NvrRecordingError,
    download_completed_export,
    enqueue_recording_evidence,
    redact_nvr_error,
    refresh_export_status,
    request_export,
)


logger = logging.getLogger(__name__)


def _deadline_exceeded(evidence, now):
    if evidence.requested_at is None:
        return False
    timeout = max(1, int(getattr(settings, "KRTC_NVR_EXPORT_TIMEOUT_SECONDS", 7200)))
    return evidence.requested_at + timedelta(seconds=timeout) <= now


def _poll_due(evidence, now):
    if evidence.next_poll_at is not None:
        return evidence.next_poll_at <= now
    interval = max(1, int(getattr(settings, "KRTC_NVR_POLL_INTERVAL_SECONDS", 60)))
    return evidence.updated_at + timedelta(seconds=interval) <= now


def _warning_due(evidence, now):
    if evidence.requested_at is None or evidence.warning_issued_at is not None:
        return False
    threshold = max(
        1,
        int(getattr(settings, "KRTC_NVR_EXPORT_WARNING_SECONDS", 3600)),
    )
    return evidence.requested_at + timedelta(seconds=threshold) <= now


def _ready_for_download(evidence):
    """相容重啟前已記錄 Status=1、但尚未轉為 ready 的舊工作。"""

    if evidence.export_status in {
        EventRecordingEvidence.STATUS_READY,
        EventRecordingEvidence.STATUS_DOWNLOADING,
    }:
        return True
    payload = evidence.response_payload if isinstance(evidence.response_payload, dict) else {}
    try:
        return int(payload.get("Status", 0)) == 1
    except (TypeError, ValueError):
        return False


def process_recording_cycle(*, now=None):
    """每筆證據每輪最多執行一次 NVR 動作，並以資料庫狀態支援重啟。"""
    now = now or timezone.now()
    batch_size = max(1, int(getattr(settings, "KRTC_NVR_WORKER_BATCH_SIZE", 20)))
    processed = created = failed = 0

    evidences = list(
        EventRecordingEvidence.objects.select_related("event", "event__camera")
        .filter(
            export_status__in=[
                EventRecordingEvidence.STATUS_PENDING,
                EventRecordingEvidence.STATUS_REQUESTED,
                EventRecordingEvidence.STATUS_EXPORTING,
                EventRecordingEvidence.STATUS_READY,
                EventRecordingEvidence.STATUS_DOWNLOADING,
            ]
        )
        .order_by("updated_at", "id")[:batch_size]
    )
    for evidence in evidences:
        if _deadline_exceeded(evidence, now):
            evidence.export_status = EventRecordingEvidence.STATUS_EXPIRED
            evidence.last_error = "NVR 匯出已超過允許等待時間。"
            evidence.save(update_fields=["export_status", "last_error", "updated_at"])
            failed += 1
            continue
        if not _poll_due(evidence, now):
            continue
        if _warning_due(evidence, now):
            evidence.warning_issued_at = now
            evidence.save(update_fields=["warning_issued_at", "updated_at"])
            logger.warning(
                "NVR export remains unfinished after warning threshold evidence=%s",
                evidence.pk,
            )
        try:
            if evidence.export_status == EventRecordingEvidence.STATUS_PENDING:
                request_export(evidence)
            elif _ready_for_download(evidence):
                download_completed_export(evidence)
            else:
                refreshed = refresh_export_status(evidence)
                if refreshed.export_status == EventRecordingEvidence.STATUS_READY:
                    download_completed_export(refreshed)
        except NvrRecordingError as exc:
            evidence.export_status = EventRecordingEvidence.STATUS_FAILED
            evidence.last_error = redact_nvr_error(exc)
            evidence.save(update_fields=["export_status", "last_error", "updated_at"])
            logger.warning(
                "NVR evidence action failed evidence=%s error=%s",
                evidence.pk,
                evidence.last_error,
            )
        processed += 1

    remaining = max(0, batch_size - processed)
    if remaining:
        cutoff = now - timedelta(
            days=max(1, int(getattr(settings, "KRTC_EVENT_MEDIA_RETENTION_DAYS", 30)))
        )
        candidates = Event.objects.select_related("camera").filter(
            detected_at__gte=cutoff,
            camera__isnull=False,
            camera__nvr_recording_enabled=True,
            camera__nvr_channel__isnull=False,
        )
        if not str(getattr(settings, "KRTC_NVR_DEFAULT_HOST", "") or "").strip():
            candidates = candidates.exclude(camera__nvr_host="")
        if not str(getattr(settings, "KRTC_NVR_DEFAULT_USERNAME", "") or "").strip():
            candidates = candidates.exclude(camera__nvr_username="")
        candidates = (
            candidates
            .exclude(recording_evidences__isnull=False)
            .order_by("detected_at", "id")[:remaining]
        )
        for event in candidates:
            if event.recording_evidences.exists():
                continue
            try:
                enqueue_recording_evidence(event)
                created += 1
            except NvrRecordingError as exc:
                logger.warning(
                    "NVR evidence creation skipped event=%s error=%s",
                    event.pk,
                    redact_nvr_error(exc),
                )

    return {"processed": processed, "created": created, "failed": failed}


class RecordingWorker:
    def __init__(self, stop_event=None, monotonic=time.monotonic):
        self.stop_event = stop_event or threading.Event()
        self.monotonic = monotonic

    def run_cycle(self):
        close_old_connections()
        try:
            result = process_recording_cycle()
            retention = run_daily_media_retention()
            if retention is not None:
                result["retention"] = retention
            return result
        finally:
            close_old_connections()

    def run(self):
        interval = max(1, int(getattr(settings, "KRTC_NVR_POLL_INTERVAL_SECONDS", 60)))
        while not self.stop_event.is_set():
            try:
                self.run_cycle()
            except Exception:
                logger.exception("NVR recording worker cycle failed")
            if self.stop_event.wait(interval):
                break
