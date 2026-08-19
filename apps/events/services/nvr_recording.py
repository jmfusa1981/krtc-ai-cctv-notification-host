from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlunsplit
from urllib.request import Request, urlopen

from django.conf import settings
from django.core.files.base import ContentFile
from django.utils import timezone

from apps.events.models import Event, EventRecordingEvidence


class NvrRecordingError(RuntimeError):
    pass


@dataclass(frozen=True)
class NvrConfig:
    host: str
    port: int
    username: str
    password: str
    channel: int
    video_format: str


def _local_nvr_timestamp(value):
    return timezone.localtime(value).strftime("%Y-%m-%dT%H:%M:%S")


def _mask_url(url: str) -> str:
    if "://" not in url or "@" not in url:
        return url
    scheme, rest = url.split("://", 1)
    _userinfo, host_path = rest.split("@", 1)
    return f"{scheme}://***:***@{host_path}"


def _build_nvr_url(config: NvrConfig, params: dict[str, str | int]) -> str:
    username = quote(config.username, safe="")
    password = quote(config.password, safe="")
    netloc = f"{username}:{password}@{config.host}:{config.port}"
    return urlunsplit(("http", netloc, "/export.cgi", urlencode(params), ""))


def _camera_nvr_config(event: Event) -> NvrConfig:
    camera = event.camera
    if camera is None:
        raise NvrRecordingError("事件尚未綁定攝影機，無法建立 NVR 錄影證據。")
    if not getattr(camera, "nvr_recording_enabled", True):
        raise NvrRecordingError(f"攝影機 {camera.camera_code} 未啟用 NVR 錄影匯出。")

    mode = getattr(settings, "KRTC_NVR_RECORDING_MODE", "simulation").strip().lower()
    host = (camera.nvr_host or getattr(settings, "KRTC_NVR_DEFAULT_HOST", "")).strip()
    username = (
        camera.nvr_username or getattr(settings, "KRTC_NVR_DEFAULT_USERNAME", "")
    ).strip()
    password = camera.nvr_password or getattr(settings, "KRTC_NVR_DEFAULT_PASSWORD", "")
    port = camera.nvr_port or getattr(settings, "KRTC_NVR_DEFAULT_PORT", 80)
    channel = camera.nvr_channel

    if mode == "simulation":
        host = host or "SIMULATION-NVR"
        username = username or "simulation"
        channel = channel if channel is not None else camera.id

    if not host:
        raise NvrRecordingError(f"攝影機 {camera.camera_code} 缺少 NVR Host。")
    if channel is None:
        raise NvrRecordingError(f"攝影機 {camera.camera_code} 缺少 NVR Channel。")
    if not username:
        raise NvrRecordingError(f"攝影機 {camera.camera_code} 缺少 NVR 帳號。")

    return NvrConfig(
        host=host,
        port=int(port),
        username=username,
        password=password,
        channel=int(channel),
        video_format=getattr(settings, "KRTC_NVR_EXPORT_FORMAT", "MP4").upper(),
    )


