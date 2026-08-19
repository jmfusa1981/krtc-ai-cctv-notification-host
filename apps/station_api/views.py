import json

from django.conf import settings
from django.db import transaction
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from apps.ai_bridge.models import AIModel, InferenceConnectionState, InferenceHost
from apps.cameras.models import Camera
from apps.events.models import Event
from apps.notifications.models import SpeakerDevice
from apps.settings_app.models import StationLocalSettings

from .auth import require_occ_token
from .models import ConfigurationAuditLog, InferenceHostConfiguration, OccSyncState


def _iso(value):
    return timezone.localtime(value).isoformat() if value else None


def _identity():
    local = StationLocalSettings.load()
    return {
        "station_code": settings.KRTC_STATION_CODE or local.station_code,
        "notification_host_code": settings.KRTC_NOTIFICATION_HOST_CODE,
    }


@require_GET
def health(request):
    return JsonResponse({**_identity(), "status": "ok", "time": _iso(timezone.now())})


@require_GET
@require_occ_token
def version(request):
    return JsonResponse({**_identity(), "application_version": settings.KRTC_APP_VERSION})


@require_GET
@require_occ_token
def status(request):
    cameras = Camera.objects.all()
    speakers = SpeakerDevice.objects.all()
    latest_event = Event.objects.order_by("-detected_at").first()
    inference = InferenceHost.objects.all()
    local = StationLocalSettings.load()
    sync = OccSyncState.load()
    connection_states = InferenceConnectionState.objects.select_related("inference_host")
    return JsonResponse({
        **_identity(),
        "host_status": "online",
        "inference_hosts": {"total": inference.count(), "online": inference.filter(status="online").count()},
        "inference_connections": [{
            "inference_host_code": item.inference_host.host_code,
            "connected": item.connected,
            "last_heartbeat_at": _iso(item.last_heartbeat_at),
            "last_event_at": _iso(item.last_event_at),
            "last_connected_at": _iso(item.last_connected_at),
            "last_disconnected_at": _iso(item.last_disconnected_at),
            "reconnect_count": item.reconnect_count,
            "last_imported_inference_id": item.last_imported_inference_id,
            "last_source_event_id": item.last_source_event_id,
        } for item in connection_states],
        "cameras": {"total": cameras.count(), "online": cameras.filter(status="online").count()},
        "speakers": {"total": speakers.count(), "online": speakers.filter(status="online").count()},
        "last_event_at": _iso(latest_event.detected_at) if latest_event else None,
        "config_version": str(local.config_version),
        "broadcast_mode": settings.BROADCAST_PLAYBACK_MODE,
        "application_version": settings.KRTC_APP_VERSION,
        "occ_sync": {
            "enabled": settings.KRTC_OCC_SYNC_ENABLED,
            "last_success_at": _iso(sync.last_success_at),
            "last_heartbeat_at": _iso(sync.last_heartbeat_at),
            "last_daily_sync_at": _iso(sync.last_daily_sync_at),
            "last_event_id": sync.last_event_id,
            "consecutive_failures": sync.consecutive_failures,
        },
        "time": _iso(timezone.now()),
    })


@require_GET
@require_occ_token
def inference_hosts(request):
    items = []
    for host in InferenceHost.objects.all():
        cfg = getattr(host, "occ_configuration", None)
        items.append({
            "host_code": host.host_code,
            "name": host.name,
            "base_url": host.base_url,
            "status": host.status,
            "last_success_at": _iso(host.last_success_at),
            "selected_model": cfg.selected_model.model_code if cfg else None,
            "config_version": cfg.config_version if cfg else None,
        })
    return JsonResponse({**_identity(), "items": items})


@require_GET
@require_occ_token
def devices(request):
    camera_items = list(Camera.objects.values("camera_code", "name", "area", "status", "is_active"))
    speaker_items = list(SpeakerDevice.objects.values("speaker_code", "name", "area", "status", "is_active"))
    return JsonResponse({**_identity(), "cameras": camera_items, "speakers": speaker_items})


