from __future__ import annotations

import io
import json
import logging
import os
import struct
import tempfile
import threading
import warnings
import wave
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from urllib.parse import quote
from uuid import uuid4

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from PIL import Image, UnidentifiedImageError

from apps.settings_app.models import UIConfiguration


logger = logging.getLogger(__name__)

MAX_ASSET_BYTES = 10 * 1024 * 1024
LOGIN_BACKGROUND_DIR = "ui/login"
ALERT_SOUND_DIR = "ui_assets/alert_sound"
_CONFIG_FILENAME = "frontend_assets.json"
_CONFIG_MAX_BYTES = 64 * 1024
_config_lock = threading.RLock()

_IMAGE_FORMATS = {
    ".jpg": "JPEG",
    ".jpeg": "JPEG",
    ".png": "PNG",
    ".webp": "WEBP",
}
_AUDIO_EXTENSIONS = {".mp3", ".wav", ".ogg"}


class FrontendAssetError(ValueError):
    """前台資產驗證或儲存失敗。"""


@dataclass(frozen=True)
class ValidatedAsset:
    data: bytes
    extension: str
    content_type: str


@dataclass(frozen=True)
class AlertSoundConfiguration:
    enabled: bool = False
    name: str = ""


def validate_login_background(upload) -> ValidatedAsset:
    extension = _upload_extension(upload)
    if extension not in _IMAGE_FORMATS:
        raise FrontendAssetError("僅支援 JPG、JPEG、PNG 或 WebP 圖片。")

    data = _read_bounded_upload(upload)
    _validate_image_bytes(data, extension)
    return ValidatedAsset(data, extension, Image.MIME[_IMAGE_FORMATS[extension]])


def validate_alert_sound(upload) -> ValidatedAsset:
    extension = _upload_extension(upload)
    if extension not in _AUDIO_EXTENSIONS:
        raise FrontendAssetError("僅支援 MP3、WAV 或 OGG 音效。")

    data = _read_bounded_upload(upload)
    validators = {
        ".wav": _validate_wav,
        ".mp3": _validate_mp3,
        ".ogg": _validate_ogg,
    }
    validators[extension](data)
    content_types = {
        ".wav": "audio/wav",
        ".mp3": "audio/mpeg",
        ".ogg": "audio/ogg",
    }
    return ValidatedAsset(data, extension, content_types[extension])


def activate_login_background(asset: ValidatedAsset) -> UIConfiguration:
    config = UIConfiguration.load()
    old_name = str(config.login_background.name or "")
    new_name = _store_asset(LOGIN_BACKGROUND_DIR, asset)
    try:
        config.login_background.name = new_name
        config.login_background_enabled = True
        config.save(update_fields=["login_background", "login_background_enabled", "updated_at"])
    except Exception:
        _delete_managed_asset(new_name, LOGIN_BACKGROUND_DIR)
        raise

    if old_name != new_name:
        _delete_managed_asset(old_name, LOGIN_BACKGROUND_DIR)
    return config


def reset_login_background() -> None:
    config = UIConfiguration.load()
    old_name = str(config.login_background.name or "")
    config.login_background_enabled = False
    config.login_background = ""
    config.save(update_fields=["login_background", "login_background_enabled", "updated_at"])
    _delete_managed_asset(old_name, LOGIN_BACKGROUND_DIR)


def resolve_login_background_url(config: UIConfiguration | None = None) -> str:
    try:
        config = config or UIConfiguration.load()
        if not config.login_background_enabled or not config.login_background:
            return ""
        name = _safe_relative_name(str(config.login_background.name or ""))
        if not _is_under(name, LOGIN_BACKGROUND_DIR):
            return ""
        extension = PurePosixPath(name).suffix.lower()
        if extension not in _IMAGE_FORMATS:
            return ""
        data = _read_storage_file(name)
        _validate_image_bytes(data, extension)
        return default_storage.url(name)
    except (FrontendAssetError, OSError, ValueError):
        return ""


def load_alert_sound_configuration() -> AlertSoundConfiguration:
    with _config_lock:
        try:
            path = _config_path()
            if not path.is_file() or path.stat().st_size > _CONFIG_MAX_BYTES:
                return AlertSoundConfiguration()
            payload = json.loads(path.read_text(encoding="utf-8"))
            name = _safe_relative_name(str(payload.get("alert_sound") or ""))
            if name and not _is_under(name, ALERT_SOUND_DIR):
                return AlertSoundConfiguration()
            return AlertSoundConfiguration(
                enabled=payload.get("alert_sound_enabled") is True,
                name=name,
            )
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return AlertSoundConfiguration()


