from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandError

from apps.ai_bridge.models import InferenceHost
from apps.ai_bridge.services.event_mapper import map_inference_event
from apps.ai_bridge.services.inference_client import (
    InferenceClient,
    InferenceClientError,
)


class Command(BaseCommand):
    help = (
        "預覽指定正式 AI 推論主機的事件 Mapping 結果。"
        "Camera Mapping 由資料庫讀取。"
        "本指令不寫入 Event 或 BroadcastLog。"
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
            help="最多取得的事件數。預設：20",
        )

        parser.add_argument(
            "--offset",
            type=int,
            default=0,
            help="事件查詢 offset。預設：0",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        host_code = options["host_code"]
        limit = options["limit"]
        offset = options["offset"]

        if limit <= 0:
            raise CommandError("--limit 必須大於 0。")

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

        try:
            health = client.health()

            if health.get("status") != "ok":
                raise CommandError(
                    f"推論主機 Health 狀態異常：{health}"
                )

            payload = client.get_events(
                limit=limit,
                offset=offset,
            )

        except InferenceClientError as exc:
            raise CommandError(str(exc)) from exc

        items = payload.get("items", [])

        accepted_count = 0
        skipped_count = 0

        self.stdout.write("")
        self.stdout.write(
            self.style.SUCCESS(
                f"取得事件數：{len(items)}"
            )
        )

        for index, item in enumerate(items, start=1):
            result = map_inference_event(
                item,
                client=client,
                inference_host=inference_host,
            )

            self.stdout.write("")

            if result.accepted:
                accepted_count += 1

                self.stdout.write(
                    self.style.SUCCESS(
                        f"[{index}] ACCEPTED"
                    )
                )

                self.stdout.write(
                    f"  inference_host     : "
                    f"{result.inference_host_code}"
                )
                self.stdout.write(
                    f"  source_host        : {result.source_host}"
                )
                self.stdout.write(
                    f"  source_event_id    : "
                    f"{result.source_event_id}"
                )
                self.stdout.write(
                    f"  source_camera_id   : "
                    f"{result.source_camera_id}"
                )
                self.stdout.write(
                    f"  source_event_code  : "
                    f"{result.source_event_code}"
                )
                self.stdout.write(
                    f"  mapped_camera_id   : "
                    f"{result.mapped_camera_id}"
                )
                self.stdout.write(
                    f"  mapped_camera_code : "
                    f"{result.mapped_camera_code}"
                )
                self.stdout.write(
                    f"  mapped_event_type  : "
                    f"{result.mapped_event_type}"
                )
                self.stdout.write(
                    f"  detected_at        : "
                    f"{result.detected_at}"
                )
                self.stdout.write(
                    f"  severity           : "
                    f"{result.severity}"
                )
                self.stdout.write(
                    f"  confidence         : "
                    f"{result.confidence}"
                )
                self.stdout.write(
                    f"  snapshot_url       : "
                    f"{result.snapshot_url}"
                )

            else:
                skipped_count += 1

                self.stdout.write(
                    self.style.WARNING(
                        f"[{index}] SKIPPED"
                    )
                )

                self.stdout.write(
                    f"  inference_host     : "
                    f"{result.inference_host_code}"
                )
                self.stdout.write(
                    f"  reason             : {result.reason}"
                )
                self.stdout.write(
                    f"  source_event_id    : "
                    f"{result.source_event_id}"
                )
                self.stdout.write(
                    f"  source_camera_id   : "
                    f"{result.source_camera_id}"
                )
                self.stdout.write(
                    f"  source_event_code  : "
                    f"{result.source_event_code}"
                )

        self.stdout.write("")
        self.stdout.write(
            self.style.SUCCESS(
                f"Mapping 完成：accepted={accepted_count}, "
                f"skipped={skipped_count}"
            )
        )