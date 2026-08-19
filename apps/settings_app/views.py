import json
import socket
import time
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from django.apps import apps
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import Group
from django.core.exceptions import PermissionDenied
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.notifications.services import get_broadcast_playback_mode
from .forms import (
    AIModelForm, AudioFileForm, BroadcastRuleForm, BroadcastScheduleForm, CameraForm,
    FrontendUserForm, InferenceCameraMappingForm, InferenceHostForm, SpeakerDeviceForm,
    StationLocalSettingsForm,
)
from .models import StationLocalSettings


STATUS_LABELS = {
    "online": "連線正常",
    "offline": "離線",
    "maintenance": "維護中",
    "error": "異常",
    "unknown": "未知",
}


def get_model_or_none(app_label, model_name):
    try:
        return apps.get_model(app_label, model_name)
    except LookupError:
        return None


def _is_settings_editor(user):
    from apps.accounts.permissions import can_manage_frontend_settings
    return can_manage_frontend_settings(user)


def _can_view_advanced_settings(user):
    from apps.accounts.permissions import can_view_advanced_settings
    return can_view_advanced_settings(user)


def _can_manage_ai_settings(user):
    from apps.accounts.permissions import can_manage_ai_settings
    return can_manage_ai_settings(user)




def _can_manage_accounts(user):
    if not user or not user.is_authenticated:
        return False
    return user.is_superuser or user.groups.filter(name="Administrator").exists()


def _json_body(request):
    try:
        return json.loads(request.body.decode("utf-8") or "{}")
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {}


def _tcp_probe(host, port, timeout=3):
    started = time.perf_counter()
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            elapsed_ms = round((time.perf_counter() - started) * 1000)
            return True, elapsed_ms, f"TCP {host}:{port} 連線成功。"
    except (OSError, ValueError) as exc:
        elapsed_ms = round((time.perf_counter() - started) * 1000)
        return False, elapsed_ms, f"TCP {host}:{port} 連線失敗：{exc}"


def _url_probe(url, timeout=5):
    started = time.perf_counter()
    request = Request(url, headers={"User-Agent": "KRTC-Notification-Host/3"})
    try:
        with urlopen(request, timeout=timeout) as response:
            elapsed_ms = round((time.perf_counter() - started) * 1000)
            status = getattr(response, "status", 200)
            return True, elapsed_ms, f"HTTP {status}，服務回應正常。"
    except Exception as exc:  # diagnostics should return the original reason to UI
        elapsed_ms = round((time.perf_counter() - started) * 1000)
        return False, elapsed_ms, f"服務無法連線：{exc}"


def _safe_stream_endpoint(stream_url):
    """Return host:port only; never expose camera credentials in the UI."""
    if not stream_url:
        return "未設定"
    try:
        parsed = urlparse(stream_url)
        if not parsed.hostname:
            return "格式無效"
        default_ports = {"rtsp": 554, "http": 80, "https": 443}
        port = parsed.port or default_ports.get(parsed.scheme.lower(), 554)
        return f"{parsed.hostname}:{port}"
    except ValueError:
        return "格式無效"


def _audio_file_health(audio):
    if not audio.file:
        return False, "未上傳", "資料庫未綁定任何檔案。"
    try:
        path = Path(audio.file.path)
        relative_name = str(audio.file.name)
        if not path.is_file():
            return False, "檔案遺失", f"預期位置：{relative_name}"
        size = path.stat().st_size
        if size <= 0:
            return False, "空白檔案", f"檔案大小為 0 bytes：{relative_name}"
        return True, f"可用 · {size:,} bytes", f"媒體路徑：{relative_name}"
    except (NotImplementedError, OSError) as exc:
        return False, "無法讀取", f"檔案系統錯誤：{exc}"


