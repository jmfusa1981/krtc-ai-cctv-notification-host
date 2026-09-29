from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandError

from apps.ai_bridge.models import InferenceHost
from apps.ai_bridge.services.event_importer import (
    EventImporter,
    ImportSummary,
)
from apps.ai_bridge.services.inference_client import (
    InferenceClient,
    InferenceClientError,
)


class Command(BaseCommand):
    help = (
        "從指定正式 AI 推論主機抓取事件並單次匯入 Django。"
        "會執行資料庫 Camera Mapping、去重、Event 建立及 "
        "BroadcastLog 建立。"
        "不執行實際 Speaker 播放。"
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--host-code",
            default="INF-001",
            help="InferenceHost 代碼。預設：INF-001",
        )

        parser.add_argument(
            "--limit",
            type=int,
            default=20,
            help="最多抓取事件數。預設：20",
        )

        parser.add_argument(
            "--offset",
            type=int,
            default=0,
            help="事件查詢 offset。預設：0",
        )

        parser.add_argument(
            "--since",
            default=None,
            help="只抓取此時間之後的事件。",
        )

        parser.add_argument(
            "--until",
            default=None,
            help="只抓取此時間之前的事件。",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        host_code = options["host_code"]
        limit = options["limit"]
        offset = options["offset"]

        if limit <= 0:
            raise CommandError("--limit 必須大於 0。")

        if limit > 500:
            raise CommandError(
                "--limit 不可大於正式 API 上限 500。"
            )

        if offset < 0:
            raise CommandError("--offset 不可小於 0。")

        try:
            inference_host = InferenceHost.objects.get(
                host_code=host_code,
            )
        except InferenceHost.DoesNotExist as exc:
            raise CommandError(
                f"找不到推論主機：host_code={host_code}"
            ) from exc

        if not inference_host.is_active:
            raise CommandError(
                f"推論主機未啟用：host_code={host_code}"
            )

        client = InferenceClient(
            base_url=inference_host.normalized_base_url,
            timeout=inference_host.timeout_seconds,
        )

        importer = EventImporter(
            client=client,
            inference_host=inference_host,
        )

        summary = ImportSummary()

        self.stdout.write(
            f"推論主機代碼：{inference_host.host_code}"
        )
        self.stdout.write(
            f"推論主機名稱：{inference_host.name}"
        )
        self.stdout.write(
            f"Base URL：{inference_host.normalized_base_url}"
        )
        self.stdout.write(
            f"Timeout：{inference_host.timeout_seconds} 秒"
        )
        self.stdout.write(
            "Playback mode：simulation"
        )

        try:
            health = client.health()

            if health.get("status") != "ok":
                raise CommandError(
                    f"推論主機 Health 狀態異常：{health}"
                )

            payload = client.get_events(
                since=options["since"],
                until=options["until"],
                limit=limit,
                offset=offset,
            )

        except InferenceClientError as exc:
            raise CommandError(str(exc)) from exc

        items = payload.get("items", [])
        summary.fetched = len(items)

        self.stdout.write(
            self.style.SUCCESS(
                f"事件抓取成功：total={payload.get('total', 0)}, "
                f"returned={len(items)}"
            )
        )

        for index, item in enumerate(items, start=1):
            source_event_id = item.get("id")

            try:
                result = importer.import_payload(item)

            except Exception as exc:
                summary.errors += 1

                self.stdout.write("")
                self.stdout.write(
                    self.style.ERROR(
                        f"[{index}] ERROR "
                        f"source_event_id={source_event_id}"
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

                self.stdout.write(
                    self.style.SUCCESS(
                        f"[{index}] IMPORTED"
                    )
                )

            elif result.status == "duplicate":
                summary.duplicate += 1

                self.stdout.write(
                    self.style.NOTICE(
                        f"[{index}] DUPLICATE"
                    )
                )

            else:
                summary.skipped += 1

                self.stdout.write(
                    self.style.WARNING(
                        f"[{index}] SKIPPED"
                    )
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

        self.stdout.write("")
        self.stdout.write(
            self.style.SUCCESS("單次匯入完成")
        )
        self.stdout.write(
            f"  inference_host         : "
            f"{inference_host.host_code}"
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