import json
from concurrent.futures import ThreadPoolExecutor, as_completed

from django.contrib.auth.decorators import login_required
from django.db import IntegrityError, close_old_connections, transaction
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from apps.accounts.permissions import can_process_events
from apps.events.models import Event

from .forms import BroadcastScheduleForm
from .live_broadcast import live_broadcast_manager
from .backends.pjsip_microphone import PjsipMicrophoneError
from .models import AudioFile, BroadcastLog, BroadcastRule, BroadcastSchedule, SpeakerDevice
from .services import (
    PLAYBACK_MODE_PJSIP,
    PLAYBACK_MODE_SIMULATION,
    get_broadcast_playback_mode,
    process_pending_broadcast_logs,
    process_single_broadcast_log,
)


@login_required
@require_POST
def process_pending_broadcast_logs_api(request):
    """
    Step 20-1 API：
    手動處理 pending BroadcastLog。

    注意：
    目前是 PoC / local development 測試用 API。
    為了方便 PowerShell Invoke-RestMethod 測試，暫時使用 csrf_exempt。
    正式版應改回登入驗證與權限控管。

    Endpoint:
    POST /api/notifications/broadcast/process-pending/

    Body optional:
    {
        "limit": 10
    }
    """

    limit = 10

    if request.body:
        try:
            payload = json.loads(request.body.decode("utf-8"))
            limit = int(payload.get("limit", 10))
        except Exception:
            return JsonResponse(
                {
                    "success": False,
                    "message": "Invalid JSON body.",
                },
                status=400,
            )

    if limit <= 0:
        return JsonResponse(
            {
                "success": False,
                "message": "limit must be greater than 0.",
            },
            status=400,
        )

    result = process_pending_broadcast_logs(limit=limit)

    return JsonResponse(
        {
            "success": True,
            "message": "Pending BroadcastLog processed.",
            "pending_count": BroadcastLog.objects.filter(
                status=BroadcastLog.STATUS_PENDING
            ).count(),
            **result,
        }
    )


@login_required
@require_POST
def manual_event_broadcast_api(request, event_id):
    """Create and process one manual broadcast for an active event."""

    if not can_process_events(request.user):
        return JsonResponse(
            {
                "success": False,
                "message": "You do not have permission to broadcast events.",
            },
            status=403,
        )

    playback_mode = get_broadcast_playback_mode()

    allowed_playback_modes = {
        PLAYBACK_MODE_SIMULATION,
        PLAYBACK_MODE_PJSIP,
    }

    if playback_mode not in allowed_playback_modes:
        return JsonResponse(
            {
                "success": False,
                "message": "Dashboard manual broadcast does not support this playback mode.",
                "playback_mode": playback_mode,
                "allowed_playback_modes": sorted(allowed_playback_modes),
            },
            status=409,
        )

    event = get_object_or_404(
        Event.objects.select_related("camera"),
        pk=event_id,
    )

    if event.status in {"dismissed", "closed"}:
        return JsonResponse(
            {
                "success": False,
                "message": "Dismissed or closed events cannot be broadcast.",
            },
            status=409,
        )

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

    if not rules:
        return JsonResponse(
            {
                "success": False,
                "message": "No active BroadcastRule matches this event.",
            },
            status=409,
        )

    rule = rules[0]
    active_log = (
        BroadcastLog.objects
        .filter(
            event=event,
            rule=rule,
            status__in=[
                BroadcastLog.STATUS_PENDING,
                BroadcastLog.STATUS_PLAYING,
            ],
        )
        .order_by("-created_at")
        .first()
    )

    if active_log and active_log.status == BroadcastLog.STATUS_PLAYING:
        return JsonResponse(
            {
                "success": False,
                "message": "This event broadcast is already playing.",
                "broadcast_log_id": active_log.id,
            },
            status=409,
        )

    if active_log is None:
        speaker_busy_log = (
            BroadcastLog.objects
            .filter(
                speaker=rule.speaker,
                status__in=[
                    BroadcastLog.STATUS_PENDING,
                    BroadcastLog.STATUS_PLAYING,
                ],
            )
            .order_by("created_at")
            .first()
        )

        if speaker_busy_log:
            return JsonResponse(
                {
                    "success": False,
                    "reason": "speaker_busy",
                    "message": (
                        f"Speaker {rule.speaker.speaker_code} is currently busy. "
                        "Please wait for the active broadcast to finish."
                    ),
                    "speaker_code": rule.speaker.speaker_code,
                    "active_broadcast_log_id": speaker_busy_log.id,
                    "active_event_id": speaker_busy_log.event_id,
                    "active_status": speaker_busy_log.status,
                },
                status=409,
            )

    created = active_log is None

    if created:
        try:
            with transaction.atomic():
                active_log = BroadcastLog.objects.create(
                    event=event,
                    rule=rule,
                    speaker=rule.speaker,
                    audio_file=rule.audio_file,
                    status=BroadcastLog.STATUS_PENDING,
                    request_payload={
                        "source": "dashboard_manual_event_broadcast",
                        "requested_by_id": request.user.id,
                        "requested_by_username": request.user.get_username(),
                        "event_id": event.id,
                        "camera_code": event.camera.camera_code,
                        "rule_code": rule.rule_code,
                        "speaker_code": rule.speaker.speaker_code,
                        "audio_code": rule.audio_file.audio_code,
                    },
                    message="Manual event broadcast created from Dashboard.",
                    requested_at=timezone.now(),
                )
        except IntegrityError:
            speaker_busy_log = (
                BroadcastLog.objects
                .filter(
                    speaker=rule.speaker,
                    status__in=[
                        BroadcastLog.STATUS_PENDING,
                        BroadcastLog.STATUS_PLAYING,
                    ],
                )
                .order_by("created_at")
                .first()
            )

            return JsonResponse(
                {
                    "success": False,
                    "reason": "speaker_busy",
                    "message": (
                        f"Speaker {rule.speaker.speaker_code} became busy "
                        "before this broadcast could start."
                    ),
                    "speaker_code": rule.speaker.speaker_code,
                    "active_broadcast_log_id": (
                        speaker_busy_log.id if speaker_busy_log else None
                    ),
                    "active_event_id": (
                        speaker_busy_log.event_id if speaker_busy_log else None
                    ),
                    "active_status": (
                        speaker_busy_log.status if speaker_busy_log else None
                    ),
                },
                status=409,
            )

    result = process_single_broadcast_log(active_log)
    active_log.refresh_from_db()
    success = active_log.status == BroadcastLog.STATUS_SUCCESS

    return JsonResponse(
        {
            "success": success,
            "message": result.get("message", "Manual broadcast processed."),
            "created": created,
            "event_id": event.id,
            "broadcast_log_id": active_log.id,
            "status": active_log.status,
            "status_display": active_log.get_status_display(),
            "rule_code": rule.rule_code,
            "speaker_code": rule.speaker.speaker_code,
            "audio_code": rule.audio_file.audio_code,
            "result": result,
        },
        status=200 if success else 502,
    )