@login_required
def station_settings(request):
    """單站通報主機系統設定與診斷頁。"""
    if not _is_settings_editor(request.user):
        raise PermissionDenied("目前帳號沒有系統設定存取權限。")
    local_settings = StationLocalSettings.load()
    if request.method == "POST":
        if not _is_settings_editor(request.user):
            return JsonResponse({"success": False, "message": "權限不足。"}, status=403)
        form = StationLocalSettingsForm(request.POST, instance=local_settings)
        if form.is_valid():
            local_settings = form.save(commit=False)
            local_settings.config_version += 1
            local_settings.save()
            return redirect(f"{reverse('settings_app:station_settings')}?saved=1")
    else:
        form = StationLocalSettingsForm(instance=local_settings)

    InferenceHost = get_model_or_none("ai_bridge", "InferenceHost")
    InferenceCameraMapping = get_model_or_none("ai_bridge", "InferenceCameraMapping")
    AIModel = get_model_or_none("ai_bridge", "AIModel")
    Camera = get_model_or_none("cameras", "Camera")
    SpeakerDevice = get_model_or_none("notifications", "SpeakerDevice")
    AudioFile = get_model_or_none("notifications", "AudioFile")
    BroadcastRule = get_model_or_none("notifications", "BroadcastRule")
    BroadcastLog = get_model_or_none("notifications", "BroadcastLog")
    BroadcastSchedule = get_model_or_none("notifications", "BroadcastSchedule")
    OccSyncState = get_model_or_none("station_api", "OccSyncState")
    OccSyncLog = get_model_or_none("station_api", "OccSyncLog")
    ConfigurationAuditLog = get_model_or_none("station_api", "ConfigurationAuditLog")

    inference_hosts = list(InferenceHost.objects.all().order_by("host_code")) if InferenceHost else []
    for host in inference_hosts:
        host.status_label_zh = STATUS_LABELS.get(host.status, "未知")

    cameras = list(Camera.objects.all().order_by("camera_code")) if Camera else []
    for camera in cameras:
        camera.status_label_zh = STATUS_LABELS.get(camera.status, "未知")
        camera.diagnostic_endpoint = _safe_stream_endpoint(camera.rtsp_url)
        camera.mapping_count = 0

    mappings = list(
        InferenceCameraMapping.objects.select_related("inference_host", "camera").order_by(
            "inference_host__host_code", "source_camera_id"
        )
    ) if InferenceCameraMapping else []
    camera_by_id = {camera.id: camera for camera in cameras}
    for mapping in mappings:
        if mapping.is_active and mapping.camera_id in camera_by_id:
            camera_by_id[mapping.camera_id].mapping_count += 1
        mapping.health_ok = bool(
            mapping.is_active
            and mapping.inference_host.is_active
            and mapping.camera.is_active
        )
        mapping.health_label = "完整" if mapping.health_ok else "需檢查"

    ai_models = list(AIModel.objects.all().order_by("model_code")) if AIModel else []
    for model in ai_models:
        model.health_ok = 0 <= model.confidence_threshold <= 1
        model.health_label = "正常" if model.health_ok else "門檻異常"

    speakers = list(SpeakerDevice.objects.all().order_by("speaker_code")) if SpeakerDevice else []
    for speaker in speakers:
        speaker.status_label_zh = STATUS_LABELS.get(speaker.status, "未知")

    audio_files = list(AudioFile.objects.all().order_by("audio_code")) if AudioFile else []
    audio_health_by_id = {}
    for audio in audio_files:
        audio.health_ok, audio.health_label, audio.health_detail = _audio_file_health(audio)
        audio_health_by_id[audio.id] = audio.health_ok

    broadcast_rules = list(
        BroadcastRule.objects.select_related("camera", "speaker", "audio_file")
        .prefetch_related("speakers")
        .order_by("priority", "rule_code")
    ) if BroadcastRule else []
    for rule in broadcast_rules:
        issues = []
        if not rule.is_active:
            issues.append("規則停用")
        target_speakers = list(rule.target_speakers_queryset())
        rule.speaker_targets_label = "、".join(
            speaker.speaker_code for speaker in target_speakers
        ) or "—"
        if not target_speakers:
            issues.append("未指定 Speaker")
        elif any(not speaker.is_active for speaker in target_speakers):
            issues.append("Speaker 停用")
        if not rule.audio_file.is_active:
            issues.append("音檔停用")
        if not audio_health_by_id.get(rule.audio_file_id, False):
            issues.append("音檔不可用")
        if rule.camera_id and not rule.camera.is_active:
            issues.append("攝影機停用")
        rule.health_ok = not issues
        rule.health_label = "完整" if rule.health_ok else "、".join(issues)
    broadcast_schedules = list(
        BroadcastSchedule.objects.prefetch_related("speakers").select_related("audio_file").order_by("next_run_at", "name")
    ) if BroadcastSchedule else []
    occ_sync_state = OccSyncState.load() if OccSyncState else None
    occ_sync_logs = list(OccSyncLog.objects.all().order_by("-started_at")[:50]) if OccSyncLog else []
    configuration_audit_logs = list(ConfigurationAuditLog.objects.all().order_by("-received_at")[:50]) if ConfigurationAuditLog else []
    recent_broadcast_logs = list(
        BroadcastLog.objects.select_related("event", "speaker", "audio_file", "rule").order_by("-created_at")[:8]
    ) if BroadcastLog else []

    active_camera_count = sum(1 for item in cameras if item.is_active)
    online_camera_count = sum(1 for item in cameras if item.is_active and item.status == "online")
    active_speaker_count = sum(1 for item in speakers if item.is_active)
    online_speaker_count = sum(1 for item in speakers if item.is_active and item.status == "online")
    mapped_active_camera_count = sum(1 for item in cameras if item.is_active and item.mapping_count > 0)
    unmapped_active_cameras = [item for item in cameras if item.is_active and item.mapping_count == 0]
    healthy_mapping_count = sum(1 for item in mappings if item.health_ok)
    healthy_rule_count = sum(1 for item in broadcast_rules if item.health_ok)
    healthy_audio_count = sum(1 for item in audio_files if item.health_ok)

    initial_issues = []
    for host in inference_hosts:
        if host.is_active and host.status != "online":
            initial_issues.append(f"推論主機 {host.host_code}：{host.status_label_zh}")
    for camera in cameras:
        if camera.is_active and camera.status != "online":
            initial_issues.append(f"攝影機 {camera.camera_code}：{camera.status_label_zh}")
        if camera.is_active and camera.mapping_count == 0:
            initial_issues.append(f"攝影機 {camera.camera_code}：尚未建立推論映射")
    for speaker in speakers:
        if speaker.is_active and speaker.status != "online":
            initial_issues.append(f"IP Speaker {speaker.speaker_code}：{speaker.status_label_zh}")
    for audio in audio_files:
        if audio.is_active and not audio.health_ok:
            initial_issues.append(f"音檔 {audio.audio_code}：{audio.health_label}")
    for rule in broadcast_rules:
        if rule.is_active and not rule.health_ok:
            initial_issues.append(f"廣播規則 {rule.rule_code}：{rule.health_label}")

    context = {
        "station_name": local_settings.station_name,
        "local_settings": local_settings,
        "settings_form": form,
        "settings_saved": request.GET.get("saved") == "1",
        "settings_save_failed": request.method == "POST" and not form.is_valid(),
        "server_time": timezone.localtime(timezone.now()),
        "broadcast_playback_mode": get_broadcast_playback_mode(),
        "inference_hosts": inference_hosts,
        "cameras": cameras,
        "mappings": mappings,
        "ai_models": ai_models,
        "speakers": speakers,
        "audio_files": audio_files,
        "broadcast_rules": broadcast_rules,
        "recent_broadcast_logs": recent_broadcast_logs,
        "broadcast_schedules": broadcast_schedules,
        "occ_sync_state": occ_sync_state,
        "occ_sync_logs": occ_sync_logs,
        "configuration_audit_logs": configuration_audit_logs,
        "inference_host_count": len(inference_hosts),
        "active_inference_host_count": sum(1 for item in inference_hosts if item.is_active),
        "camera_count": len(cameras),
        "active_camera_count": active_camera_count,
        "online_camera_count": online_camera_count,
        "speaker_count": len(speakers),
        "active_speaker_count": active_speaker_count,
        "online_speaker_count": online_speaker_count,
        "ai_model_count": len(ai_models),
        "active_ai_model_count": sum(1 for item in ai_models if item.is_active),
        "broadcast_rule_count": len(broadcast_rules),
        "active_broadcast_rule_count": sum(1 for item in broadcast_rules if item.is_active),
        "mapped_active_camera_count": mapped_active_camera_count,
        "unmapped_active_cameras": unmapped_active_cameras,
        "healthy_mapping_count": healthy_mapping_count,
        "healthy_rule_count": healthy_rule_count,
        "healthy_audio_count": healthy_audio_count,
        "initial_issues": initial_issues,
        "initial_issue_count": len(initial_issues),
        "can_edit_settings": _is_settings_editor(request.user),
        "can_open_django_admin": request.user.is_superuser,
        "can_manage_accounts": _can_manage_accounts(request.user),
        "show_advanced_settings": _can_view_advanced_settings(request.user),
        "can_edit_ai_settings": _can_manage_ai_settings(request.user),
    }
    return render(request, "settings_app/station_settings.html", context)