@require_GET
@require_occ_token
def events(request):
    try:
        limit = min(max(int(request.GET.get("limit", 100)), 1), 500)
    except ValueError:
        return JsonResponse({"detail": "limit must be an integer."}, status=400)
    items = [{
        "id": event.id,
        "source_host": event.source_host,
        "source_event_id": event.source_event_id,
        "camera_code": event.camera_code or (event.camera.camera_code if event.camera else ""),
        "event_id": event.event_id,
        "inference_host_code": event.inference_host_code,
        "event_code": event.event_code,
        "mapping_status": event.mapping_status,
        "video_url": event.video_url,
        "event_type": event.event_type,
        "severity": event.severity,
        "status": event.status,
        "detected_at": _iso(event.detected_at),
        "snapshot_url": event.snapshot_url,
    } for event in Event.objects.select_related("camera").order_by("-detected_at")[:limit]]
    return JsonResponse({**_identity(), "count": len(items), "items": items})


@require_GET
@require_occ_token
def configuration(request):
    local = StationLocalSettings.load()
    host_configs = InferenceHostConfiguration.objects.select_related("inference_host", "selected_model")
    return JsonResponse({
        **_identity(),
        "config_version": str(local.config_version),
        "broadcast_mode": settings.BROADCAST_PLAYBACK_MODE,
        "inference_models": [{
            "inference_host_code": item.inference_host.host_code,
            "model_code": item.selected_model.model_code,
            "config_version": item.config_version,
            "applied_at": _iso(item.applied_at),
        } for item in host_configs],
    })


def _safe_payload(payload):
    blocked = {"token", "api_token", "authorization", "password", "secret"}
    return {key: value for key, value in payload.items() if key.lower() not in blocked}


@csrf_exempt
@require_POST
@require_occ_token
def configuration_apply(request):
    try:
        payload = json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        return JsonResponse({"detail": "Invalid JSON."}, status=400)
    if not isinstance(payload, dict):
        return JsonResponse({"detail": "JSON body must be an object."}, status=400)

    identity = _identity()
    station_code = str(payload.get("station_code") or "")
    pao_code = str(payload.get("notification_host_code") or "")
    host_code = str(payload.get("inference_host_code") or "")
    model_code = str(payload.get("model_code") or "")
    config_version = str(payload.get("config_version") or "")
    operator_code = str(payload.get("operator_code") or "")
    safe_payload = _safe_payload(payload)

    reason = ""
    if station_code != identity["station_code"]:
        reason = "station_code_mismatch"
    elif pao_code != identity["notification_host_code"]:
        reason = "notification_host_code_mismatch"
    elif not all([host_code, model_code, config_version, operator_code]):
        reason = "missing_required_field"

    host = InferenceHost.objects.filter(host_code=host_code, is_active=True).first()
    model = AIModel.objects.filter(model_code=model_code, is_active=True).first()
    if not reason and not host:
        reason = "unknown_inference_host"
    if not reason and not model:
        reason = "unknown_or_inactive_model"

    current = InferenceHostConfiguration.objects.filter(inference_host=host).first() if host else None
    if not reason and current and config_version <= current.config_version:
        reason = "config_version_not_newer"

    audit_values = {
        **identity,
        "inference_host_code": host_code,
        "model_code": model_code,
        "config_version": config_version,
        "operator_code": operator_code,
        "source_address": request.META.get("REMOTE_ADDR") or None,
        "payload": safe_payload,
    }
    if reason:
        ConfigurationAuditLog.objects.create(status="rejected", reason=reason, **audit_values)
        return JsonResponse({"detail": reason}, status=422)

    with transaction.atomic():
        config, _ = InferenceHostConfiguration.objects.update_or_create(
            inference_host=host,
            defaults={"selected_model": model, "config_version": config_version, "applied_by": operator_code},
        )
        local = StationLocalSettings.load()
        local.config_version += 1
        local.last_synced_at = timezone.now()
        local.save(update_fields=["config_version", "last_synced_at", "updated_at"])
        ConfigurationAuditLog.objects.create(status="applied", reason="", **audit_values)
    return JsonResponse({
        **identity,
        "status": "applied",
        "inference_host_code": host.host_code,
        "model_code": model.model_code,
        "config_version": config.config_version,
        "applied_at": _iso(config.applied_at),
    })