@login_required
@require_POST
def manual_station_broadcast_api(request):
    """Play one prerecorded audio file to one or more selected station speakers."""
    if not can_process_events(request.user):
        return JsonResponse(
            {"success": False, "message": "You do not have permission to broadcast."},
            status=403,
        )

    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except (UnicodeDecodeError, json.JSONDecodeError):
        return JsonResponse({"success": False, "message": "Invalid JSON body."}, status=400)

    raw_speaker_ids = payload.get("speaker_ids")
    if raw_speaker_ids is None:
        raw_speaker_ids = [payload.get("speaker_id")]
    if not isinstance(raw_speaker_ids, list):
        return JsonResponse(
            {"success": False, "message": "speaker_ids must be a list."},
            status=400,
        )

    speaker_ids = []
    for value in raw_speaker_ids:
        if value in (None, ""):
            continue
        try:
            speaker_ids.append(int(value))
        except (TypeError, ValueError):
            return JsonResponse(
                {"success": False, "message": f"Invalid speaker id: {value}"},
                status=400,
            )
    speaker_ids = list(dict.fromkeys(speaker_ids))
    audio_file_id = payload.get("audio_file_id")
    try:
        volume_percent = max(0, min(200, int(payload.get("volume_percent", 100))))
    except (TypeError, ValueError):
        return JsonResponse({"success": False, "message": "Invalid volume_percent."}, status=400)

    if not speaker_ids or not audio_file_id:
        return JsonResponse(
            {
                "success": False,
                "message": "At least one speaker_id and audio_file_id are required.",
            },
            status=400,
        )
    if len(speaker_ids) > 16:
        return JsonResponse(
            {"success": False, "message": "A maximum of 16 Speakers is allowed per request."},
            status=400,
        )

    speakers = list(
        SpeakerDevice.objects.filter(pk__in=speaker_ids, is_active=True).order_by("speaker_code")
    )
    if len(speakers) != len(speaker_ids):
        return JsonResponse(
            {"success": False, "message": "One or more selected Speakers are missing or inactive."},
            status=404,
        )
    audio_file = get_object_or_404(AudioFile, pk=audio_file_id, is_active=True)

    try:
        if not audio_file.file or not audio_file.file.storage.exists(audio_file.file.name):
            return JsonResponse(
                {
                    "success": False,
                    "reason": "audio_missing",
                    "message": f"Audio file {audio_file.audio_code} is missing.",
                },
                status=409,
            )
    except Exception as exc:
        return JsonResponse(
            {"success": False, "message": f"Unable to verify audio file: {exc}"},
            status=409,
        )

    busy_logs = list(
        BroadcastLog.objects.filter(
            speaker__in=speakers,
            status__in=[BroadcastLog.STATUS_PENDING, BroadcastLog.STATUS_PLAYING],
        ).select_related("speaker")
    )
    if busy_logs:
        return JsonResponse(
            {
                "success": False,
                "reason": "speaker_busy",
                "message": "One or more selected Speakers are currently busy.",
                "busy_speakers": [log.speaker.speaker_code for log in busy_logs],
            },
            status=409,
        )

    logs = []
    try:
        with transaction.atomic():
            for speaker in speakers:
                logs.append(
                    BroadcastLog.objects.create(
                        speaker=speaker,
                        audio_file=audio_file,
                        status=BroadcastLog.STATUS_PENDING,
                        request_payload={
                            "source": "station_broadcast_console",
                            "requested_by_id": request.user.id,
                            "requested_by_username": request.user.get_username(),
                            "speaker_code": speaker.speaker_code,
                            "audio_code": audio_file.audio_code,
                            "multi_speaker_count": len(speakers),
                            "volume_percent": volume_percent,
                        },
                        message="Manual station broadcast created from broadcast console.",
                        requested_at=timezone.now(),
                    )
                )
    except IntegrityError:
        return JsonResponse(
            {
                "success": False,
                "reason": "speaker_busy",
                "message": "A selected Speaker became busy before playback started.",
            },
            status=409,
        )

    def _process(log_id):
        close_old_connections()
        try:
            log = BroadcastLog.objects.get(pk=log_id)
            return process_single_broadcast_log(log)
        finally:
            close_old_connections()

    results = []
    worker_count = min(len(logs), 4)
    if len(logs) == 1:
        results.append(_process(logs[0].id))
    else:
        with ThreadPoolExecutor(max_workers=worker_count, thread_name_prefix="krtc-pjsip") as executor:
            futures = {executor.submit(_process, log.id): log.id for log in logs}
            for future in as_completed(futures):
                log_id = futures[future]
                try:
                    results.append(future.result())
                except Exception as exc:
                    log = BroadcastLog.objects.get(pk=log_id)
                    log.status = BroadcastLog.STATUS_FAILED
                    log.message = f"Parallel playback worker failed: {exc}"
                    log.finished_at = timezone.now()
                    log.save(update_fields=["status", "message", "finished_at", "updated_at"])
                    results.append(
                        {
                            "broadcast_log_id": log_id,
                            "status": BroadcastLog.STATUS_FAILED,
                            "message": log.message,
                        }
                    )

    refreshed_logs = list(
        BroadcastLog.objects.filter(pk__in=[log.id for log in logs]).select_related("speaker")
    )
    success_logs = [log for log in refreshed_logs if log.status == BroadcastLog.STATUS_SUCCESS]
    failed_logs = [log for log in refreshed_logs if log.status != BroadcastLog.STATUS_SUCCESS]
    success = not failed_logs

    return JsonResponse(
        {
            "success": success,
            "message": (
                f"Completed {len(success_logs)} of {len(refreshed_logs)} Speaker broadcasts."
            ),
            "broadcast_log_ids": [log.id for log in refreshed_logs],
            "status": "success" if success else "partial_or_failed",
            "speaker_codes": [log.speaker.speaker_code for log in refreshed_logs],
            "successful_speakers": [log.speaker.speaker_code for log in success_logs],
            "failed_speakers": [log.speaker.speaker_code for log in failed_logs],
            "audio_code": audio_file.audio_code,
            "results": results,
            "requested_at": timezone.localtime(logs[0].requested_at).strftime("%Y-%m-%d %H:%M:%S"),
        },
        status=200 if success else 502,
    )