@login_required
@require_POST
def test_inference_host(request):
    InferenceHost = get_model_or_none("ai_bridge", "InferenceHost")
    payload = _json_body(request)
    host = get_object_or_404(InferenceHost, pk=payload.get("id"))
    test_url = f"{host.normalized_base_url}/health"
    ok, elapsed_ms, message = _url_probe(test_url, timeout=min(max(host.timeout_seconds, 1), 20))
    now = timezone.now()
    host.last_health_at = now
    if ok:
        host.status = "online"
        host.last_success_at = now
        host.last_error = ""
    else:
        host.status = "error"
        host.last_error_at = now
        host.last_error = message
    host.save(update_fields=["status", "last_health_at", "last_success_at", "last_error_at", "last_error", "updated_at"])
    return JsonResponse({"success": ok, "message": message, "elapsed_ms": elapsed_ms, "tested_at": timezone.localtime(now).strftime("%Y-%m-%d %H:%M:%S")})


@login_required
@require_POST
def test_camera(request):
    Camera = get_model_or_none("cameras", "Camera")
    payload = _json_body(request)
    camera = get_object_or_404(Camera, pk=payload.get("id"))
    if not camera.rtsp_url:
        return JsonResponse({"success": False, "message": "攝影機尚未設定串流 URL。", "elapsed_ms": 0})

    parsed = urlparse(camera.rtsp_url)
    host = parsed.hostname
    if not host:
        return JsonResponse({"success": False, "message": "串流 URL 格式無效。", "elapsed_ms": 0})
    default_ports = {"rtsp": 554, "http": 80, "https": 443}
    port = parsed.port or default_ports.get(parsed.scheme.lower(), 554)
    ok, elapsed_ms, message = _tcp_probe(host, port)
    camera.status = "online" if ok else "offline"
    camera.is_online = ok
    camera.last_checked_at = timezone.now()
    camera.save(update_fields=["status", "is_online", "last_checked_at"])
    return JsonResponse({"success": ok, "message": message, "elapsed_ms": elapsed_ms, "tested_at": timezone.localtime(camera.last_checked_at).strftime("%Y-%m-%d %H:%M:%S")})


