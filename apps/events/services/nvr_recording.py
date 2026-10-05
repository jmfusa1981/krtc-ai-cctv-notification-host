from __future__ import annotations

import json
import os
import re
import tempfile
from base64 import b64encode
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlunsplit
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from django.conf import settings
from django.core.files.base import ContentFile
from django.db import transaction
from django.utils import timezone

from apps.events.models import Event, EventRecordingEvidence


class NvrRecordingError(RuntimeError):
    pass


class NvrTerminalError(NvrRecordingError):
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
    """以明確設定的 NVR 時區輸出不含時區尾碼的設備時間。"""

    if value is None or timezone.is_naive(value):
        raise NvrRecordingError("事件 detected_at 必須是含時區的時間。")
    configured_name = getattr(settings, "KRTC_NVR_TIME_ZONE", settings.TIME_ZONE)
    try:
        configured_zone = ZoneInfo(configured_name)
    except Exception as exc:
        raise NvrRecordingError(f"NVR 時區設定無效：{configured_name}") from exc
    return value.astimezone(configured_zone).strftime("%Y-%m-%dT%H:%M:%S")


def redact_nvr_error(value, config: NvrConfig | None = None) -> str:
    """移除例外文字中可能出現的 NVR 帳密與 URL userinfo。"""
    text = str(value)
    if config:
        for secret in (config.username, config.password):
            if secret:
                text = text.replace(secret, "[REDACTED]")
    text = re.sub(r"(?i)(https?://)[^/@\s]+:[^/@\s]+@", r"\1***:***@", text)
    return text[:500]


def _safe_diagnostic_payload(payload, config=None):
    blocked = {"account", "username", "password", "token", "authorization", "secret"}
    if isinstance(payload, dict):
        return {
            str(key): _safe_diagnostic_payload(value, config)
            for key, value in payload.items()
            if str(key).lower() not in blocked
        }
    if isinstance(payload, list):
        return [_safe_diagnostic_payload(value, config) for value in payload]
    if isinstance(payload, str):
        return redact_nvr_error(payload, config)
    return payload


def _build_nvr_url(config: NvrConfig, params: dict[str, str | int]) -> str:
    """建立不含帳密的 URL；urlencode 可完整保留各查詢參數邊界。"""

    netloc = f"{config.host}:{config.port}"
    return urlunsplit(("http", netloc, "/export.cgi", urlencode(params), ""))


def _build_nvr_request(
    config: NvrConfig,
    params: dict[str, str | int],
    *,
    accept: str | None = None,
) -> Request:
    """使用獨立 Basic Authorization 標頭，避免帳密與特殊字元進入 URL。"""

    credentials = f"{config.username}:{config.password}".encode("utf-8")
    headers = {"Authorization": f"Basic {b64encode(credentials).decode('ascii')}"}
    if accept:
        headers["Accept"] = accept
    return Request(_build_nvr_url(config, params), headers=headers)


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
        password = password or "simulation"
        channel = channel if channel is not None else camera.id

    if not host:
        raise NvrRecordingError(f"攝影機 {camera.camera_code} 缺少 NVR Host。")
    if channel is None:
        raise NvrRecordingError(f"攝影機 {camera.camera_code} 缺少 NVR Channel。")
    if not username:
        raise NvrRecordingError(f"攝影機 {camera.camera_code} 缺少 NVR 帳號。")
    if not password:
        raise NvrRecordingError(f"攝影機 {camera.camera_code} 缺少 NVR 密碼。")
    try:
        port = int(port)
    except (TypeError, ValueError) as exc:
        raise NvrRecordingError(f"攝影機 {camera.camera_code} 的 NVR Port 無效。") from exc
    if port < 1 or port > 65535:
        raise NvrRecordingError(f"攝影機 {camera.camera_code} 的 NVR Port 無效。")
    if any(character in host for character in ("/", "?", "#", "@")) or any(
        character.isspace() for character in host
    ):
        raise NvrRecordingError(f"攝影機 {camera.camera_code} 的 NVR Host 無效。")

    return NvrConfig(
        host=host,
        port=port,
        username=username,
        password=password,
        channel=int(channel),
        video_format=getattr(settings, "KRTC_NVR_EXPORT_FORMAT", "MP4").upper(),
    )