def save_alert_sound(asset: ValidatedAsset | None, *, enabled: bool) -> AlertSoundConfiguration:
    with _config_lock:
        current = load_alert_sound_configuration()
        new_name = current.name
        if asset is not None:
            new_name = _store_asset(ALERT_SOUND_DIR, asset)

        if enabled and not _valid_alert_sound_name(new_name):
            if asset is not None:
                _delete_managed_asset(new_name, ALERT_SOUND_DIR)
            raise FrontendAssetError("請先選擇有效的自訂事件警示音。")

        updated = AlertSoundConfiguration(enabled=bool(enabled), name=new_name)
        try:
            _write_alert_configuration(updated)
        except Exception:
            if asset is not None:
                _delete_managed_asset(new_name, ALERT_SOUND_DIR)
            raise

        if asset is not None and current.name != new_name:
            _delete_managed_asset(current.name, ALERT_SOUND_DIR)
        return updated


def reset_alert_sound() -> None:
    with _config_lock:
        current = load_alert_sound_configuration()
        _write_alert_configuration(AlertSoundConfiguration())
        _delete_managed_asset(current.name, ALERT_SOUND_DIR)


def resolve_alert_sound_url() -> str:
    config = load_alert_sound_configuration()
    if not config.enabled or not _valid_alert_sound_name(config.name):
        return ""
    return f"{settings.MEDIA_URL.rstrip('/')}/{quote(config.name, safe='/')}"


def alert_sound_status() -> dict[str, object]:
    config = load_alert_sound_configuration()
    valid = _valid_alert_sound_name(config.name)
    return {
        "enabled": config.enabled and valid,
        "has_custom": valid,
        "url": resolve_alert_sound_url() if config.enabled and valid else "",
    }


def _read_bounded_upload(upload) -> bytes:
    if int(getattr(upload, "size", 0) or 0) > MAX_ASSET_BYTES:
        raise FrontendAssetError("檔案大小不可超過 10 MB。")

    chunks = []
    total = 0
    for chunk in upload.chunks():
        total += len(chunk)
        if total > MAX_ASSET_BYTES:
            raise FrontendAssetError("檔案大小不可超過 10 MB。")
        chunks.append(chunk)
    data = b"".join(chunks)
    if not data:
        raise FrontendAssetError("上傳檔案不可為空白。")
    return data


def _upload_extension(upload) -> str:
    name = str(getattr(upload, "name", "") or "").replace("\\", "/")
    return PurePosixPath(name).suffix.lower()


def _validate_image_bytes(data: bytes, extension: str) -> None:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as image:
                detected_format = image.format
                image.verify()
            with Image.open(io.BytesIO(data)) as image:
                image.load()
    except (OSError, SyntaxError, UnidentifiedImageError, Image.DecompressionBombWarning) as exc:
        raise FrontendAssetError("圖片內容損毀或格式不正確。") from exc
    if detected_format != _IMAGE_FORMATS.get(extension):
        raise FrontendAssetError("圖片內容與副檔名不符。")


def _validate_wav(data: bytes) -> None:
    try:
        with wave.open(io.BytesIO(data), "rb") as audio:
            channels = audio.getnchannels()
            sample_width = audio.getsampwidth()
            frame_count = audio.getnframes()
            if channels < 1 or sample_width < 1 or audio.getframerate() < 1 or frame_count < 1:
                raise wave.Error("invalid parameters")
            frames = audio.readframes(frame_count)
            if len(frames) != frame_count * channels * sample_width:
                raise wave.Error("truncated frames")
    except (EOFError, wave.Error) as exc:
        raise FrontendAssetError("WAV 音效內容損毀或格式不正確。") from exc


