import json
import logging

from django.contrib.auth.decorators import login_required
from django.db import IntegrityError, transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from apps.accounts.permissions import can_process_events
from apps.cameras.models import Camera
from apps.events.models import Event
from apps.notifications.models import BroadcastLog, BroadcastRule
from apps.notifications.services import (
    get_broadcast_playback_mode,
    mark_broadcast_failed,
    process_single_broadcast_log,
)


logger = logging.getLogger(__name__)


@csrf_exempt
@require_POST
def ai_event_trigger_api(request):
    """
    AI Event Trigger API

    用途：
    1. 接收外部 AI 模組送入的事件資料
    2. 依 camera_code 找到 Camera
    3. 建立 Event
    4. 依 event_type + camera 查找 BroadcastRule
    5. 建立 BroadcastLog
    6. 依目前 playback mode 自動執行廣播
    7. 回傳事件與廣播結果
    """

    try:
        payload = json.loads(request.body.decode("utf-8"))
    except json.JSONDecodeError:
        return JsonResponse(
            {
                "success": False,
                "message": "Invalid JSON payload.",
            },
            status=400,
        )

    camera_code = payload.get("camera_code")
    event_type = payload.get("event_type")
    confidence = payload.get("confidence")
    location_note = payload.get("location_note", "")
    message = payload.get("message", "")

    if not camera_code:
        return JsonResponse(
            {
                "success": False,
                "message": "camera_code is required.",
            },
            status=400,
        )

    if not event_type:
        return JsonResponse(
            {
                "success": False,
                "message": "event_type is required.",
            },
            status=400,
        )

    try:
        camera = Camera.objects.get(camera_code=camera_code)
    except Camera.DoesNotExist:
        return JsonResponse(
            {
                "success": False,
                "message": f"Camera not found: {camera_code}",
            },
            status=404,
        )

    with transaction.atomic():
        event = create_event_safely(
            camera=camera,
            event_type=event_type,
            confidence=confidence,
            payload=payload,
        )

    matched_rules = list(
        find_broadcast_rules(
            event_type=event_type,
            camera=camera,
        )
    )

    broadcast_logs = []

    for rule in matched_rules:
        active_log = BroadcastLog.objects.filter(
            speaker=rule.speaker,
            status__in=[
                BroadcastLog.STATUS_PENDING,
                BroadcastLog.STATUS_PLAYING,
            ],
        ).order_by("created_at").first()

        if active_log is not None:
            broadcast_logs.append(
                serialize_busy_broadcast_result(rule, active_log)
            )
            continue

        try:
            with transaction.atomic():
                broadcast_log = BroadcastLog.objects.create(
                    event=event,
                    rule=rule,
                    speaker=rule.speaker,
                    audio_file=rule.audio_file,
                    status=BroadcastLog.STATUS_PENDING,
                    request_payload={
                        "source": "ai_event_trigger_api",
                        "mode": get_broadcast_playback_mode(),
                        "camera_code": camera.camera_code,
                        "event_type": event_type,
                        "confidence": confidence,
                        "location_note": location_note,
                        "message": message,
                        "speaker_code": rule.speaker.speaker_code,
                        "speaker_sip_uri": rule.speaker.resolved_sip_uri,
                        "audio_code": rule.audio_file.audio_code,
                        "audio_name": rule.audio_file.name,
                        "raw_payload": payload,
                    },
                    message="Automatic broadcast task created.",
                    requested_at=timezone.now(),
                )
        except IntegrityError:
            active_log = BroadcastLog.objects.filter(
                speaker=rule.speaker,
                status__in=[
                    BroadcastLog.STATUS_PENDING,
                    BroadcastLog.STATUS_PLAYING,
                ],
            ).order_by("created_at").first()
            broadcast_logs.append(
                serialize_busy_broadcast_result(rule, active_log)
            )
            continue

        try:
            process_result = process_single_broadcast_log(broadcast_log)
        except Exception as exc:  # Keep the event API usable and retain an audit log.
            logger.exception(
                "Automatic broadcast failed unexpectedly. log_id=%s",
                broadcast_log.id,
            )
            broadcast_log.refresh_from_db()
            if broadcast_log.status in {
                BroadcastLog.STATUS_PENDING,
                BroadcastLog.STATUS_PLAYING,
            }:
                process_result = mark_broadcast_failed(
                    log=broadcast_log,
                    message=f"Unexpected automatic broadcast error: {exc}",
                    response_payload={
                        "success": False,
                        "mode": get_broadcast_playback_mode(),
                        "reason": "unexpected_auto_broadcast_error",
                        "error_type": type(exc).__name__,
                    },
                )
            else:
                process_result = {
                    "broadcast_log_id": broadcast_log.id,
                    "status": broadcast_log.status,
                    "message": broadcast_log.message,
                }

        broadcast_log.refresh_from_db()
        response_payload = broadcast_log.response_payload or {}
        broadcast_logs.append(
            {
                "id": broadcast_log.id,
                "status": broadcast_log.status,
                "message": process_result.get(
                    "message",
                    broadcast_log.message,
                ),
                "mode": response_payload.get(
                    "mode",
                    get_broadcast_playback_mode(),
                ),
                "reason": response_payload.get("reason"),
                "rule_code": rule.rule_code,
                "speaker_code": rule.speaker.speaker_code,
                "speaker_sip_uri": rule.speaker.resolved_sip_uri,
                "audio_code": rule.audio_file.audio_code,
                "audio_name": rule.audio_file.name,
            }
        )

    return JsonResponse(
        {
            "success": True,
            "message": "AI event created successfully.",
            "event": {
                "id": event.id,
                "camera_code": camera.camera_code,
                "camera_name": camera.name,
                "event_type": event.event_type,
                "confidence": getattr(event, "confidence", confidence),
                "status": getattr(event, "status", ""),
                "created_at": event.created_at.isoformat() if hasattr(event, "created_at") else None,
            },
            "broadcast": {
                "playback_mode": get_broadcast_playback_mode(),
                "matched_rule_count": len(matched_rules),
                "created_log_count": sum(
                    1 for item in broadcast_logs if item.get("id") is not None
                ),
                "logs": broadcast_logs,
            },
        },
        status=201,
    )