def _request_json(
    config: NvrConfig,
    params: dict[str, str | int],
    timeout: int,
) -> dict:
    request = _build_nvr_request(config, params, accept="application/json")
    try:
        with urlopen(request, timeout=timeout) as response:
            body = response.read()
    except HTTPError as exc:
        if exc.code in {401, 403}:
            raise NvrTerminalError(f"NVR authentication rejected: HTTP {exc.code}") from exc
        raise NvrRecordingError(f"NVR HTTP {exc.code}: {exc.reason}") from exc
    except URLError as exc:
        raise NvrRecordingError(f"NVR 連線失敗：{exc.reason}") from exc
    except TimeoutError as exc:
        raise NvrRecordingError("NVR 連線逾時。") from exc

    if not body:
        return {}
    try:
        return json.loads(body.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise NvrRecordingError("NVR 回應不是有效 JSON。") from exc


def _safe_download_name(evidence: EventRecordingEvidence, disposition: str) -> str:
    filename = ""
    if "filename=" in disposition:
        filename = disposition.split("filename=", 1)[1].strip().strip('"')
        filename = Path(filename.replace("\\", "/")).name
    if filename and Path(filename).suffix.lower() != ".mp4":
        raise NvrRecordingError("NVR 下載檔名不是 MP4。")
    return _evidence_file_name(evidence, extension="mp4")


def _download_to_partial(
    config: NvrConfig,
    params: dict[str, str | int],
    evidence: EventRecordingEvidence,
    timeout: int,
):
    """以固定區塊寫入 MEDIA_ROOT 內的暫存檔，避免影片常駐記憶體。"""
    request = _build_nvr_request(config, params)
    media_root = Path(settings.MEDIA_ROOT).resolve()
    partial_dir = (media_root / "event_recordings" / ".partial").resolve()
    partial_dir.relative_to(media_root)
    partial_dir.mkdir(parents=True, exist_ok=True)
    max_bytes = max(1, int(getattr(settings, "KRTC_NVR_MAX_VIDEO_BYTES", 2 * 1024**3)))
    chunk_bytes = max(4096, int(getattr(settings, "KRTC_NVR_DOWNLOAD_CHUNK_BYTES", 1024 * 1024)))
    temporary_path = None
    try:
        with urlopen(request, timeout=timeout) as response:
            disposition = response.headers.get("Content-Disposition", "")
            filename = _safe_download_name(evidence, disposition)
            declared_length = response.headers.get("Content-Length")
            if declared_length:
                try:
                    if int(declared_length) > max_bytes:
                        raise NvrTerminalError("NVR 影片超過允許大小。")
                except ValueError as exc:
                    raise NvrRecordingError("NVR Content-Length 格式無效。") from exc

            descriptor, temporary_name = tempfile.mkstemp(
                prefix=f"evidence_{evidence.pk}_",
                suffix=".part",
                dir=partial_dir,
            )
            temporary_path = Path(temporary_name)
            total = 0
            with os.fdopen(descriptor, "wb") as output:
                while True:
                    chunk = response.read(chunk_bytes)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > max_bytes:
                        raise NvrTerminalError("NVR 影片超過允許大小。")
                    output.write(chunk)
                output.flush()
                os.fsync(output.fileno())

            if total == 0:
                raise NvrTerminalError("NVR 下載回應為空。")
            if declared_length and total != int(declared_length):
                raise NvrRecordingError("NVR 影片下載長度不完整。")

            with temporary_path.open("rb") as downloaded:
                header = downloaded.read(4096)
            if header.lstrip().startswith(b"{"):
                try:
                    payload = json.loads(header.decode("utf-8-sig"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    payload = {}
                message = str(payload.get("Message") or payload.get("message") or "")
                raise NvrRecordingError(message or "NVR 下載回傳 JSON，尚未取得影片。")
            if len(header) < 8 or header[4:8] != b"ftyp":
                raise NvrTerminalError("NVR 下載內容不是有效 MP4。")
            completed_path = temporary_path
            temporary_path = None
            return filename, completed_path
    except HTTPError as exc:
        if exc.code in {401, 403}:
            raise NvrTerminalError(f"NVR authentication rejected: HTTP {exc.code}") from exc
        raise NvrRecordingError(f"NVR HTTP {exc.code}: {exc.reason}") from exc
    except URLError as exc:
        raise NvrRecordingError(f"NVR 下載失敗：{exc.reason}") from exc
    except TimeoutError as exc:
        raise NvrRecordingError("NVR 下載逾時。") from exc
    except OSError as exc:
        raise NvrRecordingError(f"NVR 下載中斷：{exc}") from exc
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def create_recording_evidence(
    event: Event,
    *,
    pre_seconds: int | None = None,
    post_seconds: int | None = None,
    force_new: bool = False,
) -> EventRecordingEvidence:
    """建立持久工作；此相容入口可選擇立即送出第一個匯出請求。"""

    evidence = enqueue_recording_evidence(
        event,
        pre_seconds=pre_seconds,
        post_seconds=post_seconds,
        force_new=force_new,
    )
    if evidence.export_status == EventRecordingEvidence.STATUS_PENDING:
        request_export(evidence)
    return evidence


def enqueue_recording_evidence(
    event: Event,
    *,
    pre_seconds: int | None = None,
    post_seconds: int | None = None,
    force_new: bool = False,
) -> EventRecordingEvidence:
    """鎖定事件後建立單一工作，不在呼叫端執行任何 NVR 網路 I/O。"""

    with transaction.atomic():
        locked_event = (
            Event.objects.select_for_update()
            .select_related("camera")
            .get(pk=event.pk)
        )
        return _enqueue_recording_evidence_locked(
            locked_event,
            pre_seconds=pre_seconds,
            post_seconds=post_seconds,
            force_new=force_new,
        )


def _enqueue_recording_evidence_locked(
    event: Event,
    *,
    pre_seconds: int | None,
    post_seconds: int | None,
    force_new: bool,
) -> EventRecordingEvidence:
    """在事件列鎖範圍內檢查既有工作並建立新工作。"""

    pre_seconds = (
        int(pre_seconds)
        if pre_seconds is not None
        else int(getattr(settings, "KRTC_NVR_PRE_EVENT_SECONDS", 30))
    )
    post_seconds = (
        int(post_seconds)
        if post_seconds is not None
        else int(getattr(settings, "KRTC_NVR_POST_EVENT_SECONDS", 90))
    )
    if pre_seconds != 30 or post_seconds != 90:
        raise NvrRecordingError("NVR 事件錄影時間窗固定為 detected_at 前 30 秒、後 90 秒。")
    if event.detected_at is None or timezone.is_naive(event.detected_at):
        raise NvrRecordingError("事件缺少有效且含時區的 detected_at。")
    start_at = event.detected_at - timedelta(seconds=pre_seconds)
    end_at = event.detected_at + timedelta(seconds=post_seconds)

    if not force_new:
        existing = event.recording_evidences.order_by("-created_at").first()
        if existing:
            return existing

    config = _camera_nvr_config(event)
    evidence = EventRecordingEvidence.objects.create(
        event=event,
        camera=event.camera,
        nvr_host=config.host,
        nvr_port=config.port,
        nvr_channel=config.channel,
        source_event_id=event.source_event_id or "",
        camera_code=event.camera.camera_code if event.camera else event.camera_code or "",
        event_time=event.detected_at,
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
    params = {
        "channel": config.channel,
        "start_time": _local_nvr_timestamp(evidence.evidence_start_at),
        "end_time": _local_nvr_timestamp(evidence.evidence_end_at),
        "format": evidence.video_format,
    }
    url = _build_nvr_url(config, params)
    now = timezone.now()
    evidence.requested_at = evidence.requested_at or now
    evidence.request_payload = {
        **evidence.request_payload,
        "method": "GET",
        "url": url,
    }

    try:
        payload = _request_json(config, params, timeout)
        export_id = payload.get("ID") or payload.get("id")
        if not export_id:
            message = str(payload.get("message") or payload.get("Message") or "")
            if "no record data exist" in message.lower():
                raise NvrTerminalError("NVR 查無指定時段的錄影資料。")
            raise NvrTerminalError(message or "NVR 未回傳匯出 ID。")
        evidence.export_id = str(export_id)
        evidence.export_status = EventRecordingEvidence.STATUS_REQUESTED
        evidence.next_poll_at = now + timedelta(seconds=_poll_interval_seconds())
        evidence.response_payload = _safe_diagnostic_payload(payload, config)
        evidence.last_error = ""
    except NvrTerminalError as exc:
        evidence.export_status = EventRecordingEvidence.STATUS_FAILED
        evidence.last_error = redact_nvr_error(exc, config)
    except NvrRecordingError as exc:
        evidence.last_error = redact_nvr_error(exc, config)
        _register_retry(evidence, now)

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
    params = {"ID": evidence.export_id}
    now = timezone.now()
    evidence.last_polled_at = now
    evidence.poll_count += 1

    try:
        payload = _request_json(config, params, timeout)
        status = int(payload.get("Status", 0))
        evidence.ffmpeg_status = payload.get("FFmpeg")
        evidence.export_rate = max(0, min(100, int(payload.get("Rate", 0))))
        evidence.response_payload = _safe_diagnostic_payload(payload, config)
        if status == -1:
            raise NvrTerminalError("NVR 匯出 ID 不存在。")
        if status not in {0, 1}:
            raise NvrRecordingError("NVR 匯出狀態值無效。")
        evidence.next_poll_at = now + timedelta(seconds=_poll_interval_seconds())
        evidence.export_status = (
            EventRecordingEvidence.STATUS_READY
            if status == 1
            else EventRecordingEvidence.STATUS_EXPORTING
        )
        evidence.last_error = ""
    except (ValueError, TypeError) as exc:
        evidence.last_error = redact_nvr_error(f"NVR 匯出狀態格式錯誤：{exc}", config)
    except NvrTerminalError as exc:
        evidence.export_status = EventRecordingEvidence.STATUS_FAILED
        evidence.last_error = redact_nvr_error(exc, config)
    except NvrRecordingError as exc:
        evidence.last_error = redact_nvr_error(exc, config)
        _register_retry(evidence, now)

    evidence.save()
    return evidence


def download_completed_export(
    evidence: EventRecordingEvidence,
    *,
    config: NvrConfig | None = None,
) -> EventRecordingEvidence:
    config = config or _camera_nvr_config(evidence.event)
    timeout = getattr(settings, "KRTC_NVR_DOWNLOAD_TIMEOUT_SECONDS", 30)
    params = {"ID": evidence.export_id, "action": "download"}
    evidence.export_status = EventRecordingEvidence.STATUS_DOWNLOADING
    evidence.download_started_at = evidence.download_started_at or timezone.now()
    evidence.save(
        update_fields=["export_status", "download_started_at", "updated_at"]
    )

    try:
        filename, temporary_path = _download_to_partial(
            config, params, evidence, timeout
        )
    except NvrTerminalError as exc:
        evidence.export_status = EventRecordingEvidence.STATUS_FAILED
        evidence.last_error = redact_nvr_error(exc, config)
        evidence.save(update_fields=["export_status", "last_error", "updated_at"])
        return evidence
    except NvrRecordingError as exc:
        evidence.export_status = EventRecordingEvidence.STATUS_READY
        evidence.last_error = redact_nvr_error(exc, config)
        _register_retry(evidence, timezone.now())
        evidence.save(
            update_fields=[
                "export_status",
                "last_error",
                "retry_count",
                "next_poll_at",
                "updated_at",
            ]
        )
        return evidence

    media_root = Path(settings.MEDIA_ROOT).resolve()
    local_date = timezone.localtime(
        evidence.event_time or evidence.event.detected_at,
        ZoneInfo(getattr(settings, "KRTC_NVR_TIME_ZONE", settings.TIME_ZONE)),
    ).date()
    relative_name = (
        Path("event_recordings")
        / f"{local_date:%Y}"
        / f"{local_date:%m}"
        / f"{local_date:%d}"
        / filename
    )
    final_path = (media_root / relative_name).resolve()
    final_path.relative_to(media_root)
    final_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.replace(temporary_path, final_path)
    except OSError as exc:
        try:
            temporary_path.unlink(missing_ok=True)
        except OSError:
            pass
        evidence.last_error = redact_nvr_error(f"NVR 影片本機保存失敗：{exc}", config)
        evidence.save(update_fields=["last_error", "updated_at"])
        return evidence
    evidence.file.name = relative_name.as_posix()
    evidence.file_name = filename
    evidence.download_url = ""
    evidence.export_rate = 100
    evidence.export_status = EventRecordingEvidence.STATUS_COMPLETED
    evidence.file_size = final_path.stat().st_size
    evidence.downloaded_at = timezone.now()
    evidence.completed_at = evidence.downloaded_at
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
    camera_code = evidence.camera_code or (
        evidence.camera.camera_code if evidence.camera else "CAM-UNKNOWN"
    )
    event_time = evidence.event_time or evidence.event.detected_at
    detected = timezone.localtime(event_time).strftime("%Y%m%d_%H%M%S")
    source_id = evidence.source_event_id or evidence.event.source_event_id or evidence.event_id
    stem = (
        f"event_{source_id}_{camera_code}_{detected}_"
        f"pre{evidence.pre_event_seconds}_post{evidence.post_event_seconds}"
    )
    safe_stem = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in stem)
    return str(Path(f"{safe_stem}_{evidence.pk}").with_suffix(f".{extension.lower()}"))


def _poll_interval_seconds() -> int:
    return max(1, int(getattr(settings, "KRTC_NVR_POLL_INTERVAL_SECONDS", 60)))


def _register_retry(evidence: EventRecordingEvidence, now) -> None:
    """記錄有上限的暫時性重試，且不清除既有匯出 ID。"""

    evidence.retry_count += 1
    evidence.next_poll_at = now + timedelta(seconds=_poll_interval_seconds())
    maximum = max(1, int(getattr(settings, "KRTC_NVR_MAX_RETRIES", 120)))
    if evidence.retry_count >= maximum:
        evidence.export_status = EventRecordingEvidence.STATUS_FAILED