def _validate_mp3(data: bytes) -> None:
    offset = 0
    if data.startswith(b"ID3"):
        if len(data) < 10 or any(byte & 0x80 for byte in data[6:10]):
            raise FrontendAssetError("MP3 音效內容損毀或格式不正確。")
        tag_size = sum(byte << shift for byte, shift in zip(data[6:10], (21, 14, 7, 0)))
        offset = 10 + tag_size

    scan_limit = min(len(data) - 4, offset + 64 * 1024)
    for index in range(offset, max(offset, scan_limit + 1)):
        header = int.from_bytes(data[index:index + 4], "big")
        if header & 0xFFE00000 != 0xFFE00000:
            continue
        version_id = (header >> 19) & 0x3
        layer_id = (header >> 17) & 0x3
        bitrate_index = (header >> 12) & 0xF
        sample_index = (header >> 10) & 0x3
        if version_id == 1 or layer_id != 1 or bitrate_index in {0, 15} or sample_index == 3:
            continue
        bitrates = (
            (32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320)
            if version_id == 3
            else (8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160)
        )
        sample_rates = {
            3: (44100, 48000, 32000),
            2: (22050, 24000, 16000),
            0: (11025, 12000, 8000),
        }
        bitrate = bitrates[bitrate_index - 1] * 1000
        sample_rate = sample_rates[version_id][sample_index]
        padding = (header >> 9) & 0x1
        frame_length = ((144 if version_id == 3 else 72) * bitrate // sample_rate) + padding
        if frame_length > 4 and index + frame_length <= len(data):
            return
    raise FrontendAssetError("MP3 音效內容損毀或格式不正確。")


def _validate_ogg(data: bytes) -> None:
    if len(data) < 28 or data[:4] != b"OggS" or data[4] != 0:
        raise FrontendAssetError("OGG 音效內容損毀或格式不正確。")
    segment_count = data[26]
    header_end = 27 + segment_count
    if header_end > len(data):
        raise FrontendAssetError("OGG 音效內容損毀或格式不正確。")
    body_end = header_end + sum(data[27:header_end])
    if body_end > len(data):
        raise FrontendAssetError("OGG 音效內容損毀或格式不正確。")
    first_packet = data[header_end:body_end]
    if not (first_packet.startswith(b"OpusHead") or first_packet.startswith(b"\x01vorbis")):
        raise FrontendAssetError("OGG 音效內容不是支援的 Vorbis 或 Opus 格式。")


def _store_asset(directory: str, asset: ValidatedAsset) -> str:
    name = f"{directory}/{uuid4().hex}{asset.extension}"
    return default_storage.save(name, ContentFile(asset.data))


def _safe_relative_name(name: str) -> str:
    normalized = name.replace("\\", "/").lstrip("/")
    path = PurePosixPath(normalized)
    if not normalized or path.is_absolute() or ".." in path.parts:
        raise FrontendAssetError("資產設定無效。")
    return path.as_posix()


def _is_under(name: str, directory: str) -> bool:
    path = PurePosixPath(name)
    return path.parent.as_posix() == directory


def _read_storage_file(name: str) -> bytes:
    if not default_storage.exists(name):
        raise FrontendAssetError("資產檔案不存在。")
    with default_storage.open(name, "rb") as source:
        data = source.read(MAX_ASSET_BYTES + 1)
    if not data or len(data) > MAX_ASSET_BYTES:
        raise FrontendAssetError("資產檔案無效。")
    return data


def _valid_alert_sound_name(name: str) -> bool:
    try:
        safe_name = _safe_relative_name(name)
        extension = PurePosixPath(safe_name).suffix.lower()
        if not _is_under(safe_name, ALERT_SOUND_DIR) or extension not in _AUDIO_EXTENSIONS:
            return False
        data = _read_storage_file(safe_name)
        {".wav": _validate_wav, ".mp3": _validate_mp3, ".ogg": _validate_ogg}[extension](data)
        return True
    except (FrontendAssetError, OSError, ValueError):
        return False


def _delete_managed_asset(name: str, directory: str) -> None:
    if not name:
        return
    try:
        safe_name = _safe_relative_name(name)
        stem = PurePosixPath(safe_name).stem
        if not _is_under(safe_name, directory) or len(stem) != 32:
            return
        int(stem, 16)
        if default_storage.exists(safe_name):
            default_storage.delete(safe_name)
    except Exception:
        logger.warning("無法刪除已停用的自訂前台資產。")


def _config_path() -> Path:
    return Path(settings.KRTC_CONFIG_DIR) / _CONFIG_FILENAME


def _write_alert_configuration(config: AlertSoundConfiguration) -> None:
    path = _config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "alert_sound_enabled": config.enabled,
        "alert_sound": config.name,
    }
    temporary_name = ""
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=".frontend-assets-",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary_name = temporary.name
            json.dump(payload, temporary, ensure_ascii=False, indent=2)
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_name, path)
    finally:
        if temporary_name:
            try:
                Path(temporary_name).unlink(missing_ok=True)
            except OSError:
                pass
