import signal
import threading

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import close_old_connections

from apps.notifications.scheduler import process_due_broadcast_schedules
from apps.notifications.scheduler_process import (
    SchedulerAlreadyRunning,
    SchedulerProcessLock,
    utc_now_text,
    write_scheduler_status,
)


class Command(BaseCommand):
    help = "Run the dedicated single-instance broadcast schedule worker."

    def add_arguments(self, parser):
        parser.add_argument("--interval", type=int, default=15, help="Polling interval in seconds.")
        parser.add_argument("--limit", type=int, default=10)
        parser.add_argument("--once", action="store_true")
        parser.add_argument(
            "--check-only",
            action="store_true",
            help="Validate the process lock and health file without processing schedules.",
        )

    def handle(self, *args, **options):
        interval = max(5, options["interval"])
        limit = max(1, options["limit"])
        runtime_dir = settings.BROADCAST_SCHEDULER_RUNTIME_DIR
        lock_path = runtime_dir / "broadcast_scheduler.lock"
        status_path = runtime_dir / "broadcast_scheduler_status.json"
        stop_event = threading.Event()

        def request_stop(signum, _frame):
            self.stdout.write(f"Stop requested by signal {signum}.")
            stop_event.set()

        for signal_name in ("SIGINT", "SIGTERM", "SIGBREAK"):
            process_signal = getattr(signal, signal_name, None)
            if process_signal is not None:
                signal.signal(process_signal, request_stop)

        try:
            with SchedulerProcessLock(lock_path):
                self.stdout.write(
                    self.style.SUCCESS(
                        f"Broadcast scheduler started. interval={interval}s "
                        f"pid={__import__('os').getpid()}"
                    )
                )
                write_scheduler_status(
                    status_path,
                    state="running",
                    started_at=utc_now_text(),
                    interval_seconds=interval,
                    limit=limit,
                    last_iteration_at=None,
                    last_success_at=None,
                    last_error=None,
                )
                if options["check_only"]:
                    write_scheduler_status(
                        status_path,
                        state="stopped",
                        started_at=utc_now_text(),
                        stopped_at=utc_now_text(),
                        interval_seconds=interval,
                        limit=limit,
                        last_success_at=None,
                        last_error=None,
                        check_only=True,
                    )
                    self.stdout.write(
                        self.style.SUCCESS("Scheduler process validation passed.")
                    )
                    return
                self._run_loop(
                    interval=interval,
                    limit=limit,
                    once=options["once"],
                    stop_event=stop_event,
                    status_path=status_path,
                )
        except SchedulerAlreadyRunning as exc:
            # Do not overwrite the health file owned by the running process.
            raise CommandError(str(exc)) from exc
        finally:
            close_old_connections()

    def _run_loop(self, interval, limit, once, stop_event, status_path):
        started_at = utc_now_text()
        last_success_at = None
        last_error = None
        try:
            while not stop_event.is_set():
                iteration_at = utc_now_text()
                try:
                    close_old_connections()
                    result = process_due_broadcast_schedules(limit=limit)
                    last_success_at = utc_now_text()
                    last_error = None
                    if result["due_count"] or result["failed"]:
                        self.stdout.write(str(result))
                    write_scheduler_status(
                        status_path,
                        state="running",
                        started_at=started_at,
                        interval_seconds=interval,
                        limit=limit,
                        last_iteration_at=iteration_at,
                        last_success_at=last_success_at,
                        last_error=None,
                        last_result=result,
                    )
                except Exception as exc:
                    last_error = f"{type(exc).__name__}: {exc}"
                    write_scheduler_status(
                        status_path,
                        state="degraded",
                        started_at=started_at,
                        interval_seconds=interval,
                        limit=limit,
                        last_iteration_at=iteration_at,
                        last_success_at=last_success_at,
                        last_error=last_error,
                    )
                    self.stderr.write(self.style.ERROR(last_error))
                finally:
                    close_old_connections()

                if once:
                    break
                stop_event.wait(interval)
        finally:
            write_scheduler_status(
                status_path,
                state="stopped",
                started_at=started_at,
                stopped_at=utc_now_text(),
                interval_seconds=interval,
                limit=limit,
                last_success_at=last_success_at,
                last_error=last_error,
            )
