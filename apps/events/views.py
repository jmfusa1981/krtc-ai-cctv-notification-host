import json
import logging

from django.contrib.auth.decorators import login_required
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.http import FileResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from apps.accounts.permissions import can_process_events
from apps.cameras.models import Camera
from apps.events.models import Event, EventRecordingEvidence, LocalAlarmPolicy
from apps.events.services.nvr_recording import (
    NvrRecordingError,
    create_recording_evidence,
    refresh_export_status,
)
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
        speakers = list(rule.target_speakers_queryset(active_only=True))
        if not speakers:
            broadcast_logs.append(serialize_missing_speaker_result(rule))
            continue

        for speaker in speakers:
            active_log = BroadcastLog.objects.filter(
                speaker=speaker,
                status__in=[
                    BroadcastLog.STATUS_PENDING,
                    BroadcastLog.STATUS_PLAYING,
                ],
            ).order_by("created_at").first()

            if active_log is not None:
                broadcast_logs.append(
                    serialize_busy_broadcast_result(rule, speaker, active_log)
                )
                continue

            try:
                with transaction.atomic():
                    broadcast_log = BroadcastLog.objects.create(
                        event=event,
                        rule=rule,
                        speaker=speaker,
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
                            "speaker_code": speaker.speaker_code,
                            "speaker_sip_uri": speaker.resolved_sip_uri,
                            "audio_code": rule.audio_file.audio_code,
                            "audio_name": rule.audio_file.name,
                            "target_speaker_count": len(speakers),
                            "raw_payload": payload,
                        },
                        message="Automatic broadcast task created.",
                        requested_at=timezone.now(),
                    )
            except IntegrityError:
                active_log = BroadcastLog.objects.filter(
                    speaker=speaker,
                    status__in=[
                        BroadcastLog.STATUS_PENDING,
                        BroadcastLog.STATUS_PLAYING,
                    ],
                ).order_by("created_at").first()
                broadcast_logs.append(
                    serialize_busy_broadcast_result(rule, speaker, active_log)
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
                    "speaker_code": speaker.speaker_code,
                    "speaker_sip_uri": speaker.resolved_sip_uri,
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


def serialize_busy_broadcast_result(rule, speaker, active_log):
    """Return a stable API result when the target Speaker is already busy."""

    return {
        "id": None,
        "status": BroadcastLog.STATUS_SKIPPED,
        "message": "Speaker already has a pending or playing broadcast.",
        "mode": get_broadcast_playback_mode(),
        "reason": "speaker_busy",
        "active_broadcast_log_id": active_log.id if active_log else None,
        "rule_code": rule.rule_code,
        "speaker_code": speaker.speaker_code,
        "speaker_sip_uri": speaker.resolved_sip_uri,
        "audio_code": rule.audio_file.audio_code,
        "audio_name": rule.audio_file.name,
    }


def serialize_missing_speaker_result(rule):
    return {
        "id": None,
        "status": BroadcastLog.STATUS_SKIPPED,
        "message": "BroadcastRule has no active speaker target.",
        "mode": get_broadcast_playback_mode(),
        "reason": "speaker_missing",
        "rule_code": rule.rule_code,
        "speaker_code": "",
        "speaker_sip_uri": "",
        "audio_code": rule.audio_file.audio_code if rule.audio_file else "",
        "audio_name": rule.audio_file.name if rule.audio_file else "",
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
    ).filter(
        Q(speakers__is_active=True) | Q(speaker__is_active=True)
    ).prefetch_related("speakers").distinct().order_by(
        "priority",
        "rule_code",
    )


@login_required
@require_POST
def request_event_recording_api(request, event_id):
    """Create a NVR evidence export for event T-30s to T+90s."""

    if not can_process_events(request.user):
        return JsonResponse(
            {
                "success": False,
                "message": "You do not have permission to request recordings.",
            },
            status=403,
        )

    event = get_object_or_404(
        Event.objects.select_related("camera"),
        pk=event_id,
    )

    try:
        evidence = create_recording_evidence(
            event,
            force_new=request.POST.get("force_new") == "1",
        )
    except NvrRecordingError as exc:
        return _recording_response(
            request,
            {
                "success": False,
                "message": str(exc),
                "event_id": event.id,
            },
            status=400,
        )

    return _recording_response(
        request,
        {
            "success": True,
            "message": "Event recording evidence request processed.",
            "recording": serialize_recording_evidence(evidence),
        },
        status=201,
    )


@login_required
@require_POST
def refresh_event_recording_api(request, evidence_id):
    """Refresh a pending NVR export and download it after completion."""

    if not can_process_events(request.user):
        return JsonResponse(
            {
                "success": False,
                "message": "You do not have permission to refresh recordings.",
            },
            status=403,
        )

    evidence = get_object_or_404(
        EventRecordingEvidence.objects.select_related("event", "camera"),
        pk=evidence_id,
    )

    evidence = refresh_export_status(evidence)
    return _recording_response(
        request,
        {
            "success": evidence.export_status != EventRecordingEvidence.STATUS_FAILED,
            "message": "Event recording evidence status refreshed.",
            "recording": serialize_recording_evidence(evidence),
        },
    )


@login_required
def play_event_recording(request, evidence_id):
    """Stream a completed PAO-local MP4 inline for HTML5 video playback."""

    evidence = get_object_or_404(EventRecordingEvidence, pk=evidence_id)
    if not _local_mp4_ready(evidence):
        return JsonResponse(
            {
                "success": False,
                "message": "PAO local MP4 is not ready for playback.",
                "recording": serialize_recording_evidence(evidence),
            },
            status=404,
        )

    evidence.file.open("rb")
    filename = evidence.file_name or evidence.file.name.rsplit("/", 1)[-1]
    response = FileResponse(evidence.file, content_type="video/mp4")
    response["Content-Disposition"] = f'inline; filename="{filename}"'
    response["Cache-Control"] = "no-store"
    return response


def _local_mp4_ready(evidence):
    """Return True only when the completed recording is a real local MP4."""

    if evidence.export_status != EventRecordingEvidence.STATUS_COMPLETED:
        return False
    if not evidence.file or not evidence.file.name:
        return False
    if not evidence.file.name.lower().endswith(".mp4"):
        return False
    try:
        return evidence.file.storage.exists(evidence.file.name)
    except Exception:
        logger.exception(
            "Unable to verify local event recording. evidence_id=%s",
            evidence.id,
        )
        return False


@login_required
def download_event_recording(request, evidence_id):
    """Download a completed PAO-local MP4 as a browser attachment."""

    evidence = get_object_or_404(EventRecordingEvidence, pk=evidence_id)
    if _local_mp4_ready(evidence):
        evidence.file.open("rb")
        filename = evidence.file_name or evidence.file.name.rsplit("/", 1)[-1]
        return FileResponse(
            evidence.file,
            as_attachment=True,
            filename=filename,
            content_type="video/mp4",
        )

    # Compatibility fallback for historical records that only retained an external URL.
    if evidence.download_url:
        return redirect(evidence.download_url)

    return JsonResponse(
        {
            "success": False,
            "message": "PAO local MP4 is not downloadable yet.",
            "recording": serialize_recording_evidence(evidence),
        },
        status=404,
    )


def _recording_response(request, payload, *, status=200):
    next_url = request.POST.get("next") or request.GET.get("next")
    wants_html = "text/html" in request.headers.get("Accept", "")
    if next_url and wants_html:
        return redirect(next_url)
    return JsonResponse(payload, status=status)


def serialize_recording_evidence(evidence):
    return {
        "id": evidence.id,
        "event_id": evidence.event_id,
        "camera_code": evidence.camera.camera_code if evidence.camera else "",
        "nvr_host": evidence.nvr_host,
        "nvr_channel": evidence.nvr_channel,
        "evidence_start_at": evidence.evidence_start_at.isoformat(),
        "evidence_end_at": evidence.evidence_end_at.isoformat(),
        "pre_event_seconds": evidence.pre_event_seconds,
        "post_event_seconds": evidence.post_event_seconds,
        "export_id": evidence.export_id,
        "export_status": evidence.export_status,
        "export_status_display": evidence.get_export_status_display(),
        "export_rate": evidence.export_rate,
        "file_name": evidence.file_name,
        "download_url": evidence.file.url if evidence.file else evidence.download_url,
        "last_error": evidence.last_error,
        "requested_at": evidence.requested_at.isoformat() if evidence.requested_at else None,
        "completed_at": evidence.completed_at.isoformat() if evidence.completed_at else None,
    }


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


@login_required
@require_POST
def close_active_alarm_events_api(request):
    """Close every event that is currently driving the Dashboard alarm."""

    if not can_process_events(request.user):
        return JsonResponse(
            {
                "success": False,
                "message": "You do not have permission to close events.",
            },
            status=403,
        )

    active_statuses = {"new", "processing", "confirmed"}
    policy = LocalAlarmPolicy.load()
    events = Event.objects.filter(status__in=active_statuses)

    if policy.is_enabled:
        events = events.filter(created_at__gte=policy.enabled_at)
    else:
        events = events.none()

    event_ids = list(events.order_by("id").values_list("id", flat=True))

    if not event_ids:
        return JsonResponse(
            {
                "success": True,
                "message": "No active alarm events to close.",
                "changed": False,
                "closed_count": 0,
                "closed_event_ids": [],
            }
        )

    update_values = {"status": "closed"}

    if any(field.name == "updated_at" for field in Event._meta.fields):
        update_values["updated_at"] = timezone.now()

    now = timezone.now()

    with transaction.atomic():
        closed_count = Event.objects.filter(pk__in=event_ids).update(**update_values)

        # Cancel broadcast jobs that have not started yet. Closing an event is
        # an operator decision and pending automatic jobs must not continue to
        # play after the Dashboard alarm has been cleared.
        cancelled_broadcast_count = BroadcastLog.objects.filter(
            event_id__in=event_ids,
            status=BroadcastLog.STATUS_PENDING,
        ).update(
            status=BroadcastLog.STATUS_SKIPPED,
            message="Cancelled because the related event was closed by the operator.",
            finished_at=now,
            updated_at=now,
        )

    return JsonResponse(
        {
            "success": True,
            "message": "Active alarm events closed successfully.",
            "changed": closed_count > 0,
            "closed_count": closed_count,
            "closed_event_ids": event_ids,
            "cancelled_broadcast_count": cancelled_broadcast_count,
        }
    )