def _request_json(url: str, timeout: int) -> dict:
    request = Request(url, headers={"Accept": "application/json"})
    try:
        with urlopen(request, timeout=timeout) as response:
            body = response.read()
    except HTTPError as exc:
        raise NvrRecordingError(f"NVR HTTP {exc.code}: {exc.reason}") from exc
    except URLError as exc:
        raise NvrRecordingError(f"NVR 連線失敗：{exc.reason}") from exc
    except TimeoutError as exc:
        raise NvrRecordingError("NVR 連線逾時。") from exc

    if not body:
        return {}
    try:
        return json.loads(body.decode("utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise NvrRecordingError("NVR 回應不是有效 JSON。") from exc


def _download_bytes(url: str, timeout: int) -> tuple[str, bytes]:
    request = Request(url)
    try:
        with urlopen(request, timeout=timeout) as response:
            body = response.read()
            disposition = response.headers.get("Content-Disposition", "")
    except HTTPError as exc:
        raise NvrRecordingError(f"NVR HTTP {exc.code}: {exc.reason}") from exc
    except URLError as exc:
        raise NvrRecordingError(f"NVR 下載失敗：{exc.reason}") from exc

    filename = ""
    if "filename=" in disposition:
        filename = disposition.split("filename=", 1)[1].strip().strip('"')
    return filename, body


def create_recording_evidence(
    event: Event,
    *,
    pre_seconds: int | None = None,
    post_seconds: int | None = None,
    force_new: bool = False,
) -> EventRecordingEvidence:
    pre_seconds = pre_seconds or getattr(settings, "KRTC_NVR_PRE_EVENT_SECONDS", 30)
    post_seconds = post_seconds or getattr(settings, "KRTC_NVR_POST_EVENT_SECONDS", 90)
    start_at = event.detected_at - timedelta(seconds=pre_seconds)
    end_at = event.detected_at + timedelta(seconds=post_seconds)

    if not force_new:
        existing = event.recording_evidences.order_by("-created_at").first()
        if existing and existing.export_status != EventRecordingEvidence.STATUS_FAILED:
            return existing

    config = _camera_nvr_config(event)
    evidence = EventRecordingEvidence.objects.create(
        event=event,
        camera=event.camera,
        nvr_host=config.host,
        nvr_port=config.port,
        nvr_channel=config.channel,
        video_format=config.video_format,
        pre_event_seconds=pre_seconds,
        post_event_seconds=post_seconds,
        evidence_start_at=start_at,
        evidence_end_at=end_at,
        request_payload={
            "source": "KRTC command document 260727 NVR export.cgi",
            "event_id": event.id,
            "source_event_id": event.source_event_id,
            "camera_code": event.camera.camera_code if event.camera else "",
            "nvr_host": config.host,
            "nvr_channel": config.channel,
            "start_time": _local_nvr_timestamp(start_at),
            "end_time": _local_nvr_timestamp(end_at),
            "format": config.video_format,
            "pre_event_seconds": pre_seconds,
            "post_event_seconds": post_seconds,
        },
    )
    request_export(evidence, config=config)
    return evidence


def request_export(
    evidence: EventRecordingEvidence,
    *,
    config: NvrConfig | None = None,
) -> EventRecordingEvidence:
    mode = getattr(settings, "KRTC_NVR_RECORDING_MODE", "simulation").strip().lower()
    if mode == "simulation":
        return _complete_simulated_evidence(evidence)

    config = config or _camera_nvr_config(evidence.event)
    timeout = getattr(settings, "KRTC_NVR_REQUEST_TIMEOUT", 10)
    url = _build_nvr_url(
        config,
        {
            "channel": config.channel,
            "start_time": _local_nvr_timestamp(evidence.evidence_start_at),
            "end_time": _local_nvr_timestamp(evidence.evidence_end_at),
            "format": evidence.video_format,
        },
    )
    evidence.requested_at = timezone.now()
    evidence.request_payload = {
        **evidence.request_payload,
        "method": "GET",
        "url": _mask_url(url),
    }

    try:
        payload = _request_json(url, timeout)
        export_id = payload.get("ID") or payload.get("id")
        if not export_id:
            raise NvrRecordingError(payload.get("message") or "NVR 未回傳匯出 ID。")
        evidence.export_id = str(export_id)
        evidence.export_status = EventRecordingEvidence.STATUS_REQUESTED
        evidence.response_payload = payload
        evidence.last_error = ""
    except NvrRecordingError as exc:
        evidence.export_status = EventRecordingEvidence.STATUS_FAILED
        evidence.last_error = str(exc)

    evidence.save()
    return evidence


def refresh_export_status(evidence: EventRecordingEvidence) -> EventRecordingEvidence:
    mode = getattr(settings, "KRTC_NVR_RECORDING_MODE", "simulation").strip().lower()
    if mode == "simulation":
        return _complete_simulated_evidence(evidence)

    if not evidence.export_id:
        evidence.export_status = EventRecordingEvidence.STATUS_FAILED
        evidence.last_error = "尚未取得 NVR 匯出 ID。"
        evidence.save()
        return evidence

    config = _camera_nvr_config(evidence.event)
    timeout = getattr(settings, "KRTC_NVR_REQUEST_TIMEOUT", 10)
    url = _build_nvr_url(config, {"ID": evidence.export_id})

    try:
        payload = _request_json(url, timeout)
        status = int(payload.get("Status", 0))
        evidence.ffmpeg_status = payload.get("FFmpeg")
        evidence.export_rate = max(0, min(100, int(payload.get("Rate", 0))))
        evidence.response_payload = payload
        if status == 1:
            return download_completed_export(evidence, config=config)
        if status == -1:
            raise NvrRecordingError("NVR 匯出 ID 不存在。")
        evidence.export_status = EventRecordingEvidence.STATUS_EXPORTING
        evidence.last_error = ""
    except (ValueError, TypeError) as exc:
        evidence.export_status = EventRecordingEvidence.STATUS_FAILED
        evidence.last_error = f"NVR 匯出狀態格式錯誤：{exc}"
    except NvrRecordingError as exc:
        evidence.export_status = EventRecordingEvidence.STATUS_FAILED
        evidence.last_error = str(exc)

    evidence.save()
    return evidence


def download_completed_export(
    evidence: EventRecordingEvidence,
    *,
    config: NvrConfig | None = None,
) -> EventRecordingEvidence:
    config = config or _camera_nvr_config(evidence.event)
    timeout = getattr(settings, "KRTC_NVR_REQUEST_TIMEOUT", 10)
    url = _build_nvr_url(config, {"ID": evidence.export_id, "action": "download"})

    filename, body = _download_bytes(url, timeout)
    if not body:
        raise NvrRecordingError("NVR 下載回應為空。")
    if not filename:
        extension = evidence.video_format.lower()
        filename = _evidence_file_name(evidence, extension=extension)

    evidence.file.save(filename, ContentFile(body), save=False)
    evidence.file_name = filename
    evidence.download_url = ""
    evidence.export_rate = 100
    evidence.export_status = EventRecordingEvidence.STATUS_COMPLETED
    evidence.completed_at = timezone.now()
    evidence.last_error = ""
    evidence.save()
    if evidence.event.video_url == "":
        evidence.event.video_url = evidence.file.url
        evidence.event.save(update_fields=["video_url", "updated_at"])
    return evidence


def _complete_simulated_evidence(
    evidence: EventRecordingEvidence,
) -> EventRecordingEvidence:
    filename = _evidence_file_name(evidence, extension="txt")
    content = "\n".join(
        [
            "KRTC PAO simulated NVR recording evidence",
            f"event_id={evidence.event_id}",
            f"source_event_id={evidence.event.source_event_id or ''}",
            f"camera_code={evidence.camera.camera_code if evidence.camera else ''}",
            f"nvr_host={evidence.nvr_host}",
            f"nvr_channel={evidence.nvr_channel}",
            f"detected_at={_local_nvr_timestamp(evidence.event.detected_at)}",
            f"evidence_start_at={_local_nvr_timestamp(evidence.evidence_start_at)}",
            f"evidence_end_at={_local_nvr_timestamp(evidence.evidence_end_at)}",
            f"pre_event_seconds={evidence.pre_event_seconds}",
            f"post_event_seconds={evidence.post_event_seconds}",
            "real_nvr_mode=KRTC_NVR_RECORDING_MODE=nvr",
        ]
    )
    evidence.export_id = evidence.export_id or f"SIM-{evidence.event_id}-{int(timezone.now().timestamp())}"
    evidence.export_rate = 100
    evidence.ffmpeg_status = 0
    evidence.export_status = EventRecordingEvidence.STATUS_COMPLETED
    evidence.completed_at = timezone.now()
    evidence.response_payload = {
        "mode": "simulation",
        "Status": 1,
        "Rate": 100,
        "file": filename,
    }
    evidence.last_error = ""
    evidence.file.save(filename, ContentFile(content.encode("utf-8")), save=False)
    evidence.file_name = filename
    evidence.save()
    if evidence.event.video_url == "":
        evidence.event.video_url = evidence.file.url
        evidence.event.save(update_fields=["video_url", "updated_at"])
    return evidence


def _evidence_file_name(evidence: EventRecordingEvidence, *, extension: str) -> str:
    camera_code = evidence.camera.camera_code if evidence.camera else "CAM-UNKNOWN"
    detected = timezone.localtime(evidence.event.detected_at).strftime("%Y%m%d_%H%M%S")
    source_id = evidence.event.source_event_id or evidence.event_id
    stem = (
        f"event_{source_id}_{camera_code}_{detected}_"
        f"pre{evidence.pre_event_seconds}_post{evidence.post_event_seconds}"
    )
    safe_stem = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in stem)
    return str(Path(safe_stem).with_suffix(f".{extension.lower()}"))
