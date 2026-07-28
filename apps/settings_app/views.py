import json
import socket
import time
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from django.apps import apps
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.notifications.services import get_broadcast_playback_mode
from .forms import SpeakerDeviceForm, StationLocalSettingsForm
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
    return user.is_staff or user.is_superuser


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
        BroadcastRule.objects.select_related("camera", "speaker", "audio_file").order_by("priority", "rule_code")
    ) if BroadcastRule else []
    for rule in broadcast_rules:
        issues = []
        if not rule.is_active:
            issues.append("規則停用")
        if not rule.speaker.is_active:
            issues.append("Speaker 停用")
        if not rule.audio_file.is_active:
            issues.append("音檔停用")
        if not audio_health_by_id.get(rule.audio_file_id, False):
            issues.append("音檔不可用")
        if rule.camera_id and not rule.camera.is_active:
            issues.append("攝影機停用")
        rule.health_ok = not issues
        rule.health_label = "完整" if rule.health_ok else "、".join(issues)
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
        "can_open_django_admin": request.user.is_staff,
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
