from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from urllib.parse import urlparse

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import close_old_connections, connection
from django.utils import timezone

from apps.station_api.occ_runtime import write_runtime_status
from apps.station_api.occ_sync import (
    OccSyncClient,
    daily_sync_due,
    mark_daily_sync_complete,
    prune_occ_sync_logs,
)


REQUIRED_TABLES = {
    "station_api_occsyncstate",
    "settings_app_stationlocalsettings",
}


def _path_is_writable(path: Path) -> bool:
    """
    Verify that a directory can be created/accessed and written to.

    The temporary probe file is removed immediately.
    """
    try:
        path.mkdir(parents=True, exist_ok=True)

        probe = path / f".krtc_write_test_{os.getpid()}.tmp"
        probe.write_text("KRTC", encoding="utf-8")
        probe.unlink(missing_ok=True)

        return True
    except OSError:
        return False


def run_startup_preflight() -> list[str]:
    """
    Validate local prerequisites before starting the PAO OCC sync service.

    OCC network reachability is intentionally NOT checked here.
    The OCC server may be temporarily offline while this service continues
    running in degraded mode.
    """
    errors: list[str] = []

    # ------------------------------------------------------------
    # OCC configuration
    # ------------------------------------------------------------
    if not getattr(settings, "KRTC_OCC_SYNC_ENABLED", False):
        errors.append(
            "KRTC_OCC_SYNC_ENABLED must be True."
        )

    if not str(
        getattr(settings, "KRTC_OCC_API_TOKEN", "") or ""
    ).strip():
        errors.append(
            "KRTC_OCC_API_TOKEN is required."
        )

    occ_url = str(
        getattr(
            settings,
            "KRTC_MAINTENANCE_API_BASE_URL",
            "",
        )
        or ""
    ).strip()

    if not occ_url:
        errors.append(
            "KRTC_MAINTENANCE_API_BASE_URL is required."
        )
    else:
        parsed = urlparse(occ_url)

        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.netloc
        ):
            errors.append(
                "KRTC_MAINTENANCE_API_BASE_URL must be "
                "a valid HTTP or HTTPS URL."
            )

    # ------------------------------------------------------------
    # Database
    # ------------------------------------------------------------
    database_name = settings.DATABASES["default"].get("NAME")

    if not database_name:
        errors.append(
            "Production database path is not configured."
        )
    else:
        database_path = Path(database_name)

        if not database_path.exists():
            errors.append(
                f"Production database does not exist: "
                f"{database_path}"
            )
        elif database_path.stat().st_size <= 0:
            errors.append(
                f"Production database is empty: "
                f"{database_path}"
            )

    # ------------------------------------------------------------
    # Required schema
    # ------------------------------------------------------------
    try:
        existing_tables = set(
            connection.introspection.table_names()
        )

        missing_tables = sorted(
            REQUIRED_TABLES - existing_tables
        )

        if missing_tables:
            errors.append(
                "Database schema is not ready. "
                "Missing table(s): "
                + ", ".join(missing_tables)
            )

    except Exception as exc:
        errors.append(
            "Unable to inspect production database schema: "
            f"{type(exc).__name__}: {exc}"
        )

    # ------------------------------------------------------------
    # Runtime paths
    # ------------------------------------------------------------
    persistent_root = Path(
        settings.KRTC_PERSISTENT_ROOT
    )

    runtime_dir = Path(
        settings.KRTC_OCC_SERVICE_STATUS_PATH
    ).parent

    log_dir = Path(
        settings.KRTC_LOG_DIR
    )

    if not persistent_root.exists():
        errors.append(
            f"KRTC persistent root does not exist: "
            f"{persistent_root}"
        )

    if not _path_is_writable(runtime_dir):
        errors.append(
            f"OCC runtime directory is not writable: "
            f"{runtime_dir}"
        )

    if not _path_is_writable(log_dir):
        errors.append(
            f"KRTC log directory is not writable: "
            f"{log_dir}"
        )

    return errors


