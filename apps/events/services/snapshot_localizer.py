from __future__ import annotations

import hashlib
import logging
import mimetypes
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from django.conf import settings
from django.core.files.base import ContentFile
from django.db import close_old_connections, transaction

from apps.events.models import Event

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SECONDS = float(getattr(settings, "SNAPSHOT_DOWNLOAD_TIMEOUT_SECONDS", 3.0))
DEFAULT_MAX_BYTES = int(getattr(settings, "SNAPSHOT_DOWNLOAD_MAX_BYTES", 12 * 1024 * 1024))
DEFAULT_RETRY_COUNT = int(getattr(settings, "SNAPSHOT_DOWNLOAD_RETRY_COUNT", 1))
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}

# A bounded pool prevents one thread being created for every incoming event.
_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="snapshot-localizer")
_PENDING_LOCK = threading.Lock()
_PENDING_EVENT_IDS: set[int] = set()


@dataclass(frozen=True)
class SnapshotDownloadResult:
    ok: bool
    status: str
    message: str = ""
    local_name: str = ""
    source_url: str = ""


def event_has_local_snapshot(event: Event) -> bool:
    snapshot = getattr(event, "snapshot", None)
    name = getattr(snapshot, "name", "") if snapshot else ""
    if not name:
        return False
    try:
        return bool(snapshot.storage.exists(name))
    except Exception:
        logger.exception("Unable to verify local snapshot event=%s name=%s", event.pk, name)
        return False


def local_snapshot_url(event: Event) -> str:
    """Return only a verified PAO-local snapshot URL."""
    if not event_has_local_snapshot(event):
        return ""
    try:
        return event.snapshot.url
    except (ValueError, AttributeError):
        return ""


def _looks_like_image(content: bytes) -> bool:
    return (
        content.startswith(b"\xff\xd8\xff")
        or content.startswith(b"\x89PNG\r\n\x1a\n")
        or (len(content) >= 12 and content[:4] == b"RIFF" and content[8:12] == b"WEBP")
    )


def _extension_for(content_type: str, source_url: str, content: bytes) -> str:
    extension = mimetypes.guess_extension(content_type or "") or Path(urlparse(source_url).path).suffix.lower()
    if extension == ".jpe":
        extension = ".jpg"
    if extension not in ALLOWED_EXTENSIONS:
        if content.startswith(b"\x89PNG"):
            extension = ".png"
        elif len(content) >= 12 and content[:4] == b"RIFF" and content[8:12] == b"WEBP":
            extension = ".webp"
        else:
            extension = ".jpg"
    return extension


def _safe_filename(event: Event, source_url: str, content_type: str, content: bytes) -> str:
    extension = _extension_for(content_type, source_url, content)
    source_key = event.source_event_id or event.event_id or str(event.pk)
    safe_key = "".join(
        character if character.isalnum() or character in {"-", "_"} else "_"
        for character in str(source_key)
    )[:96]
    original_name = Path(urlparse(source_url).path).stem
    safe_original = "".join(
        character if character.isalnum() or character in {"-", "_"} else "_"
        for character in original_name
    )[:96]
    digest = hashlib.sha256(source_url.encode("utf-8")).hexdigest()[:12]
    return f"event_{event.pk}_{safe_key}_{safe_original}_{digest}{extension}"