@login_required
@require_POST
def create_broadcast_schedule_api(request):
    """Create a minimal one-time or daily prerecorded broadcast schedule."""
    if not can_process_events(request.user):
        return JsonResponse({"success": False, "message": "You do not have permission to create schedules."}, status=403)

    form = BroadcastScheduleForm(request.POST)
    if not form.is_valid():
        return JsonResponse({"success": False, "message": "排程資料不完整。", "errors": form.errors.get_json_data()}, status=400)

    schedule = form.save(commit=False)
    schedule.created_by = request.user
    schedule.next_run_at = schedule.calculate_next_run() if schedule.is_active else None
    schedule.save()
    form.save_m2m()
    return JsonResponse({
        "success": True,
        "message": "排程已建立。",
        "schedule_id": schedule.id,
        "next_run_at": timezone.localtime(schedule.next_run_at).strftime("%Y-%m-%d %H:%M") if schedule.next_run_at else None,
    })


@login_required
@require_POST
def toggle_broadcast_schedule_api(request, schedule_id):
    if not can_process_events(request.user):
        return JsonResponse({"success": False, "message": "You do not have permission to modify schedules."}, status=403)
    schedule = get_object_or_404(BroadcastSchedule, pk=schedule_id)
    schedule.is_active = not schedule.is_active
    schedule.next_run_at = schedule.calculate_next_run() if schedule.is_active else None
    schedule.save(update_fields=["is_active", "next_run_at", "updated_at"])
    return JsonResponse({"success": True, "is_active": schedule.is_active})


