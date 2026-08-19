from __future__ import annotations

import logging
import threading
import time

from django.conf import settings
from django.core.management import call_command
from django.db import close_old_connections

logger = logging.getLogger(__name__)

_start_lock = threading.Lock()
_started = False


def start_inference_polling() -> bool:
    """Start the inference-host polling loop once in the Django process."""
    global _started

    with _start_lock:
        if _started:
            return False
        _started = True

        thread = threading.Thread(
            target=_run_polling_command,
            name="krtc-inference-polling",
            daemon=True,
        )
        thread.start()
        return True


def _run_polling_command() -> None:
    delay = max(
        0.0,
        float(getattr(settings, "INFERENCE_POLL_STARTUP_DELAY_SECONDS", 2.0)),
    )
    if delay:
        time.sleep(delay)

    close_old_connections()
    try:
        call_command(
            "poll_inference_hosts",
            interval=float(getattr(settings, "INFERENCE_POLL_INTERVAL_SECONDS", 5.0)),
            limit=int(getattr(settings, "INFERENCE_POLL_EVENT_LIMIT", 100)),
            offset=int(getattr(settings, "INFERENCE_POLL_EVENT_OFFSET", 0)),
        )
    except Exception:
        logger.exception("The automatic inference-host polling service stopped unexpectedly.")
    finally:
        close_old_connections()
