import json

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from apps.accounts.permissions import can_process_events
from apps.cameras.models import Camera
from apps.events.models import Event
from apps.notifications.models import BroadcastLog, BroadcastRule


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
    6. 回傳事件與廣播任務建立結果

    注意：
    本階段只建立 BroadcastLog，不實際播放 IP Speaker。
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

    event = create_event_safely(
        camera=camera,
        event_type=event_type,
        confidence=confidence,
        payload=payload,
    )

    matched_rules = find_broadcast_rules(
        event_type=event_type,
        camera=camera,
    )

    broadcast_logs = []

    for rule in matched_rules:
        broadcast_log = BroadcastLog.objects.create(
            event=event,
            rule=rule,
            speaker=rule.speaker,
            audio_file=rule.audio_file,
            status=BroadcastLog.STATUS_PENDING,
            request_payload={
                "source": "ai_event_trigger_api",
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
            message="Broadcast task created. IP Speaker playback integration pending.",
            requested_at=timezone.now(),
        )

        broadcast_logs.append(
            {
                "id": broadcast_log.id,
                "status": broadcast_log.status,
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
                "matched_rule_count": matched_rules.count(),
                "created_log_count": len(broadcast_logs),
                "logs": broadcast_logs,
            },
        },
        status=201,
    )


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
