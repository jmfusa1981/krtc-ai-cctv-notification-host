from __future__ import annotations

import hashlib
import mimetypes
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand

from apps.events.models import Event


class Command(BaseCommand):
    help = "下載尚未本地保存的遠端事件快照至 Event.snapshot。"

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=20)
        parser.add_argument("--timeout", type=float, default=8.0)
        parser.add_argument("--max-bytes", type=int, default=12 * 1024 * 1024)
        parser.add_argument("--overwrite", action="store_true")

    def handle(self, *args, **options):
        limit = max(1, options["limit"])
        timeout = max(1.0, options["timeout"])
        max_bytes = max(1024, options["max_bytes"])
        overwrite = options["overwrite"]

        queryset = Event.objects.exclude(snapshot_url="").order_by("created_at")
        if not overwrite:
            queryset = queryset.filter(snapshot="")

        processed = 0
        downloaded = 0
        failed = 0

        for event in queryset[:limit]:
            processed += 1
            try:
                filename, content = self._download(
                    event.snapshot_url,
                    event_id=event.id,
                    source_event_id=event.source_event_id,
                    timeout=timeout,
                    max_bytes=max_bytes,
                )
                event.snapshot.save(filename, ContentFile(content), save=True)
                downloaded += 1
                self.stdout.write(self.style.SUCCESS(
                    f"[OK] event={event.id} -> {event.snapshot.name}"
                ))
            except Exception as exc:  # management command must continue per event
                failed += 1
                self.stderr.write(f"[FAILED] event={event.id}: {exc}")

        self.stdout.write(
            self.style.SUCCESS(
                f"完成：processed={processed}, downloaded={downloaded}, failed={failed}"
            )
        )

    def _download(self, url, *, event_id, source_event_id, timeout, max_bytes):
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            raise ValueError("snapshot_url 僅允許 http/https")
        if not parsed.hostname:
            raise ValueError("snapshot_url 缺少主機名稱")

        request = Request(
            url,
            headers={
                "User-Agent": "KRTC-Notification-Host/2.0",
                "Accept": "image/jpeg,image/png,image/webp,image/*;q=0.8",
            },
        )

        try:
            with urlopen(request, timeout=timeout) as response:
                content_type = response.headers.get_content_type()
                if not content_type.startswith("image/"):
                    raise ValueError(f"回應不是圖片：{content_type}")

                declared_length = response.headers.get("Content-Length")
                if declared_length and int(declared_length) > max_bytes:
                    raise ValueError("圖片超過允許大小")

                content = response.read(max_bytes + 1)
                if len(content) > max_bytes:
                    raise ValueError("圖片超過允許大小")
        except HTTPError as exc:
            raise RuntimeError(f"HTTP {exc.code}") from exc
        except URLError as exc:
            raise RuntimeError(f"連線失敗：{exc.reason}") from exc

        extension = mimetypes.guess_extension(content_type) or Path(parsed.path).suffix
        if extension not in {".jpg", ".jpeg", ".png", ".webp"}:
            extension = ".jpg"

        source_key = source_event_id or str(event_id)
        digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:10]
        filename = f"event_{source_key}_{digest}{extension}"
        return filename, content