@login_required
@require_POST
def test_speaker(request):
    SpeakerDevice = get_model_or_none("notifications", "SpeakerDevice")
    payload = _json_body(request)
    speaker = get_object_or_404(SpeakerDevice, pk=payload.get("id"))
    ok, elapsed_ms, message = _tcp_probe(str(speaker.ip_address), speaker.port)
    speaker.status = "online" if ok else "offline"
    speaker.last_checked_at = timezone.now()
    speaker.save(update_fields=["status", "last_checked_at", "updated_at"])
    return JsonResponse({"success": ok, "message": message, "elapsed_ms": elapsed_ms, "tested_at": timezone.localtime(speaker.last_checked_at).strftime("%Y-%m-%d %H:%M:%S")})


@login_required
@require_POST
def test_audio_file(request):
    AudioFile = get_model_or_none("notifications", "AudioFile")
    payload = _json_body(request)
    audio = get_object_or_404(AudioFile, pk=payload.get("id"))
    started = time.perf_counter()
    if not audio.file:
        return JsonResponse({"success": False, "message": "尚未上傳音檔。", "elapsed_ms": 0})
    try:
        file_path = Path(audio.file.path)
        relative_name = str(audio.file.name)
        ok = file_path.is_file() and file_path.stat().st_size > 0
        elapsed_ms = round((time.perf_counter() - started) * 1000)
        if ok:
            message = f"音檔可讀，大小 {file_path.stat().st_size:,} bytes；路徑 {relative_name}。"
        else:
            media_root = Path(settings.MEDIA_ROOT)
            message = f"音檔不存在或內容為空；請確認 {media_root / relative_name}。"
    except (NotImplementedError, OSError) as exc:
        ok = False
        elapsed_ms = round((time.perf_counter() - started) * 1000)
        message = f"音檔檢查失敗：{exc}"
    return JsonResponse({"success": ok, "message": message, "elapsed_ms": elapsed_ms, "tested_at": timezone.localtime(timezone.now()).strftime("%Y-%m-%d %H:%M:%S")})


