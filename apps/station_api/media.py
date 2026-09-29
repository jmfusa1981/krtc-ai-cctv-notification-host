from dataclasses import dataclass
from pathlib import Path

from django.conf import settings
from django.utils.text import get_valid_filename

from apps.events.models import EventRecordingEvidence


@dataclass(frozen=True)
class LocalMedia:
    path: Path
    content_type: str
    filename: str


_IMAGE_SIGNATURES = {
    ".jpg": (b"\xff\xd8\xff", "image/jpeg"),
    ".jpeg": (b"\xff\xd8\xff", "image/jpeg"),
    ".png": (b"\x89PNG\r\n\x1a\n", "image/png"),
    ".webp": (b"RIFF", "image/webp"),
}


def _media_root_path():
    try:
        return Path(settings.MEDIA_ROOT).resolve(strict=True)
    except (OSError, TypeError, ValueError):
        return None


def _contained_file(field_file):
    """只允許解析 MEDIA_ROOT 內由資料庫 FileField 指定的本機檔案。"""
    name = str(getattr(field_file, "name", "") or "").strip()
    media_root = _media_root_path()
    if not name or media_root is None:
        return None

    try:
        candidate = (media_root / name).resolve(strict=True)
        candidate.relative_to(media_root)
    except (OSError, RuntimeError, ValueError):
        return None
    return candidate if candidate.is_file() else None


def resolve_snapshot(field_file):
    path = _contained_file(field_file)
    if path is None:
        return None

    signature = _IMAGE_SIGNATURES.get(path.suffix.lower())
    if signature is None:
        return None
    expected, content_type = signature
    try:
        with path.open("rb") as media_file:
            header = media_file.read(12)
    except OSError:
        return None
    if path.suffix.lower() == ".webp":
        valid = header.startswith(expected) and header[8:12] == b"WEBP"
    else:
        valid = header.startswith(expected)
    if not valid:
        return None
    return LocalMedia(path=path, content_type=content_type, filename=path.name)


def resolve_recording(evidence):
    if evidence.export_status != EventRecordingEvidence.STATUS_COMPLETED:
        return None
    path = _contained_file(evidence.file)
    if path is None or path.suffix.lower() != ".mp4":
        return None
    try:
        with path.open("rb") as media_file:
            header = media_file.read(12)
    except OSError:
        return None
    if len(header) < 8 or header[4:8] != b"ftyp":
        return None

    filename = get_valid_filename(path.name)
    if not filename.lower().endswith(".mp4"):
        filename = f"event_recording_{evidence.pk}.mp4"
    return LocalMedia(path=path, content_type="video/mp4", filename=filename)
