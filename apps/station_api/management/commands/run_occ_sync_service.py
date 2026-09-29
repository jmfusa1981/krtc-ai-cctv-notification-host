import threading
import time

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import close_old_connections
from django.utils import timezone

from apps.station_api.occ_runtime import write_runtime_status
from apps.station_api.occ_sync import (
    OccSyncClient,
    daily_sync_due,
    mark_daily_sync_complete,
    prune_occ_sync_logs,
)


class OccSyncService:
    """以獨立節奏執行 Heartbeat 與一般 OCC 同步工作。"""

    def __init__(
        self,
        heartbeat_client=None,
        worker_client=None,
        stop_event=None,
        monotonic=time.monotonic,
    ):
        self.heartbeat_client = heartbeat_client or OccSyncClient()
        self.worker_client = worker_client or OccSyncClient()
        self.stop_event = stop_event or threading.Event()
        self.monotonic = monotonic
        self._last_prune_date = None

    def _report_error(self, command, exc):
        command.stderr.write(str(exc))
        write_runtime_status(state="degraded", last_error=str(exc))

    def heartbeat_loop(self, command):
        interval = max(5, int(settings.KRTC_HEARTBEAT_INTERVAL))
        next_run = self.monotonic()
        close_old_connections()
        try:
            while not self.stop_event.is_set():
                now_monotonic = self.monotonic()
                if now_monotonic < next_run:
                    if self.stop_event.wait(next_run - now_monotonic):
                        break

                write_runtime_status(
                    last_heartbeat_attempt_at=timezone.now().isoformat()
                )
                try:
                    self.heartbeat_client.send_heartbeat()
                    write_runtime_status(
                        state="running",
                        last_heartbeat_success_at=timezone.now().isoformat(),
                        last_error="",
                    )
                except Exception as exc:
                    self._report_error(command, exc)
                finally:
                    close_old_connections()

                next_run += interval
                current = self.monotonic()
                if next_run <= current:
                    next_run = current + interval
        finally:
            close_old_connections()

    def worker_cycle(self, command):
        try:
            self.worker_client.send_pending_events()
        except Exception as exc:
            self._report_error(command, exc)

        if daily_sync_due():
            try:
                self.worker_client.send_device_status()
            except Exception as exc:
                self._report_error(command, exc)
            else:
                try:
                    self.worker_client.send_daily_sync()
                except Exception as exc:
                    self._report_error(command, exc)
                else:
                    mark_daily_sync_complete()

        today = timezone.localdate()
        if self._last_prune_date != today:
            try:
                prune_occ_sync_logs()
                self._last_prune_date = today
            except Exception as exc:
                self._report_error(command, exc)

        write_runtime_status(last_worker_cycle_at=timezone.now().isoformat())

    def run(self, command):
        started_at = timezone.now().isoformat()
        write_runtime_status(
            state="running",
            started_at=started_at,
            last_error="",
        )
        heartbeat_thread = threading.Thread(
            target=self.heartbeat_loop,
            args=(command,),
            name="krtc-occ-heartbeat",
            daemon=True,
        )
        heartbeat_thread.start()
        worker_interval = max(5, int(settings.KRTC_HEARTBEAT_INTERVAL))
        try:
            while not self.stop_event.is_set():
                close_old_connections()
                try:
                    self.worker_cycle(command)
                except Exception as exc:
                    self._report_error(command, exc)
                finally:
                    close_old_connections()
                if self.stop_event.wait(worker_interval):
                    break
        finally:
            self.stop_event.set()
            heartbeat_thread.join(timeout=min(worker_interval, 10))
            write_runtime_status(state="stopped")
            close_old_connections()


class Command(BaseCommand):
    help = "Run the dedicated PAO to OCC heartbeat and synchronization service."

    def handle(self, *args, **options):
        if not settings.KRTC_OCC_SYNC_ENABLED:
            raise CommandError("KRTC_OCC_SYNC_ENABLED must be True.")
        if not settings.KRTC_OCC_API_TOKEN:
            raise CommandError("KRTC_OCC_API_TOKEN is required.")
        service = OccSyncService()
        self.stdout.write(self.style.SUCCESS("OCC sync service started."))
        try:
            service.run(self)
        except KeyboardInterrupt:
            service.stop_event.set()
            self.stdout.write("OCC sync service stopping.")
