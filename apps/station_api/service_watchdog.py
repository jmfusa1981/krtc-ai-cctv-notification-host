from __future__ import annotations

import json
import logging
import os
import sys
import threading
import time
from pathlib import Path

from django.conf import settings
from django.db import close_old_connections
from django.utils import timezone

from .device_faults import recover_device_fault, report_device_fault
from .models import DeviceFaultLog

logger = logging.getLogger(__name__)

_start_lock = threading.Lock()
_watchdog_started = False
_watchdog_thread = None


def _host_code() -> str:
    return str(getattr(settings, "KRTC_NOTIFICATION_HOST_CODE", "") or "PAO").strip()


def _sync_service_fault(*, fault_code: str, healthy: bool, description: str, severity=None):
    try:
        if healthy:
            recover_device_fault(
                device_type=DeviceFaultLog.DEVICE_NOTIFICATION_HOST,
                device_code=_host_code(),
                fault_code=fault_code,
            )
            return

        report_device_fault(
            device_type=DeviceFaultLog.DEVICE_NOTIFICATION_HOST,
            device_code=_host_code(),
            device_name="PAO Notification Host",
            area="PAO Internal Service",
            fault_code=fault_code,
            fault_description=description[:500],
            severity=severity or DeviceFaultLog.SEVERITY_WARNING,
        )
    except Exception:
        logger.exception("PAO service watchdog could not update DeviceFaultLog.")


def _broadcast_scheduler_health() -> tuple[bool, str]:
    if not getattr(settings, "BROADCAST_SCHEDULER_AUTOSTART", True):
        return True, "Broadcast scheduler monitoring skipped because autostart is disabled."

    try:
        from apps.notifications.scheduler_runtime import scheduler_thread_alive
        if scheduler_thread_alive():
            return True, "Broadcast scheduler thread is alive."
    except Exception as exc:
        logger.debug("Unable to read scheduler thread state: %s", exc)

    status_path = Path(settings.BROADCAST_SCHEDULER_RUNTIME_DIR) / "broadcast_scheduler_status.json"
    if not status_path.exists():
        return False, f"Broadcast scheduler status file is missing: {status_path}"

    try:
        payload = json.loads(status_path.read_text(encoding="utf-8"))
        updated_text = payload.get("updated_at")
        state = str(payload.get("state") or "").strip().lower()
        if not updated_text:
            return False, "Broadcast scheduler status has no updated_at."

        updated_at = timezone.datetime.fromisoformat(updated_text)
        if timezone.is_naive(updated_at):
            updated_at = timezone.make_aware(updated_at, timezone=timezone.get_current_timezone())

        age = (timezone.now() - updated_at).total_seconds()
        interval = max(5, int(getattr(settings, "BROADCAST_SCHEDULER_INTERVAL_SECONDS", 15)))
        stale_after = max(
            int(getattr(settings, "PAO_WATCHDOG_BROADCAST_STALE_SECONDS", 60)),
            interval * 4,
            60,
        )

        if state == "degraded":
            return False, f"Broadcast scheduler is degraded: {payload.get('last_error') or 'unknown error'}"
        if state != "running":
            return False, f"Broadcast scheduler state is {state or 'unknown'}."
        if age > stale_after:
            return False, f"Broadcast scheduler status is stale ({age:.1f}s > {stale_after}s)."
        return True, f"Broadcast scheduler status is current ({age:.1f}s)."
    except Exception as exc:
        return False, f"Unable to read broadcast scheduler status: {type(exc).__name__}: {exc}"


def _inference_polling_health() -> tuple[bool, str]:
    if not getattr(settings, "INFERENCE_POLL_AUTOSTART", False):
        return True, "Inference polling monitoring skipped because autostart is disabled."

    try:
        from apps.ai_bridge.background_polling import inference_polling_thread_alive
        if inference_polling_thread_alive():
            return True, "Inference polling thread is alive."
        return False, "Inference polling autostart is enabled but its background thread is not alive."
    except Exception as exc:
        return False, f"Unable to inspect inference polling service: {type(exc).__name__}: {exc}"


def evaluate_services() -> dict[str, dict[str, object]]:
    results = {}

    if getattr(settings, "PAO_WATCHDOG_MONITOR_INFERENCE_POLLING", True):
        healthy, description = _inference_polling_health()
        _sync_service_fault(
            fault_code="PAO_INFERENCE_POLLING_STOPPED",
            healthy=healthy,
            description=description,
            severity=DeviceFaultLog.SEVERITY_CRITICAL,
        )
        results["inference_polling"] = {"healthy": healthy, "description": description}

    if getattr(settings, "PAO_WATCHDOG_MONITOR_BROADCAST_SCHEDULER", True):
        healthy, description = _broadcast_scheduler_health()
        _sync_service_fault(
            fault_code="PAO_BROADCAST_SCHEDULER_UNHEALTHY",
            healthy=healthy,
            description=description,
            severity=DeviceFaultLog.SEVERITY_WARNING,
        )
        results["broadcast_scheduler"] = {"healthy": healthy, "description": description}

    results["occ_sync_service"] = {
        "healthy": True,
        "description": (
            "Reserved / not monitored."
            if not getattr(settings, "PAO_WATCHDOG_MONITOR_OCC_SYNC_SERVICE", False)
            else "Monitoring requested but no external service heartbeat adapter is configured."
        ),
    }
    return results


def _is_runserver_worker() -> bool:
    argv = [str(item).lower() for item in sys.argv]
    if "runserver" not in argv:
        return False
    if "--noreload" in argv:
        return True
    return os.environ.get("RUN_MAIN", "").lower() == "true"


def _watchdog_loop() -> None:
    startup_delay = max(5, int(getattr(settings, "PAO_SERVICE_WATCHDOG_STARTUP_DELAY_SECONDS", 20)))
    interval = max(10, int(getattr(settings, "PAO_SERVICE_WATCHDOG_INTERVAL_SECONDS", 30)))
    time.sleep(startup_delay)

    while True:
        try:
            close_old_connections()
            results = evaluate_services()
            unhealthy = {k: v for k, v in results.items() if not v.get("healthy", True)}
            if unhealthy:
                logger.warning("PAO service watchdog detected unhealthy services: %s", unhealthy)
        except Exception:
            logger.exception("PAO service watchdog iteration failed.")
        finally:
            close_old_connections()
        time.sleep(interval)


def start_service_watchdog_for_current_process() -> bool:
    global _watchdog_started, _watchdog_thread

    if not getattr(settings, "PAO_SERVICE_WATCHDOG_ENABLED", True):
        return False
    if not _is_runserver_worker():
        return False

    with _start_lock:
        if _watchdog_started:
            return False
        thread = threading.Thread(
            target=_watchdog_loop,
            name="krtc-pao-service-watchdog",
            daemon=True,
        )
        thread.start()
        _watchdog_thread = thread
        _watchdog_started = True
        return True


def service_watchdog_thread_alive() -> bool:
    return bool(_watchdog_thread and _watchdog_thread.is_alive())
