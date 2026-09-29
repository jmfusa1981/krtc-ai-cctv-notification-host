from __future__ import annotations

import logging
import threading
import time

from django.conf import settings
from django.core.management import call_command
from django.db import close_old_connections

logger = logging.getLogger(__name__)
_lock = threading.Lock()
_started = False
_thread = None


def start_zone_count_polling() -> bool:
    global _started, _thread
    with _lock:
        if _started:
            return False
        _started = True
        thread = threading.Thread(target=_run, name="krtc-zone-count-polling", daemon=True)
        thread.start()
        _thread = thread
        return True


def zone_count_polling_thread_alive() -> bool:
    return bool(_thread and _thread.is_alive())


def _run():
    delay = max(0.0, float(getattr(settings, "ZONE_COUNT_POLL_STARTUP_DELAY_SECONDS", 4.0)))
    if delay:
        time.sleep(delay)
    close_old_connections()
    try:
        call_command(
            "poll_zone_counts",
            interval=float(getattr(settings, "ZONE_COUNT_POLL_INTERVAL_SECONDS", 15.0)),
        )
    except Exception:
        logger.exception("The automatic zone-count polling service stopped unexpectedly.")
    finally:
        close_old_connections()