def serialize_busy_broadcast_result(rule, active_log):
    """Return a stable API result when the target Speaker is already busy."""

    return {
        "id": None,
        "status": BroadcastLog.STATUS_SKIPPED,
        "message": "Speaker already has a pending or playing broadcast.",
        "mode": get_broadcast_playback_mode(),
        "reason": "speaker_busy",
        "active_broadcast_log_id": active_log.id if active_log else None,
        "rule_code": rule.rule_code,
        "speaker_code": rule.speaker.speaker_code,
        "speaker_sip_uri": rule.speaker.resolved_sip_uri,
        "audio_code": rule.audio_file.audio_code,
        "audio_name": rule.audio_file.name,
    }


def create_event_safely(camera, event_type, confidence, payload):
    """
    依目前 Event model 實際存在的欄位建立 Event。

    這樣可以避免因為 Event model 沒有 location_note / message / raw_payload
    而導致 API 測試失敗。
    """

    event_fields = {
        field.name
        for field in Event._meta.get_fields()
        if hasattr(field, "attname")
    }

    event_data = {}

    if "camera" in event_fields:
        event_data["camera"] = camera

    if "event_type" in event_fields:
        event_data["event_type"] = event_type

    if "confidence" in event_fields:
        event_data["confidence"] = confidence

    if "status" in event_fields:
        event_data["status"] = "new"

    if "raw_payload" in event_fields:
        event_data["raw_payload"] = payload

    if "description" in event_fields:
        event_data["description"] = payload.get("message", "")

    if "note" in event_fields:
        event_data["note"] = payload.get("location_note", "")

    return Event.objects.create(**event_data)


def find_broadcast_rules(event_type, camera):
    """
    查找廣播規則。

    優先邏輯：
    1. event_type 相同
    2. is_active=True
    3. auto_broadcast=True
    4. camera 等於目前 camera，或 camera 為空的通用規則
    5. priority 數字越小越優先
    """

    return BroadcastRule.objects.filter(
        event_type=event_type,
        is_active=True,
        auto_broadcast=True,
    ).filter(
        camera__in=[camera, None],
    ).order_by(
        "priority",
        "rule_code",
    )

@login_required
@require_POST
def confirm_event_api(request, event_id):
    """Confirm an event without deleting its history."""

    if not can_process_events(request.user):
        return JsonResponse(
            {
                "success": False,
                "message": "You do not have permission to confirm events.",
            },
            status=403,
        )

    event = get_object_or_404(
        Event.objects.select_related("camera"),
        pk=event_id,
    )

    if event.status in {"dismissed", "closed"}:
        return JsonResponse(
            {
                "success": False,
                "message": "Dismissed or closed events cannot be confirmed.",
                "event": serialize_event_action_result(event),
            },
            status=409,
        )

    if event.status not in {"new", "processing", "confirmed"}:
        return JsonResponse(
            {
                "success": False,
                "message": f"Unsupported event status: {event.status}",
                "event": serialize_event_action_result(event),
            },
            status=409,
        )

    changed = event.status != "confirmed"

    if changed:
        event.status = "confirmed"
        update_fields = ["status"]

        if hasattr(event, "updated_at"):
            update_fields.append("updated_at")

        event.save(update_fields=update_fields)

    return JsonResponse(
        {
            "success": True,
            "message": "Event confirmed successfully.",
            "changed": changed,
            "event": serialize_event_action_result(event),
        }
    )


def serialize_event_action_result(event):
    camera = getattr(event, "camera", None)

    return {
        "id": event.id,
        "status": event.status,
        "status_display": event.get_status_display(),
        "camera_id": getattr(event, "camera_id", None),
        "camera_code": getattr(camera, "camera_code", "") if camera else "",
        "updated_at": event.updated_at.isoformat() if hasattr(event, "updated_at") else None,
    }


@login_required
@require_POST
def close_event_api(request, event_id):
    """Close a confirmed event without deleting its history."""

    if not can_process_events(request.user):
        return JsonResponse(
            {
                "success": False,
                "message": "You do not have permission to close events.",
            },
            status=403,
        )

    event = get_object_or_404(
        Event.objects.select_related("camera"),
        pk=event_id,
    )

    if event.status == "closed":
        return JsonResponse(
            {
                "success": True,
                "message": "Event is already closed.",
                "changed": False,
                "event": serialize_event_action_result(event),
            }
        )

    if event.status not in {"confirmed", "processing"}:
        return JsonResponse(
            {
                "success": False,
                "message": "Only confirmed or processing events can be closed.",
                "event": serialize_event_action_result(event),
            },
            status=409,
        )

    event.status = "closed"
    update_fields = ["status"]

    if hasattr(event, "updated_at"):
        update_fields.append("updated_at")

    event.save(update_fields=update_fields)

    return JsonResponse(
        {
            "success": True,
            "message": "Event closed successfully.",
            "changed": True,
            "event": serialize_event_action_result(event),
        }
    )