from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandError

from apps.ai_bridge.models import InferenceHost
from apps.ai_bridge.services.event_importer import (
    EventImporter,
    ImportSummary,
)
from apps.ai_bridge.services.inference_client import InferenceClient
from apps.ai_bridge.services.notify_event_normalizer import (
    normalize_notify_event_list,
)


class Command(BaseCommand):
    help = (
        "從離線 JSON 檔回放正式推論主機 notify events。"
        "會執行 Mapping、去重、Event 建立與模擬 BroadcastLog 建立。"
        "不執行實際 Speaker 播放。"
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--host-code",
            default="INF-001",
            help="InferenceHost 代碼。預設：INF-001",
        )

        parser.add_argument(
            "--file",
            required=True,
            help="notify events JSON 檔案路徑。",
        )

        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="最多回放幾筆；未指定時回放檔案內全部資料。",
        )

        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="只預覽 Mapping，不寫入 Event 或 BroadcastLog。",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        host_code = options["host_code"]
        file_path = Path(options["file"])
        limit = options["limit"]
        dry_run = options["dry_run"]

        if limit is not None and limit <= 0:
            raise CommandError("--limit 必須大於 0。")

        if not file_path.exists():
            raise CommandError(
                f"找不到 JSON 檔案：{file_path}"
            )

        if not file_path.is_file():
            raise CommandError(
                f"指定路徑不是檔案：{file_path}"
            )

        try:
            inference_host = InferenceHost.objects.get(
                host_code=host_code,
            )
        except InferenceHost.DoesNotExist as exc:
            raise CommandError(
                f"找不到推論主機：host_code={host_code}"
            ) from exc

        try:
            raw_text = file_path.read_text(encoding="utf-8-sig")
            raw_payload = json.loads(raw_text)
        except UnicodeDecodeError as exc:
            raise CommandError(
                "JSON 檔案編碼錯誤，請使用 UTF-8。"
            ) from exc
        except json.JSONDecodeError as exc:
            raise CommandError(
                f"JSON 格式錯誤：line={exc.lineno}, "
                f"column={exc.colno}, message={exc.msg}"
            ) from exc

        if not isinstance(raw_payload, dict):
            raise CommandError(
                "JSON 根節點必須是 object。"
            )

        normalized_items = normalize_notify_event_list(
            raw_payload
        )

        if limit is not None:
            normalized_items = normalized_items[:limit]

        client = InferenceClient(
            base_url=inference_host.normalized_base_url,
            timeout=inference_host.timeout_seconds,
        )

        importer = EventImporter(
            client=client,
            inference_host=inference_host,
        )

        summary = ImportSummary(
            fetched=len(normalized_items),
        )

        self.stdout.write(
            f"推論主機：{inference_host.host_code}"
        )
        self.stdout.write(
            f"來源檔案：{file_path.resolve()}"
        )
        self.stdout.write(
            f"回放筆數：{len(normalized_items)}"
        )
        self.stdout.write(
            f"模式：{'DRY RUN' if dry_run else 'IMPORT'}"
        )
        self.stdout.write(
            "Playback mode：simulation"
        )

        for index, item in enumerate(
            normalized_items,
            start=1,
        ):
            if dry_run:
                self._print_dry_run_item(
                    index=index,
                    item=item,
                )
                continue

            try:
                result = importer.import_payload(item)

            except Exception as exc:
                summary.errors += 1

                self.stdout.write("")
                self.stdout.write(
                    self.style.ERROR(
                        f"[{index}] ERROR "
                        f"source_event_id={item.get('id')}"
                    )
                )
                self.stdout.write(
                    f"  error : "
                    f"{exc.__class__.__name__}: {exc}"
                )
                continue

            self.stdout.write("")

            if result.status == "imported":
                summary.imported += 1
                summary.broadcast_logs_created += (
                    result.broadcast_logs_created
                )
                summary.broadcast_logs_skipped += (
                    result.broadcast_logs_skipped
                )

                label = self.style.SUCCESS("IMPORTED")

            elif result.status == "duplicate":
                summary.duplicate += 1
                label = self.style.NOTICE("DUPLICATE")

            else:
                summary.skipped += 1
                label = self.style.WARNING("SKIPPED")

            self.stdout.write(
                f"[{index}] {label}"
            )
            self.stdout.write(
                f"  source_event_id       : "
                f"{result.source_event_id}"
            )
            self.stdout.write(
                f"  reason                : {result.reason}"
            )
            self.stdout.write(
                f"  django_event_id       : {result.event_id}"
            )
            self.stdout.write(
                "  broadcast_logs_created: "
                f"{result.broadcast_logs_created}"
            )
            self.stdout.write(
                "  broadcast_logs_skipped: "
                f"{result.broadcast_logs_skipped}"
            )

        if dry_run:
            self.stdout.write("")
            self.stdout.write(
                self.style.SUCCESS(
                    "Dry run 完成，未寫入資料庫。"
                )
            )
            return

        self.stdout.write("")
        self.stdout.write(
            self.style.SUCCESS("離線事件回放完成")
        )
        self.stdout.write(
            f"  fetched                : {summary.fetched}"
        )
        self.stdout.write(
            f"  imported               : {summary.imported}"
        )
        self.stdout.write(
            f"  duplicate              : {summary.duplicate}"
        )
        self.stdout.write(
            f"  skipped                : {summary.skipped}"
        )
        self.stdout.write(
            "  broadcast_logs_created : "
            f"{summary.broadcast_logs_created}"
        )
        self.stdout.write(
            "  broadcast_logs_skipped : "
            f"{summary.broadcast_logs_skipped}"
        )
        self.stdout.write(
            f"  errors                 : {summary.errors}"
        )

    def _print_dry_run_item(
        self,
        *,
        index: int,
        item: dict[str, Any],
    ) -> None:
        self.stdout.write("")
        self.stdout.write(
            self.style.HTTP_INFO(
                f"[{index}] NORMALIZED"
            )
        )
        self.stdout.write(
            f"  id            : {item.get('id')}"
        )
        self.stdout.write(
            f"  event_code    : {item.get('event_code')}"
        )
        self.stdout.write(
            f"  event_type    : {item.get('event_type')}"
        )
        self.stdout.write(
            f"  camera_id     : {item.get('camera_id')}"
        )
        self.stdout.write(
            f"  roi_id        : {item.get('roi_id')}"
        )
        self.stdout.write(
            f"  created_at    : {item.get('created_at')}"
        )
        self.stdout.write(
            f"  snapshot_path : {item.get('snapshot_path')}"
        )