import json

from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from apps.accounts.permissions import can_process_events
from apps.events.models import Event

from .models import BroadcastLog, BroadcastRule
from .services import (
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

    if playback_mode != PLAYBACK_MODE_SIMULATION:
        return JsonResponse(
            {
                "success": False,
                "message": "Step 19.4A manual broadcast requires simulation mode.",
                "playback_mode": playback_mode,
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

    created = active_log is None

    if created:
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
