import json

from django.contrib.auth.decorators import login_required
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from apps.accounts.permissions import can_process_events
from apps.events.models import Event

from .models import AudioFile, BroadcastLog, BroadcastRule, SpeakerDevice
from .services import (
    PLAYBACK_MODE_PJSIP,
    PLAYBACK_MODE_SIMULATION,
    get_broadcast_playback_mode,
    process_pending_broadcast_logs,
    process_single_broadcast_log,
)


@csrf_exempt
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
    """Play one selected prerecorded audio file to one selected station speaker."""
    if not can_process_events(request.user):
        return JsonResponse({"success": False, "message": "You do not have permission to broadcast."}, status=403)

    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except (UnicodeDecodeError, json.JSONDecodeError):
        return JsonResponse({"success": False, "message": "Invalid JSON body."}, status=400)

    speaker_id = payload.get("speaker_id")
    audio_file_id = payload.get("audio_file_id")
    if not speaker_id or not audio_file_id:
        return JsonResponse({"success": False, "message": "speaker_id and audio_file_id are required."}, status=400)

    speaker = get_object_or_404(SpeakerDevice, pk=speaker_id, is_active=True)
    audio_file = get_object_or_404(AudioFile, pk=audio_file_id, is_active=True)

    try:
        if not audio_file.file or not audio_file.file.storage.exists(audio_file.file.name):
            return JsonResponse({
                "success": False,
                "reason": "audio_missing",
                "message": f"Audio file {audio_file.audio_code} is missing.",
            }, status=409)
    except Exception as exc:
        return JsonResponse({"success": False, "message": f"Unable to verify audio file: {exc}"}, status=409)

    busy_log = (
        BroadcastLog.objects.filter(
            speaker=speaker,
            status__in=[BroadcastLog.STATUS_PENDING, BroadcastLog.STATUS_PLAYING],
        ).order_by("created_at").first()
    )
    if busy_log:
        return JsonResponse({
            "success": False,
            "reason": "speaker_busy",
            "message": f"Speaker {speaker.speaker_code} is currently busy.",
            "active_broadcast_log_id": busy_log.id,
        }, status=409)

    try:
        with transaction.atomic():
            log = BroadcastLog.objects.create(
                speaker=speaker,
                audio_file=audio_file,
                status=BroadcastLog.STATUS_PENDING,
                request_payload={
                    "source": "station_broadcast_console",
                    "requested_by_id": request.user.id,
                    "requested_by_username": request.user.get_username(),
                    "speaker_code": speaker.speaker_code,
                    "audio_code": audio_file.audio_code,
                },
                message="Manual station broadcast created from broadcast console.",
                requested_at=timezone.now(),
            )
    except IntegrityError:
        return JsonResponse({"success": False, "reason": "speaker_busy", "message": "Speaker became busy before playback started."}, status=409)

    result = process_single_broadcast_log(log)
    log.refresh_from_db()
    success = log.status == BroadcastLog.STATUS_SUCCESS
    return JsonResponse({
        "success": success,
        "message": result.get("message", "Manual station broadcast processed."),
        "broadcast_log_id": log.id,
        "status": log.status,
        "status_display": log.get_status_display(),
        "speaker_code": speaker.speaker_code,
        "audio_code": audio_file.audio_code,
        "requested_at": timezone.localtime(log.requested_at).strftime("%Y-%m-%d %H:%M:%S"),
    }, status=200 if success else 502)
