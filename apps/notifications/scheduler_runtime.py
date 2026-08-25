import logging
import os
import sys
import threading

from django.conf import settings
from django.db import close_old_connections

from .scheduler_process import (
    SchedulerAlreadyRunning,
    SchedulerProcessLock,
    utc_now_text,
    write_scheduler_status,
)

logger = logging.getLogger(__name__)

_start_lock = threading.Lock()
_scheduler_started = False
_scheduler_thread = None


def _is_runserver_worker():
    if "runserver" not in sys.argv:
        return False
    if "--noreload" in sys.argv:
        return True
    return os.environ.get("RUN_MAIN", "").lower() == "true"


def _scheduler_loop(interval_seconds):
    from .scheduler import process_due_broadcast_schedules

    runtime_dir = settings.BROADCAST_SCHEDULER_RUNTIME_DIR
    lock_path = runtime_dir / "broadcast_scheduler.lock"
    status_path = runtime_dir / "broadcast_scheduler_status.json"
    started_at = utc_now_text()
    last_success_at = None
    last_error = None

    try:
        with SchedulerProcessLock(lock_path):
            logger.info("Broadcast scheduler started (interval=%ss).", interval_seconds)
            write_scheduler_status(
                status_path,
                state="running",
                started_at=started_at,
                interval_seconds=interval_seconds,
                limit=10,
                last_iteration_at=None,
                last_success_at=None,
                last_error=None,
                mode="runserver_autostart",
            )
            while True:
                iteration_at = utc_now_text()
                try:
                    close_old_connections()
                    result = process_due_broadcast_schedules(limit=10)
                    last_success_at = utc_now_text()
                    last_error = None
                    if result["due_count"] or result["failed"]:
                        logger.info("Broadcast scheduler result: %s", result)
                    write_scheduler_status(
                        status_path,
                        state="running",
                        started_at=started_at,
                        interval_seconds=interval_seconds,
                        limit=10,
                        last_iteration_at=iteration_at,
                        last_success_at=last_success_at,
                        last_error=None,
                        last_result=result,
                        mode="runserver_autostart",
                    )
                except Exception as exc:
                    last_error = f"{type(exc).__name__}: {exc}"
                    logger.exception("Broadcast scheduler iteration failed.")
                    write_scheduler_status(
                        status_path,
                        state="degraded",
                        started_at=started_at,
                        interval_seconds=interval_seconds,
                        limit=10,
                        last_iteration_at=iteration_at,
                        last_success_at=last_success_at,
                        last_error=last_error,
                        mode="runserver_autostart",
                    )
                finally:
                    close_old_connections()
                threading.Event().wait(interval_seconds)
    except SchedulerAlreadyRunning:
        logger.info("Broadcast scheduler autostart skipped because another scheduler is running.")
    finally:
        if last_success_at or last_error:
            write_scheduler_status(
                status_path,
                state="stopped",
                started_at=started_at,
                stopped_at=utc_now_text(),
                interval_seconds=interval_seconds,
                limit=10,
                last_success_at=last_success_at,
                last_error=last_error,
                mode="runserver_autostart",
            )


def start_scheduler_for_current_process():
    global _scheduler_started, _scheduler_thread

    if not getattr(settings, "BROADCAST_SCHEDULER_AUTOSTART", True):
        return False
    if not _is_runserver_worker():
        return False

    with _start_lock:
        if _scheduler_started:
            return False
        interval_seconds = max(
            5,
            int(getattr(settings, "BROADCAST_SCHEDULER_INTERVAL_SECONDS", 10)),
        )
        thread = threading.Thread(
            target=_scheduler_loop,
            args=(interval_seconds,),
            name="krtc-broadcast-scheduler",
            daemon=True,
        )
        thread.start()
        _scheduler_thread = thread
        _scheduler_started = True
        return True


def scheduler_thread_alive() -> bool:
    return bool(_scheduler_thread and _scheduler_thread.is_alive())
