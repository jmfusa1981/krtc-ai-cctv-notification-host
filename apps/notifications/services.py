import hashlib
import json
import subprocess
import sys
import threading
import time
import wave
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.db import IntegrityError, OperationalError, close_old_connections, transaction
from django.utils import timezone

from .backends.pjsip import (
    PjsipPreflightError,
    execute_pjsip_playback_plan,
)
from .models import BroadcastLog, SpeakerDevice
from .pjsip_readiness import prepare_pjsip_readiness
from .runtime_config import get_broadcast_runtime_config


DEFAULT_PLAYBACK_MODE = "simulation"

PLAYBACK_MODE_SIMULATION = "simulation"
PLAYBACK_MODE_PJSIP = "pjsip"
PLAYBACK_MODE_MICROSIP_WINSOUND = "microsip_winsound"

DEFAULT_PLAY_AFTER_DIAL_DELAY_SECONDS = 1
DEFAULT_HANGUP_AFTER_AUDIO_MARGIN_SECONDS = 2

SOURCE_LIVE_MICROPHONE = "live_microphone"
SOURCE_BROADCAST_SCHEDULE = "broadcast_schedule"
SOURCE_PRIORITY_LIVE = 0
SOURCE_PRIORITY_WARNING = 50
SOURCE_PRIORITY_SCHEDULE = 100
SCHEDULE_RETRY_DELAY_SECONDS = 30
STALE_SCHEDULE_LOCK_SECONDS = 900
SQLITE_WRITE_RETRY_ATTEMPTS = 8
SQLITE_WRITE_RETRY_DELAY_SECONDS = 0.05

# SQLite permits multiple readers but only one writer. PJSIP playback remains
# parallel; only the short BroadcastLog state transitions are serialized.
_broadcast_db_write_lock = threading.RLock()


def _run_broadcast_db_write(operation):
    last_error = None
    with _broadcast_db_write_lock:
        for attempt in range(SQLITE_WRITE_RETRY_ATTEMPTS):
            try:
                with transaction.atomic():
                    return operation()
            except OperationalError as exc:
                if "locked" not in str(exc).lower():
                    raise
                last_error = exc
                if attempt + 1 < SQLITE_WRITE_RETRY_ATTEMPTS:
                    time.sleep(
                        SQLITE_WRITE_RETRY_DELAY_SECONDS * (attempt + 1)
                    )
    raise last_error


def get_broadcast_queue_cooldown_seconds():
    """取得等價事件的 queue 去重秒數。"""

    value = getattr(settings, "BROADCAST_QUEUE_COOLDOWN_SECONDS", 30)
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 30


def get_broadcast_queue_ttl_seconds():
    """取得尚未開始播放工作的存活秒數。"""

    value = getattr(settings, "BROADCAST_QUEUE_TTL_SECONDS", 120)
    try:
        return max(1, int(value))
    except (TypeError, ValueError):
        return 120


