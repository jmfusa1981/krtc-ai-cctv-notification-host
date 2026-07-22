from __future__ import annotations

import time
from datetime import datetime
from typing import Any

from django.core.management.base import BaseCommand, CommandError
from django.db import close_old_connections
from django.utils import timezone

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
        "持續輪詢所有啟用中的 AI 推論主機，"
        "逐台執行 Health check、事件抓取、Mapping、去重與匯入。"
        "單台主機失敗不會中止其他主機。"
        "不執行實際 Speaker 播放。"
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--interval",
            type=float,
            default=5.0,
            help="完整輪詢週期間隔秒數。預設：5",
        )

        parser.add_argument(
            "--limit",
            type=int,
            default=100,
            help="每台主機每輪最多抓取事件數。預設：100，最大：500",
        )

        parser.add_argument(
            "--offset",
            type=int,
            default=0,
            help="事件查詢 offset。預設：0",
        )

        parser.add_argument(
            "--host-code",
            action="append",
            dest="host_codes",
            default=None,
            help=(
                "只輪詢指定 host_code。"
                "可重複指定，例如："
                "--host-code INF-001 --host-code INF-002"
            ),
        )

        parser.add_argument(
            "--once",
            action="store_true",
            help="只執行一個輪詢週期後結束。",
        )

        parser.add_argument(
            "--skip-health-check",
            action="store_true",
            help="略過每台主機的 GET /health 檢查。",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        interval = options["interval"]
        limit = options["limit"]
        offset = options["offset"]
        host_codes = options["host_codes"]
        run_once = options["once"]
        skip_health_check = options["skip_health_check"]

        if interval <= 0:
            raise CommandError("--interval 必須大於 0。")

        if limit <= 0:
            raise CommandError("--limit 必須大於 0。")

        if limit > 500:
            raise CommandError(
                "--limit 不可大於正式 API 上限 500。"
            )

        if offset < 0:
            raise CommandError("--offset 不可小於 0。")

        self.stdout.write(
            self.style.SUCCESS(
                "多推論主機輪詢已啟動"
            )
        )
        self.stdout.write(
            f"輪詢間隔：{interval} 秒"
        )
        self.stdout.write(
            f"每台事件上限：{limit}"
        )
        self.stdout.write(
            "Playback mode：simulation"
        )

        if host_codes:
            self.stdout.write(
                f"指定主機：{', '.join(host_codes)}"
            )
        else:
            self.stdout.write(
                "指定主機：全部啟用中的推論主機"
            )

        if run_once:
            self.stdout.write(
                "執行模式：單一輪詢週期"
            )
        else:
            self.stdout.write(
                "執行模式：持續輪詢，按 Ctrl+C 停止"
            )

        self.stdout.write("")

        cycle_number = 0

        try:
            while True:
                cycle_number += 1

                close_old_connections()

                started_at = datetime.now().astimezone()

                self.stdout.write(
                    self.style.NOTICE(
                        f"[Cycle {cycle_number}] "
                        f"{started_at.isoformat(timespec='seconds')}"
                    )
                )

                hosts = self._get_hosts(host_codes)

                if not hosts:
                    self.stdout.write(
                        self.style.WARNING(
                            "目前沒有符合條件且已啟用的推論主機。"
                        )
                    )
                else:
                    cycle_summary = self._poll_hosts(
                        hosts=hosts,
                        limit=limit,
                        offset=offset,
                        skip_health_check=skip_health_check,
                    )

                    self._print_cycle_summary(cycle_summary)

                close_old_connections()

                if run_once:
                    break

                self.stdout.write(
                    f"等待 {interval} 秒後開始下一輪..."
                )
                self.stdout.write("")

                time.sleep(interval)

        except KeyboardInterrupt:
            self.stdout.write("")
            self.stdout.write(
                self.style.WARNING(
                    "收到 Ctrl+C，正在停止多主機輪詢。"
                )
            )

        finally:
            close_old_connections()

            self.stdout.write(
                self.style.SUCCESS(
                    "多推論主機輪詢已停止。"
                )
            )

    def _get_hosts(
        self,
        host_codes: list[str] | None,
    ) -> list[InferenceHost]:
        queryset = (
            InferenceHost.objects
            .filter(is_active=True)
            .order_by("host_code")
        )

        if host_codes:
            queryset = queryset.filter(
                host_code__in=host_codes,
            )

        return list(queryset)

    def _poll_hosts(
        self,
        *,
        hosts: list[InferenceHost],
        limit: int,
        offset: int,
        skip_health_check: bool,
    ) -> dict[str, int]:
        cycle_summary = {
            "hosts_total": len(hosts),
            "hosts_online": 0,
            "hosts_failed": 0,
            "fetched": 0,
            "imported": 0,
            "duplicate": 0,
            "skipped": 0,
            "broadcast_created": 0,
            "broadcast_skipped": 0,
            "errors": 0,
        }

        for host in hosts:
            self.stdout.write("")
            self.stdout.write(
                self.style.HTTP_INFO(
                    f"[{host.host_code}] "
                    f"{host.name} "
                    f"({host.normalized_base_url})"
                )
            )

            summary = self._poll_single_host(
                host=host,
                limit=limit,
                offset=offset,
                skip_health_check=skip_health_check,
            )

            if summary is None:
                cycle_summary["hosts_failed"] += 1
                continue

            cycle_summary["hosts_online"] += 1
            cycle_summary["fetched"] += summary.fetched
            cycle_summary["imported"] += summary.imported
            cycle_summary["duplicate"] += summary.duplicate
            cycle_summary["skipped"] += summary.skipped
            cycle_summary["broadcast_created"] += (
                summary.broadcast_logs_created
            )
            cycle_summary["broadcast_skipped"] += (
                summary.broadcast_logs_skipped
            )
            cycle_summary["errors"] += summary.errors

        return cycle_summary

    def _poll_single_host(
        self,
        *,
        host: InferenceHost,
        limit: int,
        offset: int,
        skip_health_check: bool,
    ) -> ImportSummary | None:
        client = InferenceClient(
            base_url=host.normalized_base_url,
            timeout=host.timeout_seconds,
        )

        importer = EventImporter(
            client=client,
            inference_host=host,
        )

        now = timezone.now()

        try:
            if not skip_health_check:
                health = client.health()

                host.last_health_at = now

                if health.get("status") != "ok":
                    raise InferenceClientError(
                        f"Health 狀態異常：{health}"
                    )

            payload = client.get_events(
                limit=limit,
                offset=offset,
            )

        except InferenceClientError as exc:
            host.status = InferenceHost.STATUS_OFFLINE
            host.last_error_at = now
            host.last_error = str(exc)

            update_fields = [
                "status",
                "last_error_at",
                "last_error",
                "updated_at",
            ]

            if not skip_health_check:
                update_fields.append("last_health_at")

            host.save(update_fields=update_fields)

            self.stdout.write(
                self.style.ERROR(
                    f"  FAILED：{exc}"
                )
            )

            return None

        host.status = InferenceHost.STATUS_ONLINE
        host.last_success_at = now
        host.last_error = ""

        update_fields = [
            "status",
            "last_success_at",
            "last_error",
            "updated_at",
        ]

        if not skip_health_check:
            update_fields.append("last_health_at")

        host.save(update_fields=update_fields)

        items = payload.get("items", [])

        summary = ImportSummary(
            fetched=len(items),
        )

        for item in items:
            try:
                result = importer.import_payload(item)

            except Exception as exc:
                summary.errors += 1

                self.stdout.write(
                    self.style.ERROR(
                        "  ERROR "
                        f"source_event_id={item.get('id')} "
                        f"{exc.__class__.__name__}: {exc}"
                    )
                )
                continue

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
                        "  IMPORTED "
                        f"source_event_id={result.source_event_id} "
                        f"django_event_id={result.event_id}"
                    )
                )

            elif result.status == "duplicate":
                summary.duplicate += 1

            else:
                summary.skipped += 1

                self.stdout.write(
                    self.style.WARNING(
                        "  SKIPPED "
                        f"source_event_id={result.source_event_id} "
                        f"reason={result.reason}"
                    )
                )

        self.stdout.write(
            "  RESULT："
            f"fetched={summary.fetched}, "
            f"imported={summary.imported}, "
            f"duplicate={summary.duplicate}, "
            f"skipped={summary.skipped}, "
            f"broadcast_created="
            f"{summary.broadcast_logs_created}, "
            f"broadcast_skipped="
            f"{summary.broadcast_logs_skipped}, "
            f"errors={summary.errors}"
        )

        return summary

    def _print_cycle_summary(
        self,
        summary: dict[str, int],
    ) -> None:
        self.stdout.write("")
        self.stdout.write(
            self.style.SUCCESS(
                "本輪總結："
            )
        )
        self.stdout.write(
            f"  hosts_total       : {summary['hosts_total']}"
        )
        self.stdout.write(
            f"  hosts_online      : {summary['hosts_online']}"
        )
        self.stdout.write(
            f"  hosts_failed      : {summary['hosts_failed']}"
        )
        self.stdout.write(
            f"  fetched           : {summary['fetched']}"
        )
        self.stdout.write(
            f"  imported          : {summary['imported']}"
        )
        self.stdout.write(
            f"  duplicate         : {summary['duplicate']}"
        )
        self.stdout.write(
            f"  skipped           : {summary['skipped']}"
        )
        self.stdout.write(
            "  broadcast_created : "
            f"{summary['broadcast_created']}"
        )
        self.stdout.write(
            "  broadcast_skipped : "
            f"{summary['broadcast_skipped']}"
        )
        self.stdout.write(
            f"  errors            : {summary['errors']}"
        )