def download_event_snapshot(
    event: Event,
    *,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    max_bytes: int = DEFAULT_MAX_BYTES,
    overwrite: bool = False,
    retry_count: int = DEFAULT_RETRY_COUNT,
) -> SnapshotDownloadResult:
    """Download the complete snapshot_url returned by KMetro API v1.5.

    The URL is used verbatim. No base URL or /snapshots path is reconstructed.
    A 404 is terminal because the inference host has already removed that file.
    """
    if not overwrite and event_has_local_snapshot(event):
        return SnapshotDownloadResult(
            True,
            "already_local",
            local_name=getattr(event.snapshot, "name", ""),
            source_url=(event.snapshot_url or "").strip(),
        )

    source_url = str(event.snapshot_url or "").strip()
    if not source_url:
        return SnapshotDownloadResult(False, "missing_url", "snapshot_url is empty")

    parsed = urlparse(source_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return SnapshotDownloadResult(
            False,
            "invalid_url",
            "snapshot_url must be an absolute HTTP/HTTPS URL",
            source_url=source_url,
        )

    request = Request(
        source_url,
        headers={
            "User-Agent": "KRTC-PAO-Notification-Host/5.12",
            "Accept": "image/jpeg,image/png,image/webp,image/*;q=0.8",
            "Cache-Control": "no-cache",
            "Connection": "close",
        },
    )

    attempts = max(1, int(retry_count) + 1)
    last_result: SnapshotDownloadResult | None = None

    for attempt in range(1, attempts + 1):
        try:
            with urlopen(request, timeout=max(1.0, float(timeout))) as response:
                content_type = response.headers.get_content_type() or "application/octet-stream"
                declared_length = response.headers.get("Content-Length")
                if declared_length:
                    try:
                        if int(declared_length) > max_bytes:
                            return SnapshotDownloadResult(
                                False,
                                "too_large",
                                "declared content length exceeds limit",
                                source_url=source_url,
                            )
                    except ValueError:
                        pass
                content = response.read(max_bytes + 1)

        except HTTPError as exc:
            status = "not_found" if exc.code == 404 else "http_error"
            result = SnapshotDownloadResult(False, status, f"HTTP {exc.code}", source_url=source_url)
            if exc.code == 404 or attempt >= attempts:
                return result
            last_result = result
        except (socket.timeout, TimeoutError) as exc:
            last_result = SnapshotDownloadResult(
                False, "timeout", str(exc) or "connection timed out", source_url=source_url
            )
        except URLError as exc:
            last_result = SnapshotDownloadResult(
                False, "connection_error", str(exc.reason), source_url=source_url
            )
        except OSError as exc:
            last_result = SnapshotDownloadResult(False, "connection_error", str(exc), source_url=source_url)
        except Exception as exc:
            logger.exception("Unexpected snapshot download error event=%s", event.pk)
            return SnapshotDownloadResult(False, "unexpected_error", str(exc), source_url=source_url)
        else:
            if not content:
                return SnapshotDownloadResult(False, "empty_response", "empty response body", source_url=source_url)
            if len(content) > max_bytes:
                return SnapshotDownloadResult(False, "too_large", "downloaded content exceeds limit", source_url=source_url)
            if not content_type.startswith("image/") and not _looks_like_image(content):
                return SnapshotDownloadResult(
                    False, "not_image", f"response is not an image: {content_type}", source_url=source_url
                )

            filename = _safe_filename(event, source_url, content_type, content)
            try:
                if overwrite and getattr(event.snapshot, "name", ""):
                    try:
                        event.snapshot.delete(save=False)
                    except Exception:
                        logger.warning("Unable to delete previous local snapshot event=%s", event.pk, exc_info=True)
                event.snapshot.save(filename, ContentFile(content), save=True)
            except Exception as exc:
                logger.exception("Unable to save local snapshot event=%s", event.pk)
                return SnapshotDownloadResult(False, "save_error", str(exc), source_url=source_url)

            return SnapshotDownloadResult(
                True,
                "downloaded",
                local_name=event.snapshot.name,
                source_url=source_url,
            )

        if attempt < attempts:
            time.sleep(min(0.5 * attempt, 1.5))

    return last_result or SnapshotDownloadResult(False, "download_failed", source_url=source_url)


def _download_snapshot_worker(event_id: int) -> None:
    close_old_connections()
    try:
        event = Event.objects.get(pk=event_id)
        result = download_event_snapshot(event)
        if result.ok:
            logger.info(
                "Snapshot localized event=%s status=%s local=%s",
                event_id,
                result.status,
                result.local_name,
            )
        elif result.status not in {"missing_url", "not_found"}:
            logger.warning(
                "Snapshot localization failed event=%s status=%s message=%s url=%s",
                event_id,
                result.status,
                result.message,
                result.source_url,
            )
    except Event.DoesNotExist:
        return
    except Exception:
        logger.exception("Snapshot localization worker failed event=%s", event_id)
    finally:
        with _PENDING_LOCK:
            _PENDING_EVENT_IDS.discard(int(event_id))
        close_old_connections()


def schedule_event_snapshot_download(event_id: int) -> None:
    """Schedule localization after the current DB transaction commits."""
    event_id = int(event_id)

    def submit() -> None:
        with _PENDING_LOCK:
            if event_id in _PENDING_EVENT_IDS:
                return
            _PENDING_EVENT_IDS.add(event_id)
        _EXECUTOR.submit(_download_snapshot_worker, event_id)

    transaction.on_commit(submit)