@login_required
@require_POST
def test_maintenance_host(request):
    local_settings = StationLocalSettings.load()
    payload = _json_body(request)
    maintenance_host_url = (payload.get("url") or local_settings.maintenance_host_url or "").strip()
    if not maintenance_host_url:
        return JsonResponse({"success": False, "message": "尚未設定中央維護主機 URL。", "elapsed_ms": 0})
    parsed = urlparse(maintenance_host_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return JsonResponse({"success": False, "message": "中央維護主機 URL 格式無效。", "elapsed_ms": 0})
    test_url = f"{maintenance_host_url.rstrip('/')}/health"
    ok, elapsed_ms, message = _url_probe(test_url, timeout=5)
    return JsonResponse({"success": ok, "message": message, "elapsed_ms": elapsed_ms, "tested_at": timezone.localtime(timezone.now()).strftime("%Y-%m-%d %H:%M:%S")})


@login_required
@require_POST
def save_speaker(request):
    if not _is_settings_editor(request.user):
        return JsonResponse({"success": False, "message": "權限不足。"}, status=403)

    payload = request.POST
    speaker_id = payload.get("id")
    speaker = None
    if speaker_id:
        SpeakerDevice = get_model_or_none("notifications", "SpeakerDevice")
        speaker = get_object_or_404(SpeakerDevice, pk=speaker_id)

    form = SpeakerDeviceForm(payload, instance=speaker)
    if not form.is_valid():
        return JsonResponse(
            {"success": False, "message": "請修正設備設定。", "errors": form.errors.get_json_data()},
            status=400,
        )

    speaker = form.save()
    return JsonResponse({
        "success": True,
        "message": f"{speaker.speaker_code} 已儲存。",
        "speaker": {
            "id": speaker.id,
            "speaker_code": speaker.speaker_code,
            "name": speaker.name,
            "area": speaker.area,
            "network_mode": speaker.network_mode,
            "network_mode_label": speaker.get_network_mode_display(),
            "ip_address": str(speaker.ip_address),
            "port": speaker.port,
            "username": speaker.username,
            "preferred_codec": speaker.preferred_codec,
            "preferred_codec_label": speaker.get_preferred_codec_display(),
            "sip_uri": speaker.resolved_sip_uri,
            "is_active": speaker.is_active,
        },
    })

MANAGEMENT_REGISTRY = {
    "inference-host": {
        "model": ("ai_bridge", "InferenceHost"),
        "form": InferenceHostForm,
        "title": "推論主機",
        "plural": "推論主機",
        "tab": "hosts",
    },
    "camera": {
        "model": ("cameras", "Camera"),
        "form": CameraForm,
        "title": "攝影機",
        "plural": "攝影機",
        "tab": "devices",
    },
    "camera-mapping": {
        "model": ("ai_bridge", "InferenceCameraMapping"),
        "form": InferenceCameraMappingForm,
        "title": "Camera ID 映射",
        "plural": "Camera ID 映射",
        "tab": "ai",
    },
    "ai-model": {
        "model": ("ai_bridge", "AIModel"),
        "form": AIModelForm,
        "title": "AI 模型",
        "plural": "AI 模型",
        "tab": "ai",
    },
    "audio-file": {
        "model": ("notifications", "AudioFile"),
        "form": AudioFileForm,
        "title": "廣播音檔",
        "plural": "廣播音檔",
        "tab": "broadcast",
    },
    "broadcast-rule": {
        "model": ("notifications", "BroadcastRule"),
        "form": BroadcastRuleForm,
        "title": "廣播規則",
        "plural": "廣播規則",
        "tab": "broadcast",
    },
    "broadcast-schedule": {
        "model": ("notifications", "BroadcastSchedule"),
        "form": BroadcastScheduleForm,
        "title": "廣播排程",
        "plural": "廣播排程",
        "tab": "broadcast",
    },
}


def _management_config(kind):
    config = MANAGEMENT_REGISTRY.get(kind)
    if not config:
        raise PermissionDenied("不支援的設定類型。")
    return config


@login_required
def manage_object(request, kind, object_id=None):
    """Create or edit operational configuration without exposing Django admin."""
    if not _is_settings_editor(request.user):
        raise PermissionDenied("目前帳號沒有修改系統設定的權限。")

    config = _management_config(kind)
    if kind in {"ai-model", "camera-mapping"} and not _can_manage_ai_settings(request.user):
        raise PermissionDenied("目前帳號只有 AI / 映射檢視權限，不能修改。")
    Model = get_model_or_none(*config["model"])
    instance = get_object_or_404(Model, pk=object_id) if object_id else None
    FormClass = config["form"]

    # BroadcastRule is now managed from the station broadcast console.
    # Keep the existing management form, but allow that console to be the
    # explicit return target without introducing a generic open redirect.
    return_to = request.POST.get("return_to") if request.method == "POST" else request.GET.get("return_to")
    if return_to != "broadcast" or kind != "broadcast-rule":
        return_to = ""

    if request.method == "POST":
        form = FormClass(request.POST, request.FILES, instance=instance)
        if form.is_valid():
            saved = form.save(commit=False)
            if kind == "broadcast-schedule":
                if not saved.pk and hasattr(saved, "created_by"):
                    saved.created_by = request.user
                saved.next_run_at = saved.calculate_next_run()
            saved.save()
            if hasattr(form, "save_m2m"):
                form.save_m2m()
            if return_to == "broadcast":
                return redirect(f"{reverse('dashboard:station_broadcast')}?saved=1#auto-broadcast-rules")
            return redirect(
                f"{reverse('settings_app:station_settings')}?saved=1&tab={config['tab']}#management-saved"
            )
    else:
        form = FormClass(instance=instance)

    return render(request, "settings_app/manage_object.html", {
        "form": form,
        "kind": kind,
        "object": instance,
        "management_title": config["title"],
        "management_plural": config["plural"],
        "return_tab": config["tab"],
        "return_to": return_to,
        "station_name": StationLocalSettings.load().station_name,
    })


@login_required
@require_POST
def remove_object(request, kind, object_id):
    """Delete editable operational settings from the maintenance UI."""
    if not _is_settings_editor(request.user):
        raise PermissionDenied("目前帳號沒有修改系統設定的權限。")
    config = _management_config(kind)
    if kind != "broadcast-rule":
        raise PermissionDenied("此設定類型不支援在維運頁刪除。")
    Model = get_model_or_none(*config["model"])
    instance = get_object_or_404(Model, pk=object_id)
    instance.delete()
    if kind == "broadcast-rule" and request.POST.get("return_to") == "broadcast":
        return redirect(f"{reverse('dashboard:station_broadcast')}?saved=1#auto-broadcast-rules")
    return redirect(f"{reverse('settings_app:station_settings')}?saved=1&tab={config['tab']}")


@login_required
@require_POST
def toggle_object(request, kind, object_id):
    """Disable/enable objects instead of deleting operational history."""
    if not _is_settings_editor(request.user):
        raise PermissionDenied("目前帳號沒有修改系統設定的權限。")
    config = _management_config(kind)
    if kind in {"ai-model", "camera-mapping"} and not _can_manage_ai_settings(request.user):
        raise PermissionDenied("目前帳號只有 AI / 映射檢視權限，不能修改。")
    Model = get_model_or_none(*config["model"])
    instance = get_object_or_404(Model, pk=object_id)
    if not hasattr(instance, "is_active"):
        return JsonResponse({"success": False, "message": "此設定不支援啟用／停用。"}, status=400)
    instance.is_active = not instance.is_active
    instance.save(update_fields=["is_active", "updated_at"] if hasattr(instance, "updated_at") else ["is_active"])
    return redirect(f"{reverse('settings_app:station_settings')}?tab={config['tab']}")



@login_required
def user_management(request):
    if not _can_manage_accounts(request.user):
        raise PermissionDenied("只有系統管理員或 Superuser 可以管理使用者。")

    users = list(
        get_user_model().objects.filter(is_superuser=False)
        .prefetch_related("groups")
        .order_by("username")
    )
    for account in users:
        account.frontend_role = (
            account.groups.filter(name__in=["Operator", "Maintainer", "Administrator"])
            .values_list("name", flat=True)
            .first()
            or "未指派"
        )

    return render(request, "settings_app/user_management.html", {
        "frontend_users": users,
        "settings_saved": request.GET.get("saved") == "1",
        "server_time": timezone.localtime(timezone.now()),
        "broadcast_playback_mode": get_broadcast_playback_mode(),
        "station_name": StationLocalSettings.load().station_name,
    })


@login_required
@require_POST
def remove_user(request, object_id):
    if not _can_manage_accounts(request.user):
        raise PermissionDenied("只有系統管理員或 Superuser 可以移除使用者。")
    user = get_object_or_404(get_user_model(), pk=object_id, is_superuser=False)
    if user.pk == request.user.pk:
        return JsonResponse({"success": False, "message": "不可移除目前登入帳號。"}, status=400)
    user.is_active = False
    user.save(update_fields=["is_active"])
    return redirect(reverse("settings_app:user_management"))

@login_required
def manage_user(request, object_id=None):
    if not _can_manage_accounts(request.user):
        raise PermissionDenied("只有 Administrator 或 Superuser 可以管理帳號。")
    User = get_user_model()
    instance = get_object_or_404(User, pk=object_id, is_superuser=False) if object_id else None
    if request.method == "POST":
        form = FrontendUserForm(request.POST, user_instance=instance)
        if form.is_valid():
            user = instance or User()
            user.username = form.cleaned_data["username"]
            user.first_name = form.cleaned_data["first_name"]
            user.email = form.cleaned_data["email"]
            user.is_active = form.cleaned_data["is_active"]
            user.is_staff = False
            user.is_superuser = False
            password = form.cleaned_data.get("password")
            if password:
                user.set_password(password)
            user.save()
            role_group, _ = Group.objects.get_or_create(name=form.cleaned_data["role"])
            user.groups.set([role_group])
            return redirect(f"{reverse('settings_app:user_management')}?saved=1")
    else:
        form = FrontendUserForm(user_instance=instance)
    return render(request, "settings_app/manage_object.html", {
        "form": form,
        "kind": "user",
        "object": instance,
        "management_title": "使用者帳號",
        "management_plural": "使用者管理",
        "return_tab": "users",
        "return_url_name": "settings_app:user_management",
        "station_name": StationLocalSettings.load().station_name,
    })


@login_required
@require_POST
def toggle_user(request, object_id):
    if not _can_manage_accounts(request.user):
        raise PermissionDenied("只有 Administrator 或 Superuser 可以管理帳號。")
    user = get_object_or_404(get_user_model(), pk=object_id, is_superuser=False)
    if user.pk == request.user.pk:
        return JsonResponse({"success": False, "message": "不可停用目前登入帳號。"}, status=400)
    user.is_active = not user.is_active
    user.save(update_fields=["is_active"])
    return redirect(reverse("settings_app:user_management"))