@login_required
@require_POST
def delete_broadcast_schedule_api(request, schedule_id):
    if not can_process_events(request.user):
        return JsonResponse({"success": False, "message": "You do not have permission to delete schedules."}, status=403)
    schedule = get_object_or_404(BroadcastSchedule, pk=schedule_id)
    schedule.delete()
    return JsonResponse({"success": True, "message": "排程已刪除。"})


@login_required
@require_POST
def start_live_microphone_broadcast_api(request):
    """Start one real Windows microphone broadcast session for 1-4 Speakers."""
    if not can_process_events(request.user):
        return JsonResponse({"success": False, "message": "You do not have permission to broadcast."}, status=403)

    if get_broadcast_playback_mode() != PLAYBACK_MODE_PJSIP:
        return JsonResponse(
            {"success": False, "message": "即時人聲廣播僅支援正式 PJSIP 模式。"},
            status=409,
        )

    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except (UnicodeDecodeError, json.JSONDecodeError):
        return JsonResponse({"success": False, "message": "Invalid JSON body."}, status=400)

    raw_ids = payload.get("speaker_ids", [])
    if not isinstance(raw_ids, list):
        return JsonResponse({"success": False, "message": "speaker_ids must be a list."}, status=400)

    speaker_ids = []
    for value in raw_ids:
        try:
            speaker_ids.append(int(value))
        except (TypeError, ValueError):
            return JsonResponse({"success": False, "message": f"Invalid speaker id: {value}"}, status=400)
    speaker_ids = list(dict.fromkeys(speaker_ids))

    speakers = list(
        SpeakerDevice.objects.filter(pk__in=speaker_ids, is_active=True).order_by("speaker_code")
    )
    if not speaker_ids or len(speakers) != len(speaker_ids):
        return JsonResponse(
            {"success": False, "message": "One or more selected Speakers are missing or inactive."},
            status=404,
        )

    try:
        volume_percent = max(0, min(200, int(payload.get("volume_percent", 100))))
    except (TypeError, ValueError):
        return JsonResponse({"success": False, "message": "Invalid volume_percent."}, status=400)

    try:
        result = live_broadcast_manager.start(speakers, request.user, volume_percent=volume_percent)
    except PjsipMicrophoneError as exc:
        return JsonResponse({"success": False, "message": str(exc)}, status=409)
    except Exception as exc:
        return JsonResponse({"success": False, "message": f"無法啟動人聲廣播：{exc}"}, status=500)

    return JsonResponse({"success": True, "message": "即時人聲廣播已開始。", **result})


@login_required
@require_POST
def stop_live_microphone_broadcast_api(request):
    if not can_process_events(request.user):
        return JsonResponse({"success": False, "message": "You do not have permission to broadcast."}, status=403)
    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except (UnicodeDecodeError, json.JSONDecodeError):
        payload = {}
    try:
        result = live_broadcast_manager.stop(
            session_id=payload.get("session_id"),
            reason="manual_stop",
        )
    except PjsipMicrophoneError as exc:
        return JsonResponse({"success": False, "message": str(exc)}, status=409)
    return JsonResponse({"success": True, "message": "即時人聲廣播已停止。", **result})


@login_required
def live_microphone_broadcast_status_api(request):
    return JsonResponse({"success": True, **live_broadcast_manager.status()})