class OccSyncService:
    """
    Dedicated PAO-to-OCC heartbeat and synchronization service.
    """

    def __init__(
        self,
        heartbeat_client=None,
        worker_client=None,
        stop_event=None,
        monotonic=time.monotonic,
    ):
        self.heartbeat_client = (
            heartbeat_client or OccSyncClient()
        )
        self.worker_client = (
            worker_client or OccSyncClient()
        )
        self.stop_event = (
            stop_event or threading.Event()
        )
        self.monotonic = monotonic
        self._last_prune_date = None

    def _report_error(self, command, exc):
        command.stderr.write(str(exc))

        write_runtime_status(
            state="degraded",
            last_error=str(exc),
        )

    def heartbeat_loop(self, command):
        interval = max(
            5,
            int(settings.KRTC_HEARTBEAT_INTERVAL),
        )

        next_run = self.monotonic()

        close_old_connections()

        try:
            while not self.stop_event.is_set():
                now_monotonic = self.monotonic()

                if now_monotonic < next_run:
                    if self.stop_event.wait(
                        next_run - now_monotonic
                    ):
                        break

                write_runtime_status(
                    last_heartbeat_attempt_at=(
                        timezone.now().isoformat()
                    )
                )

                try:
                    self.heartbeat_client.send_heartbeat()

                    write_runtime_status(
                        state="running",
                        last_heartbeat_success_at=(
                            timezone.now().isoformat()
                        ),
                        last_error="",
                    )

                except Exception as exc:
                    self._report_error(
                        command,
                        exc,
                    )

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
            self._report_error(
                command,
                exc,
            )

        if daily_sync_due():
            try:
                self.worker_client.send_device_status()

            except Exception as exc:
                self._report_error(
                    command,
                    exc,
                )

            else:
                try:
                    self.worker_client.send_daily_sync()

                except Exception as exc:
                    self._report_error(
                        command,
                        exc,
                    )

                else:
                    mark_daily_sync_complete()

        today = timezone.localdate()

        if self._last_prune_date != today:
            try:
                prune_occ_sync_logs()
                self._last_prune_date = today

            except Exception as exc:
                self._report_error(
                    command,
                    exc,
                )

        write_runtime_status(
            last_worker_cycle_at=(
                timezone.now().isoformat()
            )
        )

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

        worker_interval = max(
            5,
            int(settings.KRTC_HEARTBEAT_INTERVAL),
        )

        try:
            while not self.stop_event.is_set():
                close_old_connections()

                try:
                    self.worker_cycle(command)

                except Exception as exc:
                    self._report_error(
                        command,
                        exc,
                    )

                finally:
                    close_old_connections()

                if self.stop_event.wait(
                    worker_interval
                ):
                    break

        finally:
            self.stop_event.set()

            heartbeat_thread.join(
                timeout=min(
                    worker_interval,
                    10,
                )
            )

            write_runtime_status(
                state="stopped"
            )

            close_old_connections()


class Command(BaseCommand):
    help = (
        "Run the dedicated PAO to OCC heartbeat "
        "and synchronization service."
    )

    def handle(self, *args, **options):
        self.stdout.write(
            "Running OCC sync startup preflight..."
        )

        errors = run_startup_preflight()

        if errors:
            self.stderr.write(
                self.style.ERROR(
                    "OCC sync startup preflight FAILED."
                )
            )

            for error in errors:
                self.stderr.write(
                    f" - {error}"
                )

            try:
                write_runtime_status(
                    state="startup_failed",
                    last_error="; ".join(errors),
                )
            except Exception:
                pass

            raise CommandError(
                "OCC sync startup preflight failed."
            )

        self.stdout.write(
            self.style.SUCCESS(
                "OCC sync startup preflight PASS."
            )
        )

        service = OccSyncService()

        self.stdout.write(
            self.style.SUCCESS(
                "OCC sync service started."
            )
        )

        try:
            service.run(self)

        except KeyboardInterrupt:
            service.stop_event.set()

            self.stdout.write(
                "OCC sync service stopping."
            )