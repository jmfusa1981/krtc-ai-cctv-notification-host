from __future__ import annotations

import json
from typing import Any

from django.core.management.base import BaseCommand, CommandError

from apps.ai_bridge.services.inference_client import (
    DEFAULT_BASE_URL,
    DEFAULT_TIMEOUT_SECONDS,
    InferenceClient,
    InferenceClientError,
)


class Command(BaseCommand):
    help = (
        "唯讀抓取正式 AI 推論主機事件資料。"
        "本指令不執行 Mapping，也不寫入 Django 資料庫。"
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--base-url",
            default=DEFAULT_BASE_URL,
            help=(
                "AI 推論主機 Base URL。"
                f"預設：{DEFAULT_BASE_URL}"
            ),
        )

        parser.add_argument(
            "--timeout",
            type=int,
            default=DEFAULT_TIMEOUT_SECONDS,
            help=(
                "HTTP timeout 秒數。"
                f"預設：{DEFAULT_TIMEOUT_SECONDS}"
            ),
        )

        parser.add_argument(
            "--limit",
            type=int,
            default=20,
            help="最多取得幾筆事件。預設：20",
        )

        parser.add_argument(
            "--offset",
            type=int,
            default=0,
            help="事件查詢 offset。預設：0",
        )

        parser.add_argument(
            "--camera-id",
            default=None,
            help="只取得指定正式推論主機 camera_id 的事件。",
        )

        parser.add_argument(
            "--event-type",
            default=None,
            help="只取得指定 event_type 的事件。",
        )

        parser.add_argument(
            "--severity",
            default=None,
            help="只取得指定 severity 的事件。",
        )

        parser.add_argument(
            "--since",
            default=None,
            help="只取得此時間之後的事件，格式依正式 API 規範。",
        )

        parser.add_argument(
            "--until",
            default=None,
            help="只取得此時間之前的事件，格式依正式 API 規範。",
        )

        parser.add_argument(
            "--show-cameras",
            action="store_true",
            help="額外顯示 GET /api/cameras 的原始結果。",
        )

        parser.add_argument(
            "--raw-json",
            action="store_true",
            help="以完整 JSON 格式輸出事件 API 回傳。",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        base_url = options["base_url"]
        timeout = options["timeout"]
        limit = options["limit"]
        offset = options["offset"]

        if timeout <= 0:
            raise CommandError("--timeout 必須大於 0。")

        if limit <= 0:
            raise CommandError("--limit 必須大於 0。")

        if offset < 0:
            raise CommandError("--offset 不可小於 0。")

        client = InferenceClient(
            base_url=base_url,
            timeout=timeout,
        )

        self.stdout.write(
            self.style.NOTICE(
                f"推論主機：{client.config.base_url}"
            )
        )

        self.stdout.write(
            self.style.NOTICE(
                f"Timeout：{client.config.timeout} 秒"
            )
        )

        try:
            self._check_health(client)

            payload = client.get_events(
                camera_id=options["camera_id"],
                event_type=options["event_type"],
                severity=options["severity"],
                since=options["since"],
                until=options["until"],
                limit=limit,
                offset=offset,
            )

            if options["raw_json"]:
                self._print_raw_json(
                    title="Event API 原始回傳",
                    payload=payload,
                )
            else:
                self._print_event_summary(payload)

            if options["show_cameras"]:
                cameras = client.get_cameras()
                self._print_raw_json(
                    title="Camera API 原始回傳",
                    payload=cameras,
                )

        except InferenceClientError as exc:
            raise CommandError(str(exc)) from exc

    def _check_health(self, client: InferenceClient) -> None:
        self.stdout.write("檢查 GET /health ...")

        health_payload = client.health()
        health_status = health_payload.get("status")

        if health_status != "ok":
            raise CommandError(
                "推論主機 Health 狀態異常："
                f"{json.dumps(health_payload, ensure_ascii=False)}"
            )

        self.stdout.write(
            self.style.SUCCESS("Health check：OK")
        )

    def _print_event_summary(
        self,
        payload: dict[str, Any],
    ) -> None:
        total = payload.get("total", 0)
        items = payload.get("items", [])

        self.stdout.write("")
        self.stdout.write(
            self.style.SUCCESS(
                f"事件 API 抓取成功：total={total}, "
                f"returned={len(items)}"
            )
        )

        if not items:
            self.stdout.write(
                self.style.WARNING("目前沒有事件資料。")
            )
            return

        for index, item in enumerate(items, start=1):
            self.stdout.write("")
            self.stdout.write(
                self.style.HTTP_INFO(
                    f"[{index}] source_event_id={item.get('id')}"
                )
            )

            self.stdout.write(
                f"  created_at    : {item.get('created_at')}"
            )
            self.stdout.write(
                f"  camera_id     : {item.get('camera_id')}"
            )
            self.stdout.write(
                f"  roi_id        : {item.get('roi_id')}"
            )
            self.stdout.write(
                f"  event_type    : {item.get('event_type')}"
            )
            self.stdout.write(
                f"  event_code    : {item.get('event_code')}"
            )
            self.stdout.write(
                f"  severity      : {item.get('severity')}"
            )
            self.stdout.write(
                f"  confidence    : {item.get('confidence')}"
            )
            self.stdout.write(
                f"  snapshot_path : {item.get('snapshot_path')}"
            )

            extra = item.get("extra")
            self.stdout.write(
                "  extra         : "
                + json.dumps(
                    extra,
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )

    def _print_raw_json(
        self,
        *,
        title: str,
        payload: Any,
    ) -> None:
        self.stdout.write("")
        self.stdout.write(
            self.style.HTTP_INFO(title)
        )

        self.stdout.write(
            json.dumps(
                payload,
                ensure_ascii=False,
                indent=2,
                sort_keys=False,
            )
        )