def build_broadcast_dedup_key(
    *,
    rule_id,
    speaker_id,
    event_source,
    event_type,
):
    """依規則、Speaker、事件來源與類型建立穩定去重鍵。"""

    identity = {
        "event_source": str(event_source or ""),
        "event_type": str(event_type or ""),
        "rule_id": str(rule_id or ""),
        "speaker_id": str(speaker_id or ""),
    }
    encoded = json.dumps(
        identity,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def enqueue_broadcast_log(
    *,
    speaker,
    audio_file,
    event=None,
    rule=None,
    request_payload=None,
    message="Broadcast queued.",
    queue_priority=100,
    dedup_key="",
    cooldown_seconds=None,
    ttl_seconds=None,
    requested_at=None,
):
    """建立持久化 Speaker 工作；等價事件在 cooldown 內記為 suppressed。"""

    now = requested_at or timezone.now()
    cooldown_seconds = (
        get_broadcast_queue_cooldown_seconds()
        if cooldown_seconds is None
        else max(0, int(cooldown_seconds))
    )
    ttl_seconds = (
        get_broadcast_queue_ttl_seconds()
        if ttl_seconds is None
        else max(1, int(ttl_seconds))
    )

    def _enqueue():
        suppressed = False
        if dedup_key and cooldown_seconds:
            cutoff = now - timedelta(seconds=cooldown_seconds)
            suppressed = BroadcastLog.objects.filter(
                dedup_key=dedup_key,
                created_at__gte=cutoff,
            ).exclude(
                status__in=[
                    BroadcastLog.STATUS_FAILED,
                    BroadcastLog.STATUS_EXPIRED,
                    BroadcastLog.STATUS_CANCELLED,
                ]
            ).exists()

        status = (
            BroadcastLog.STATUS_SUPPRESSED
            if suppressed
            else BroadcastLog.STATUS_QUEUED
        )
        payload = dict(request_payload or {})
        payload.update(
            {
                "queue_priority": int(queue_priority),
                "queue_ttl_seconds": ttl_seconds,
                "dedup_key": dedup_key,
            }
        )
        log = BroadcastLog.objects.create(
            event=event,
            rule=rule,
            speaker=speaker,
            audio_file=audio_file,
            status=status,
            queue_priority=max(0, int(queue_priority)),
            dedup_key=dedup_key,
            expires_at=now + timedelta(seconds=ttl_seconds),
            request_payload=payload,
            response_payload=(
                {
                    "success": False,
                    "reason": "duplicate_within_cooldown",
                    "cooldown_seconds": cooldown_seconds,
                }
                if suppressed
                else None
            ),
            message=(
                "Equivalent broadcast suppressed inside cooldown window."
                if suppressed
                else message
            ),
            requested_at=now,
            finished_at=now if suppressed else None,
        )
        return log, not suppressed

    return _run_broadcast_db_write(_enqueue)


def expire_stale_queued_broadcasts(*, speaker_ids=None, now=None):
    """將超過 TTL 的 queued 工作標記為 expired，且不呼叫播放後端。"""

    now = now or timezone.now()
    queryset = BroadcastLog.objects.filter(
        status=BroadcastLog.STATUS_QUEUED,
        expires_at__isnull=False,
        expires_at__lte=now,
    )
    if speaker_ids is not None:
        queryset = queryset.filter(speaker_id__in=list(speaker_ids))
    return queryset.update(
        status=BroadcastLog.STATUS_EXPIRED,
        finished_at=now,
        message="Queued broadcast expired before playback.",
        response_payload={"success": False, "reason": "queue_ttl_expired"},
        updated_at=now,
    )

DEFAULT_MICROSIP_PATHS = [
    r"C:\Users\user\Desktop\MicroSIP.lnk",
    r"C:\Users\user\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\MicroSIP\MicroSIP.lnk",
    r"C:\Users\user\AppData\Local\MicroSIP\MicroSIP.exe",
    r"C:\Program Files\MicroSIP\microsip.exe",
    r"C:\Program Files (x86)\MicroSIP\microsip.exe",
]


def process_pending_broadcast_logs(limit=10):
    """
    處理 pending BroadcastLog。

    Step 20-3 支援兩種模式：

    1. simulation
       不實際呼叫 IP Speaker。
       用於 Dashboard / API 流程測試。

    2. microsip_winsound
       使用 Windows SIP URI 呼叫 MicroSIP 撥號，
       再用 winsound 播放本機 wav 音檔，
       播放完成後嘗試自動掛斷 MicroSIP。

    settings.py 可設定：
    BROADCAST_PLAYBACK_MODE = "simulation"
    或
    BROADCAST_PLAYBACK_MODE = "microsip_winsound"
    """

    return process_queued_broadcasts(limit=limit)


def process_broadcast_logs_for_event(event_id, *, limit=10, max_workers=4):
    """以 Speaker 為單位處理事件建立的 queued 廣播工作。"""

    speaker_ids = list(
        BroadcastLog.objects.filter(
            event_id=event_id,
            status__in=BroadcastLog.QUEUED_STATUSES,
            speaker__isnull=False,
        ).values_list("speaker_id", flat=True).distinct()
    )
    return process_queued_broadcasts(
        speaker_ids=speaker_ids,
        limit=limit,
        max_workers=max_workers,
    )


def process_speaker_queue(speaker_id, *, limit=100):
    """循序清空單一 Speaker queue；同一時間只允許一筆 playing。"""

    results = []
    processed_count = 0
    lock_retry_count = 0
    max_lock_retries = SQLITE_WRITE_RETRY_ATTEMPTS * 4
    while processed_count < max(1, int(limit)):
        try:
            expire_stale_queued_broadcasts(speaker_ids=[speaker_id])
            log = (
                BroadcastLog.objects
                .select_related("event", "event__camera", "rule", "speaker", "audio_file")
                .filter(
                    speaker_id=speaker_id,
                    status__in=BroadcastLog.QUEUED_STATUSES,
                )
                .order_by("queue_priority", "created_at", "pk")
                .first()
            )
            if log is None:
                break

            result = process_single_broadcast_log(log)
            results.append(result)
            processed_count += 1
            lock_retry_count = 0
            if result.get("status") in BroadcastLog.QUEUED_STATUSES:
                break
        except OperationalError as exc:
            if "locked" not in str(exc).lower():
                raise
            lock_retry_count += 1
            if lock_retry_count >= max_lock_retries:
                raise
            close_old_connections()
            time.sleep(SQLITE_WRITE_RETRY_DELAY_SECONDS * lock_retry_count)

    return results


def process_queued_broadcasts(*, speaker_ids=None, limit=100, max_workers=None):
    """平行處理不同 Speaker，並讓各 Speaker 內部依 priority/時間循序執行。"""

    expire_stale_queued_broadcasts(speaker_ids=speaker_ids)
    queryset = BroadcastLog.objects.filter(
        status__in=BroadcastLog.QUEUED_STATUSES,
        speaker__isnull=False,
    )
    if speaker_ids is not None:
        queryset = queryset.filter(speaker_id__in=list(speaker_ids))
    ordered_speaker_ids = list(
        dict.fromkeys(
            queryset.order_by("queue_priority", "created_at", "pk")
            .values_list("speaker_id", flat=True)
        )
    )
    if not ordered_speaker_ids:
        return _broadcast_result_summary([])

    worker_count = min(
        len(ordered_speaker_ids),
        max(
            1,
            int(
                max_workers
                or getattr(settings, "BROADCAST_QUEUE_MAX_WORKERS", 4)
            ),
        ),
    )
    per_speaker_limit = max(1, int(limit))

    def _worker(target_speaker_id):
        close_old_connections()
        try:
            return process_speaker_queue(
                target_speaker_id,
                limit=per_speaker_limit,
            )
        finally:
            close_old_connections()

    results = []
    if len(ordered_speaker_ids) == 1:
        results.extend(_worker(ordered_speaker_ids[0]))
    else:
        with ThreadPoolExecutor(
            max_workers=worker_count,
            thread_name_prefix="krtc-speaker-queue",
        ) as executor:
            futures = {
                executor.submit(_worker, speaker_id): speaker_id
                for speaker_id in ordered_speaker_ids
            }
            for future in as_completed(futures):
                speaker_id = futures[future]
                try:
                    results.extend(future.result())
                except Exception as exc:
                    results.append(
                        {
                            "speaker_id": speaker_id,
                            "status": BroadcastLog.STATUS_FAILED,
                            "message": f"Speaker queue worker failed: {exc}",
                        }
                    )
    return _broadcast_result_summary(results)


def _broadcast_result_summary(results):
    return {
        "processed_count": len(results),
        "success_count": sum(
            1 for item in results
            if item.get("status") == BroadcastLog.STATUS_SUCCESS
        ),
        "failed_count": sum(
            1 for item in results
            if item.get("status") == BroadcastLog.STATUS_FAILED
        ),
        "skipped_count": sum(
            1 for item in results
            if item.get("status") == BroadcastLog.STATUS_SKIPPED
        ),
        "expired_count": sum(
            1 for item in results
            if item.get("status") == BroadcastLog.STATUS_EXPIRED
        ),
        "queued_count": sum(
            1 for item in results
            if item.get("status") in BroadcastLog.QUEUED_STATUSES
        ),
        "results": results,
    }


def process_broadcast_logs_for_event_async(event_id):
    """Start a non-blocking worker after the event transaction commits."""

    thread = threading.Thread(
        target=_process_broadcast_logs_for_event_worker,
        args=(event_id,),
        name=f"krtc-auto-broadcast-event-{event_id}",
        daemon=False,
    )
    thread.start()
    return thread


def _process_broadcast_logs_for_event_worker(event_id):
    close_old_connections()
    try:
        process_broadcast_logs_for_event(
            event_id,
            limit=int(getattr(settings, "AUTO_BROADCAST_EVENT_LOG_LIMIT", 10)),
            max_workers=int(getattr(settings, "AUTO_BROADCAST_MAX_WORKERS", 4)),
        )
    finally:
        close_old_connections()


def broadcast_log_source(log):
    return str((log.request_payload or {}).get("source") or "")


def broadcast_log_priority(log):
    return int(getattr(log, "queue_priority", SOURCE_PRIORITY_WARNING))


def active_broadcast_logs_for_speakers(speakers):
    return list(
        BroadcastLog.objects.filter(
            speaker__in=list(speakers),
            status__in=BroadcastLog.ACTIVE_STATUSES,
        ).select_related("speaker")
    )


def interrupt_lower_priority_broadcasts(speakers, minimum_priority, reason):
    now = timezone.now()
    interrupted = []
    for log in active_broadcast_logs_for_speakers(speakers):
        if broadcast_log_priority(log) <= minimum_priority:
            continue
        if log.status == BroadcastLog.STATUS_PLAYING:
            stop_pjsua_process_for_broadcast_log(log)
        payload = dict(log.response_payload or {})
        payload.update(
            {
                "interrupted_by_priority": minimum_priority,
                "interrupt_reason": reason,
                "interrupted_at": now.isoformat(),
            }
        )
        log.status = BroadcastLog.STATUS_CANCELLED
        log.finished_at = now
        log.message = f"Broadcast interrupted by higher priority request: {reason}"
        log.response_payload = payload
        log.save(update_fields=["status", "finished_at", "message", "response_payload", "updated_at"])
        reschedule_interrupted_schedule_log(log, now)
        interrupted.append(log)
    return interrupted


def reset_all_speaker_workflows(reason="manual_workflow_reset"):
    now = timezone.now()
    reset_logs = []
    active_logs = (
        BroadcastLog.objects.filter(
            speaker__isnull=False,
            status__in=BroadcastLog.ACTIVE_STATUSES,
        )
        .select_related("speaker")
        .order_by("created_at")
    )

    for log in active_logs:
        pjsua_stopped = False
        if log.status == BroadcastLog.STATUS_PLAYING:
            pjsua_stopped = stop_pjsua_process_for_broadcast_log(log)

        payload = dict(log.response_payload or {})
        payload.update(
            {
                "source": broadcast_log_source(log) or "unknown",
                "end_reason": reason,
                "cleared_at": now.isoformat(),
                "pjsua_stopped": pjsua_stopped,
            }
        )
        log.status = BroadcastLog.STATUS_CANCELLED
        log.finished_at = now
        log.message = "手動清除 Speaker 工作流，已解除忙碌狀態。"
        log.response_payload = payload
        log.save(update_fields=["status", "finished_at", "message", "response_payload", "updated_at"])
        reschedule_interrupted_schedule_log(log, now)
        reset_logs.append(log)

    return {
        "cleared_count": len(reset_logs),
        "cleared_logs": [
            {
                "id": log.id,
                "speaker_code": log.speaker.speaker_code if log.speaker else None,
                "source": broadcast_log_source(log),
            }
            for log in reset_logs
        ],
    }


def stop_pjsua_process_for_broadcast_log(log):
    if not log.speaker:
        return False
    marker = str(Path(settings.PJSIP_LOG_DIR) / f"dashboard_broadcast_{log.id}_{log.speaker.speaker_code}.log")
    try:
        result = subprocess.run(
            [
                "wmic",
                "process",
                "where",
                "name='pjsua.exe'",
                "get",
                "ProcessId,CommandLine",
                "/format:csv",
            ],
            capture_output=True,
            text=True,
            timeout=5,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except Exception:
        return False
    if result.returncode != 0:
        return False
    stopped = False
    for line in result.stdout.splitlines():
        if marker not in line:
            continue
        pid = line.rsplit(",", 1)[-1].strip()
        if not pid.isdigit():
            continue
        subprocess.run(
            ["taskkill", "/PID", pid, "/T", "/F"],
            capture_output=True,
            text=True,
            timeout=5,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        stopped = True
    return stopped


def clear_stale_schedule_broadcast_locks():
    now = timezone.now()
    cutoff = now - timedelta(seconds=STALE_SCHEDULE_LOCK_SECONDS)
    cleared = []
    stale_logs = BroadcastLog.objects.filter(
        status__in=[BroadcastLog.STATUS_PENDING, BroadcastLog.STATUS_PLAYING],
        request_payload__source=SOURCE_BROADCAST_SCHEDULE,
        requested_at__lte=cutoff,
    ).select_related("speaker")
    for log in stale_logs:
        if log.status == BroadcastLog.STATUS_PLAYING:
            stop_pjsua_process_for_broadcast_log(log)
        payload = dict(log.response_payload or {})
        payload.update(
            {
                "source": SOURCE_BROADCAST_SCHEDULE,
                "end_reason": "stale_schedule_lock",
                "cleared_at": now.isoformat(),
            }
        )
        log.status = BroadcastLog.STATUS_FAILED
        log.finished_at = now
        log.message = "排程廣播逾時未完成，已自動解除 Speaker 忙碌狀態。"
        log.response_payload = payload
        log.save(update_fields=["status", "finished_at", "message", "response_payload", "updated_at"])
        reschedule_interrupted_schedule_log(log, now)
        cleared.append(log)
    return cleared


def reschedule_interrupted_schedule_log(log, now=None):
    payload = log.request_payload or {}
    schedule_id = payload.get("schedule_id")
    if broadcast_log_source(log) != SOURCE_BROADCAST_SCHEDULE or not schedule_id:
        return False

    from .models import BroadcastSchedule

    schedule = BroadcastSchedule.objects.filter(pk=schedule_id).first()
    if not schedule:
        return False
    retry_at = (now or timezone.now()) + timedelta(seconds=SCHEDULE_RETRY_DELAY_SECONDS)
    schedule.is_active = True
    schedule.next_run_at = retry_at
    schedule.save(update_fields=["is_active", "next_run_at", "updated_at"])
    return True


def process_single_broadcast_log(log):
    """
    處理單一 BroadcastLog。

    注意：
    真實播放音檔可能需要數秒，因此不要把整個播放流程包在 transaction 裡。

    流程：
    1. transaction 內鎖定資料，檢查資料完整性，標記為 playing。
    2. transaction 外執行播放。
    3. 播放完成後回寫 success / failed。
    """

    prepare_result = prepare_broadcast_log_for_playback(log)

    if not prepare_result["success"]:
        return prepare_result["result"]

    log_id = prepare_result["broadcast_log_id"]

    log = _run_broadcast_db_write(
        lambda: (
            BroadcastLog.objects
            .select_related("event", "event__camera", "rule", "speaker", "audio_file")
            .get(id=log_id)
        )
    )

    speaker = log.speaker
    audio_file = log.audio_file

    playback_result = play_audio_to_speaker(
        speaker=speaker,
        audio_file=audio_file,
        broadcast_log=log,
    )

    log = _run_broadcast_db_write(
        lambda: (
            BroadcastLog.objects
            .select_related("speaker", "audio_file")
            .get(pk=log_id)
        )
    )
    if log.status != BroadcastLog.STATUS_PLAYING:
        return {
            "broadcast_log_id": log.id,
            "status": log.status,
            "message": log.message,
            "speaker_code": log.speaker.speaker_code if log.speaker else "",
            "audio_code": log.audio_file.audio_code if log.audio_file else "",
        }

    if playback_result.get("success"):
        return mark_broadcast_success(
            log=log,
            message=playback_result.get(
                "message",
                "Playback completed successfully.",
            ),
            response_payload=playback_result,
        )

    return mark_broadcast_failed(
        log=log,
        message=playback_result.get(
            "message",
            "Playback failed.",
        ),
        response_payload=playback_result,
    )


def prepare_broadcast_log_for_playback(log):
    """
    鎖定 BroadcastLog，檢查資料完整性，並標記為 playing。
    """

    log_id = log.id

    def _prepare():
        current_log = (
            BroadcastLog.objects
            .select_for_update()
            .select_related("event", "event__camera", "rule", "speaker", "audio_file")
            .get(id=log_id)
        )

        if current_log.status not in BroadcastLog.QUEUED_STATUSES:
            return {
                "success": False,
                "result": {
                    "broadcast_log_id": current_log.id,
                    "status": current_log.status,
                    "message": "BroadcastLog is not queued.",
                },
            }

        if current_log.speaker is None:
            current_log.status = BroadcastLog.STATUS_FAILED
            current_log.finished_at = timezone.now()
            current_log.message = "SpeakerDevice is missing."
            current_log.response_payload = {
                "success": False,
                "reason": "speaker_missing",
            }
            current_log.save(
                update_fields=[
                    "status", "finished_at", "message",
                    "response_payload", "updated_at",
                ]
            )

            return {
                "success": False,
                "result": {
                    "broadcast_log_id": current_log.id,
                    "status": current_log.status,
                    "message": current_log.message,
                    "speaker_code": "",
                    "audio_code": "",
                },
            }

        now = timezone.now()
        if current_log.expires_at and current_log.expires_at <= now:
            current_log.status = BroadcastLog.STATUS_EXPIRED
            current_log.finished_at = now
            current_log.message = "Queued broadcast expired before playback."
            current_log.response_payload = {
                "success": False,
                "reason": "queue_ttl_expired",
            }
            current_log.save(
                update_fields=[
                    "status",
                    "finished_at",
                    "message",
                    "response_payload",
                    "updated_at",
                ]
            )
            return {
                "success": False,
                "result": {
                    "broadcast_log_id": current_log.id,
                    "status": current_log.status,
                    "message": current_log.message,
                },
            }

        speaker_playing = BroadcastLog.objects.filter(
            speaker_id=current_log.speaker_id,
            status=BroadcastLog.STATUS_PLAYING,
        ).exclude(pk=current_log.pk).exists()
        if speaker_playing:
            if current_log.status != BroadcastLog.STATUS_QUEUED:
                current_log.status = BroadcastLog.STATUS_QUEUED
                current_log.save(update_fields=["status", "updated_at"])
            return {
                "success": False,
                "result": {
                    "broadcast_log_id": current_log.id,
                    "status": BroadcastLog.STATUS_QUEUED,
                    "message": "Speaker is busy; broadcast remains queued.",
                    "reason": "speaker_busy_queued",
                },
            }

        next_log_id = (
            BroadcastLog.objects.filter(
                speaker_id=current_log.speaker_id,
                status__in=BroadcastLog.QUEUED_STATUSES,
            )
            .order_by("queue_priority", "created_at", "pk")
            .values_list("pk", flat=True)
            .first()
        )
        if next_log_id != current_log.pk:
            return {
                "success": False,
                "result": {
                    "broadcast_log_id": current_log.id,
                    "status": current_log.status,
                    "message": "A higher-priority broadcast is ahead in the Speaker queue.",
                    "reason": "waiting_for_queue_priority",
                },
            }

        if current_log.audio_file is None:
            current_log.status = BroadcastLog.STATUS_FAILED
            current_log.finished_at = timezone.now()
            current_log.message = "AudioFile is missing."
            current_log.response_payload = {
                "success": False,
                "reason": "audio_file_missing",
            }
            current_log.save(
                update_fields=[
                    "status", "finished_at", "message",
                    "response_payload", "updated_at",
                ]
            )

            return {
                "success": False,
                "result": {
                    "broadcast_log_id": current_log.id,
                    "status": current_log.status,
                    "message": current_log.message,
                    "speaker_code": (
                        current_log.speaker.speaker_code
                        if current_log.speaker else ""
                    ),
                    "audio_code": "",
                },
            }

        # Re-read the mutable playback resources at the execution boundary.
        # A BroadcastLog may have been queued while a speaker was online and
        # processed after the device was disabled or marked offline.
        speaker = SpeakerDevice.objects.get(pk=current_log.speaker_id)
        audio_file = type(current_log.audio_file).objects.get(
            pk=current_log.audio_file_id
        )

        if not speaker.is_active:
            return _fail_prepared_broadcast(
                current_log,
                reason="speaker_inactive",
                message=(
                    f"Playback blocked: SpeakerDevice {speaker.speaker_code} "
                    "is inactive."
                ),
            )

        if speaker.status != SpeakerDevice.STATUS_ONLINE:
            return _fail_prepared_broadcast(
                current_log,
                reason="speaker_offline",
                message=(
                    f"Playback blocked: SpeakerDevice {speaker.speaker_code} "
                    f"status is {speaker.status}."
                ),
                extra_payload={"speaker_status": speaker.status},
            )

        if not audio_file.is_active:
            return _fail_prepared_broadcast(
                current_log,
                reason="audio_file_inactive",
                message=(
                    f"Playback blocked: AudioFile {audio_file.audio_code} "
                    "is inactive."
                ),
            )

        playback_mode = get_broadcast_playback_mode()

        request_payload = build_request_payload(
            playback_mode=playback_mode,
            speaker=speaker,
            audio_file=audio_file,
            broadcast_log=current_log,
        )

        current_log.status = BroadcastLog.STATUS_PLAYING
        current_log.started_at = now
        current_log.request_payload = request_payload
        current_log.message = f"Playback started. mode={playback_mode}"
        try:
            with transaction.atomic():
                current_log.save(
                    update_fields=[
                        "status",
                        "started_at",
                        "request_payload",
                        "message",
                        "updated_at",
                    ]
                )
        except IntegrityError:
            current_log.status = BroadcastLog.STATUS_QUEUED
            current_log.started_at = None
            return {
                "success": False,
                "result": {
                    "broadcast_log_id": current_log.id,
                    "status": BroadcastLog.STATUS_QUEUED,
                    "message": "Speaker claim lost; broadcast remains queued.",
                    "reason": "speaker_claim_conflict",
                },
            }

        return {
            "success": True,
            "broadcast_log_id": current_log.id,
        }

    return _run_broadcast_db_write(_prepare)


def _fail_prepared_broadcast(
    current_log,
    *,
    reason,
    message,
    extra_payload=None,
):
    """Fail a pending log before any playback backend can be invoked."""

    current_log.status = BroadcastLog.STATUS_FAILED
    current_log.finished_at = timezone.now()
    current_log.message = message
    current_log.response_payload = {
        "success": False,
        "mode": get_broadcast_playback_mode(),
        "reason": reason,
        **(extra_payload or {}),
    }
    current_log.save(
        update_fields=[
            "status",
            "finished_at",
            "message",
            "response_payload",
            "updated_at",
        ]
    )
    return {
        "success": False,
        "result": {
            "broadcast_log_id": current_log.id,
            "status": current_log.status,
            "message": current_log.message,
            "speaker_code": (
                current_log.speaker.speaker_code
                if current_log.speaker else ""
            ),
            "audio_code": (
                current_log.audio_file.audio_code
                if current_log.audio_file else ""
            ),
        },
    }


def build_request_payload(playback_mode, speaker, audio_file, broadcast_log):
    """
    建立 request_payload，方便後續在 Admin / Dashboard 追蹤播放請求。
    """

    audio_file_name = ""
    audio_file_path = ""

    if audio_file.file:
        audio_file_name = audio_file.file.name

        try:
            audio_file_path = audio_file.file.path
        except NotImplementedError:
            audio_file_path = audio_file.file.name

    existing_payload = broadcast_log.request_payload or {}

    return {
        **existing_payload,
        "mode": playback_mode,
        "broadcast_log_id": broadcast_log.id,

        "speaker_id": speaker.id,
        "speaker_code": speaker.speaker_code,
        "speaker_name": speaker.name,
        "protocol": speaker.protocol,
        "ip_address": str(speaker.ip_address),
        "port": speaker.port,
        "sip_uri": speaker.sip_uri,
        "resolved_sip_uri": speaker.resolved_sip_uri,

        "audio_file_id": audio_file.id,
        "audio_code": audio_file.audio_code,
        "audio_name": audio_file.name,
        "audio_file": audio_file_name,
        "audio_path": audio_file_path,

        "requested_at": timezone.localtime(timezone.now()).strftime("%Y-%m-%d %H:%M:%S"),
    }


def play_audio_to_speaker(speaker, audio_file, broadcast_log):
    """
    播放音檔到 IP Speaker 的總入口。
    """

    # Defence in depth: status can change after the log was marked playing but
    # before the external playback process starts. Always use current DB state.
    speaker = SpeakerDevice.objects.get(pk=speaker.pk)
    if not speaker.is_active:
        return {
            "success": False,
            "mode": get_broadcast_playback_mode(),
            "broadcast_log_id": broadcast_log.id,
            "speaker_code": speaker.speaker_code,
            "reason": "speaker_inactive",
            "message": (
                f"Playback blocked: SpeakerDevice {speaker.speaker_code} "
                "is inactive."
            ),
        }
    if speaker.status != SpeakerDevice.STATUS_ONLINE:
        return {
            "success": False,
            "mode": get_broadcast_playback_mode(),
            "broadcast_log_id": broadcast_log.id,
            "speaker_code": speaker.speaker_code,
            "speaker_status": speaker.status,
            "reason": "speaker_offline",
            "message": (
                f"Playback blocked: SpeakerDevice {speaker.speaker_code} "
                f"status is {speaker.status}."
            ),
        }

    playback_mode = get_broadcast_playback_mode()

    if playback_mode == PLAYBACK_MODE_SIMULATION:
        return simulate_play_audio_to_speaker(
            speaker=speaker,
            audio_file=audio_file,
            broadcast_log=broadcast_log,
        )

    if playback_mode == PLAYBACK_MODE_PJSIP:
        return play_audio_via_pjsip(
            speaker=speaker,
            audio_file=audio_file,
            broadcast_log=broadcast_log,
        )

    if playback_mode == PLAYBACK_MODE_MICROSIP_WINSOUND:
        return play_audio_via_microsip_winsound(
            speaker=speaker,
            audio_file=audio_file,
            broadcast_log=broadcast_log,
        )

    return {
        "success": False,
        "mode": playback_mode,
        "broadcast_log_id": broadcast_log.id,
        "reason": "unsupported_playback_mode",
        "message": f"Unsupported BROADCAST_PLAYBACK_MODE: {playback_mode}",
    }


def simulate_play_audio_to_speaker(speaker, audio_file, broadcast_log):
    """
    模擬播放音檔到 IP Speaker。
    """

    return {
        "success": True,
        "mode": PLAYBACK_MODE_SIMULATION,
        "broadcast_log_id": broadcast_log.id,
        "speaker_code": speaker.speaker_code,
        "speaker_endpoint": speaker.endpoint_base_url,
        "resolved_sip_uri": speaker.resolved_sip_uri,
        "audio_code": audio_file.audio_code,
        "audio_file": audio_file.file.name if audio_file.file else "",
        "played_at": timezone.localtime(timezone.now()).strftime("%Y-%m-%d %H:%M:%S"),
        "message": "Simulation playback completed successfully.",
    }


def play_audio_via_microsip_winsound(speaker, audio_file, broadcast_log):
    """
    使用 MicroSIP + winsound 播放 wav 音檔到 SIP Speaker。

    流程：
    1. 使用 Windows SIP URI handler 呼叫 MicroSIP 撥號。
    2. 等待 MicroSIP 建立通話。
    3. 使用 winsound 同步播放 wav 音檔。
    4. 播放結束後等待 margin。
    5. 嘗試自動掛斷 MicroSIP。

    前提：
    1. Windows 環境。
    2. MicroSIP 已安裝並註冊 sip: URI handler。
    3. MicroSIP 麥克風來源需設定為 Stereo Mix 或 CABLE Output。
    4. 目前第一版只支援 wav 音檔。
    """

    if sys.platform != "win32":
        return {
            "success": False,
            "mode": PLAYBACK_MODE_MICROSIP_WINSOUND,
            "broadcast_log_id": broadcast_log.id,
            "reason": "unsupported_platform",
            "message": "microsip_winsound mode only supports Windows.",
        }

    sip_uri = speaker.resolved_sip_uri

    if not sip_uri:
        return {
            "success": False,
            "mode": PLAYBACK_MODE_MICROSIP_WINSOUND,
            "broadcast_log_id": broadcast_log.id,
            "reason": "sip_uri_missing",
            "message": "Speaker SIP URI is missing.",
        }

    audio_path_result = get_audio_file_absolute_path(audio_file)

    if not audio_path_result["success"]:
        return {
            "success": False,
            "mode": PLAYBACK_MODE_MICROSIP_WINSOUND,
            "broadcast_log_id": broadcast_log.id,
            **audio_path_result,
        }

    audio_path = Path(audio_path_result["audio_path"])

    if audio_path.suffix.lower() != ".wav":
        return {
            "success": False,
            "mode": PLAYBACK_MODE_MICROSIP_WINSOUND,
            "broadcast_log_id": broadcast_log.id,
            "reason": "unsupported_audio_format",
            "audio_path": str(audio_path),
            "message": "microsip_winsound mode currently supports wav only. Please use a wav test audio file.",
        }

    duration_result = get_wav_duration_seconds(audio_path)

    if not duration_result["success"]:
        return {
            "success": False,
            "mode": PLAYBACK_MODE_MICROSIP_WINSOUND,
            "broadcast_log_id": broadcast_log.id,
            **duration_result,
        }

    dial_result = start_sip_call(sip_uri)

    if not dial_result["success"]:
        return {
            "success": False,
            "mode": PLAYBACK_MODE_MICROSIP_WINSOUND,
            "broadcast_log_id": broadcast_log.id,
            **dial_result,
        }

    play_delay = get_play_after_dial_delay_seconds()
    hangup_margin = get_hangup_after_audio_margin_seconds()

    time.sleep(play_delay)

    playback_result = play_wav_file_sync(audio_path)

    if not playback_result["success"]:
        return {
            "success": False,
            "mode": PLAYBACK_MODE_MICROSIP_WINSOUND,
            "broadcast_log_id": broadcast_log.id,
            "sip_uri": sip_uri,
            "audio_path": str(audio_path),
            **playback_result,
        }

    time.sleep(hangup_margin)

    hangup_result = hangup_microsip_call()

    return {
        "success": True,
        "mode": PLAYBACK_MODE_MICROSIP_WINSOUND,
        "broadcast_log_id": broadcast_log.id,

        "speaker_code": speaker.speaker_code,
        "speaker_name": speaker.name,
        "sip_uri": sip_uri,

        "audio_code": audio_file.audio_code,
        "audio_name": audio_file.name,
        "audio_path": str(audio_path),
        "audio_duration_seconds": duration_result["duration_seconds"],

        "play_after_dial_delay_seconds": play_delay,
        "hangup_after_audio_margin_seconds": hangup_margin,

        "dial_result": dial_result,
        "playback_result": playback_result,
        "hangup_result": hangup_result,

        "played_at": timezone.localtime(timezone.now()).strftime("%Y-%m-%d %H:%M:%S"),
        "message": "MicroSIP winsound playback completed successfully.",
    }


def get_audio_file_absolute_path(audio_file):
    """
    取得 AudioFile 的本機絕對路徑。
    """

    if not audio_file.file:
        return {
            "success": False,
            "reason": "audio_file_empty",
            "message": "AudioFile.file is empty.",
        }

    try:
        audio_path = Path(audio_file.file.path)
    except NotImplementedError:
        return {
            "success": False,
            "reason": "audio_storage_not_local",
            "message": "Audio file storage does not provide a local file path.",
        }

    if not audio_path.exists():
        return {
            "success": False,
            "reason": "audio_file_not_found",
            "audio_path": str(audio_path),
            "message": f"Audio file not found: {audio_path}",
        }

    if not audio_path.is_file():
        return {
            "success": False,
            "reason": "audio_path_is_not_file",
            "audio_path": str(audio_path),
            "message": f"Audio path is not a file: {audio_path}",
        }

    return {
        "success": True,
        "audio_path": str(audio_path),
    }


def get_wav_duration_seconds(audio_path):
    """
    讀取 wav 音檔長度。
    """

    try:
        with wave.open(str(audio_path), "rb") as wav_file:
            frames = wav_file.getnframes()
            frame_rate = wav_file.getframerate()

            if frame_rate <= 0:
                return {
                    "success": False,
                    "reason": "invalid_wav_frame_rate",
                    "audio_path": str(audio_path),
                    "message": "Invalid wav frame rate.",
                }

            duration_seconds = frames / float(frame_rate)

            return {
                "success": True,
                "duration_seconds": round(duration_seconds, 3),
            }

    except (wave.Error, OSError) as exc:
        return {
            "success": False,
            "reason": "read_wav_duration_failed",
            "audio_path": str(audio_path),
            "message": f"Failed to read wav duration: {exc}",
        }


def start_sip_call(sip_uri):
    """
    使用 Windows SIP URI handler 啟動 MicroSIP 撥號。
    """

    try:
        subprocess.Popen(
            ["cmd", "/c", "start", "", sip_uri],
            shell=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError as exc:
        return {
            "success": False,
            "reason": "start_sip_call_failed",
            "sip_uri": sip_uri,
            "message": f"Failed to start SIP call: {exc}",
        }

    return {
        "success": True,
        "sip_uri": sip_uri,
        "message": "SIP call request sent.",
    }


def play_wav_file_sync(audio_path):
    """
    使用 winsound 同步播放 wav 音檔。
    """

    try:
        import winsound

        winsound.PlaySound(
            str(audio_path),
            winsound.SND_FILENAME,
        )

    except RuntimeError as exc:
        return {
            "success": False,
            "reason": "winsound_play_failed",
            "audio_path": str(audio_path),
            "message": f"winsound playback failed: {exc}",
        }

    except OSError as exc:
        return {
            "success": False,
            "reason": "audio_file_os_error",
            "audio_path": str(audio_path),
            "message": f"Audio file OS error: {exc}",
        }

    return {
        "success": True,
        "audio_path": str(audio_path),
        "message": "wav playback completed.",
    }


def hangup_microsip_call():
    """
    嘗試掛斷 MicroSIP。

    優先：
    microsip.exe /hangupall

    備援：
    PowerShell AppActivate('MicroSIP') + ESC
    """

    command_result = try_microsip_hangup_command()

    if command_result["success"]:
        return command_result

    escape_result = try_send_escape_to_microsip()

    if escape_result["success"]:
        return escape_result

    return {
        "success": False,
        "reason": "hangup_failed",
        "command_result": command_result,
        "escape_result": escape_result,
        "message": "Failed to hang up MicroSIP automatically. Please hang up manually.",
    }


def try_microsip_hangup_command():
    """
    使用 microsip.exe /hangupall 掛斷所有通話。
    """

    microsip_exe = find_microsip_exe_path()

    if microsip_exe is None:
        return {
            "success": False,
            "reason": "microsip_exe_not_found",
            "checked_paths": get_microsip_paths(),
            "message": "MicroSIP exe not found. Cannot run /hangupall.",
        }

    try:
        subprocess.Popen(
            [str(microsip_exe), "/hangupall"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    except OSError as exc:
        return {
            "success": False,
            "reason": "microsip_hangup_command_failed",
            "microsip_exe": str(microsip_exe),
            "message": f"Failed to run MicroSIP hangup command: {exc}",
        }

    return {
        "success": True,
        "method": "microsip_hangupall",
        "microsip_exe": str(microsip_exe),
        "message": "MicroSIP /hangupall command sent.",
    }


def try_send_escape_to_microsip():
    """
    備援掛斷方式：
    使用 PowerShell 啟用 MicroSIP 視窗並送 ESC。
    """

    command = (
        "$ws = New-Object -ComObject WScript.Shell; "
        "if ($ws.AppActivate('MicroSIP')) { "
        "Start-Sleep -Milliseconds 200; "
        "$ws.SendKeys('{ESC}'); "
        "exit 0 "
        "} else { "
        "exit 1 "
        "}"
    )

    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", command],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=3,
        )

    except (OSError, subprocess.TimeoutExpired) as exc:
        return {
            "success": False,
            "reason": "send_escape_failed",
            "message": f"Failed to send ESC to MicroSIP: {exc}",
        }

    if result.returncode == 0:
        return {
            "success": True,
            "method": "powershell_send_escape",
            "message": "ESC sent to MicroSIP window.",
        }

    return {
        "success": False,
        "reason": "microsip_window_not_found",
        "message": "MicroSIP window not found. Cannot send ESC.",
    }


def find_microsip_exe_path():
    """
    從設定路徑中找出 microsip.exe。

    注意：
    .lnk 可以用來開啟 MicroSIP，但不能可靠地執行 /hangupall。
    所以掛斷指令只使用 .exe。
    """

    for path_text in get_microsip_paths():
        path = Path(path_text)

        if path.exists() and path.suffix.lower() == ".exe":
            return path

    return None


def get_microsip_paths():
    """
    取得 MicroSIP 可能路徑。
    """

    return getattr(
        settings,
        "BROADCAST_MICROSIP_PATHS",
        DEFAULT_MICROSIP_PATHS,
    )


def get_broadcast_playback_mode():
    """
    取得目前有效的廣播播放後端。

    由 runtime resolver 統一解析環境安全預設與 Superuser 工程模式。
    """

    return get_broadcast_runtime_config().operational_backend


def get_play_after_dial_delay_seconds():
    """
    撥號後等待多久才播放音檔。
    """

    value = getattr(
        settings,
        "BROADCAST_PLAY_AFTER_DIAL_DELAY_SECONDS",
        DEFAULT_PLAY_AFTER_DIAL_DELAY_SECONDS,
    )

    try:
        return max(0, float(value))
    except (TypeError, ValueError):
        return DEFAULT_PLAY_AFTER_DIAL_DELAY_SECONDS


def get_hangup_after_audio_margin_seconds():
    """
    音檔播放結束後，等待多久再掛斷。
    """

    value = getattr(
        settings,
        "BROADCAST_HANGUP_AFTER_AUDIO_MARGIN_SECONDS",
        DEFAULT_HANGUP_AFTER_AUDIO_MARGIN_SECONDS,
    )

    try:
        return max(0, float(value))
    except (TypeError, ValueError):
        return DEFAULT_HANGUP_AFTER_AUDIO_MARGIN_SECONDS


def mark_broadcast_success(log, message, response_payload=None):
    """
    將 BroadcastLog 標記為 success。
    """

    def _mark():
        current_log = BroadcastLog.objects.select_for_update().get(pk=log.pk)
        current_log.status = BroadcastLog.STATUS_SUCCESS
        current_log.finished_at = timezone.now()
        current_log.message = message
        current_log.response_payload = response_payload or {}
        current_log.save(
            update_fields=[
                "status",
                "finished_at",
                "message",
                "response_payload",
                "updated_at",
            ]
        )
        return current_log

    log = _run_broadcast_db_write(_mark)
    result = {
        "broadcast_log_id": log.id,
        "status": log.status,
        "message": message,
        "speaker_code": log.speaker.speaker_code if log.speaker else "",
        "audio_code": log.audio_file.audio_code if log.audio_file else "",
    }
    return result


def mark_broadcast_failed(log, message, response_payload=None):
    """
    將 BroadcastLog 標記為 failed。
    """

    def _mark():
        current_log = BroadcastLog.objects.select_for_update().get(pk=log.pk)
        current_log.status = BroadcastLog.STATUS_FAILED
        current_log.finished_at = timezone.now()
        current_log.message = message
        current_log.response_payload = response_payload or {}
        current_log.save(
            update_fields=[
                "status",
                "finished_at",
                "message",
                "response_payload",
                "updated_at",
            ]
        )
        return current_log

    log = _run_broadcast_db_write(_mark)
    result = {
        "broadcast_log_id": log.id,
        "status": log.status,
        "message": message,
        "speaker_code": log.speaker.speaker_code if log.speaker else "",
        "audio_code": log.audio_file.audio_code if log.audio_file else "",
    }
    return result


def play_audio_via_pjsip(speaker, audio_file, broadcast_log):
    """Play one local WAV file through the validated PJSIP/PJSUA backend."""

    log_path = (
        Path(settings.PJSIP_LOG_DIR)
        / f"dashboard_broadcast_{broadcast_log.id}_{speaker.speaker_code}.log"
    )

    requested_volume = (broadcast_log.request_payload or {}).get(
        "volume_percent",
        None,
    )

    try:
        readiness = prepare_pjsip_readiness(
            speaker_code=speaker.speaker_code,
            audio_code=audio_file.audio_code,
            log_path=log_path,
            check_ports=True,
            audio_gain_percent=requested_volume,
        )
        speaker = readiness.speaker
        audio_file = readiness.audio_file
        plan = readiness.plan
        result = execute_pjsip_playback_plan(
            plan,
            extra_wait_seconds=settings.PJSIP_EXTRA_WAIT_SECONDS,
        )
    except PjsipPreflightError as exc:
        return {
            "success": False,
            "mode": PLAYBACK_MODE_PJSIP,
            "message": str(exc),
            "reason": "pjsip_preflight_error",
            "speaker_code": speaker.speaker_code,
            "resolved_sip_uri": speaker.resolved_sip_uri,
            "audio_code": audio_file.audio_code,
        }

    return {
        "success": result.success,
        "mode": PLAYBACK_MODE_PJSIP,
        "message": result.message,
        "broadcast_log_id": broadcast_log.id,
        "speaker_code": speaker.speaker_code,
        "resolved_sip_uri": speaker.resolved_sip_uri,
        "audio_code": audio_file.audio_code,
        "audio_file": audio_file.file.name,
        "confirmed": result.confirmed,
        "media_active": result.media_active,
        "disconnected": result.disconnected,
        "return_code": result.return_code,
        "log_file": result.log_path.name,
        "local_sip_port": plan.local_sip_port,
        "local_rtp_port": plan.local_rtp_port,
        "audio_gain_percent": plan.audio_gain_percent,
        "preferred_codec": speaker.preferred_codec,
    }
