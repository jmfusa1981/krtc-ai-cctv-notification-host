from __future__ import annotations

import asyncio
import logging
import threading
import time

from django.conf import settings
from django.db import close_old_connections

logger = logging.getLogger(__name__)

_start_lock = threading.Lock()
_started = False


def start_inference_websocket_listener() -> bool:
    """Start the multi-host WebSocket listener once in the Django process."""
    global _started

    with _start_lock:
        if _started:
            return False
        _started = True

        thread = threading.Thread(
            target=_run_listener_service,
            name="krtc-inference-websocket",
            daemon=True,
        )
        thread.start()
        return True


def _run_listener_service() -> None:
    delay = max(
        0.0,
        float(getattr(settings, "INFERENCE_WS_AUTOSTART_DELAY_SECONDS", 3.0)),
    )
    if delay:
        time.sleep(delay)

    close_old_connections()
    try:
        asyncio.run(_supervise_listeners())
    except Exception:
        logger.exception("The automatic inference WebSocket service stopped unexpectedly.")
    finally:
        close_old_connections()


async def _supervise_listeners() -> None:
    """Keep listeners alive and periodically detect host configuration changes."""
    refresh_seconds = max(
        5.0,
        float(getattr(settings, "INFERENCE_WS_HOST_REFRESH_SECONDS", 30.0)),
    )
    tasks: dict[int, asyncio.Task] = {}
    signatures: dict[int, tuple[str, str, int]] = {}

    while True:
        close_old_connections()
        hosts = await asyncio.to_thread(_load_active_hosts)
        active_ids = {host.pk for host in hosts}

        # Stop listeners for disabled or deleted hosts.
        for host_id in list(tasks):
            if host_id not in active_ids:
                tasks[host_id].cancel()
                await asyncio.gather(tasks[host_id], return_exceptions=True)
                tasks.pop(host_id, None)
                signatures.pop(host_id, None)

        # Start or restart listeners for new or changed hosts.
        for host in hosts:
            signature = (
                host.websocket_url or "",
                host.normalized_base_url,
                int(host.timeout_seconds),
            )
            task = tasks.get(host.pk)
            needs_restart = (
                task is None
                or task.done()
                or signatures.get(host.pk) != signature
            )
            if not needs_restart:
                continue

            if task is not None and not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)

            tasks[host.pk] = asyncio.create_task(
                _run_host_listener(host),
                name=f"krtc-ws-{host.host_code}",
            )
            signatures[host.pk] = signature

        await asyncio.sleep(refresh_seconds)


def _load_active_hosts():
    from apps.ai_bridge.models import InferenceHost

    close_old_connections()
    try:
        return list(InferenceHost.objects.filter(is_active=True).order_by("host_code"))
    finally:
        close_old_connections()


async def _run_host_listener(host) -> None:
    from apps.ai_bridge.websocket_client import InferenceWebSocketReceiver

    receiver = InferenceWebSocketReceiver(inference_host=host)
    logger.info(
        "Automatic inference WebSocket listener started: host=%s url=%s",
        host.host_code,
        receiver.ws_url,
    )
    try:
        await receiver.run_forever()
    except asyncio.CancelledError:
        logger.info(
            "Automatic inference WebSocket listener stopped: host=%s",
            host.host_code,
        )
        raise
    except Exception:
        logger.exception(
            "Automatic inference WebSocket listener failed: host=%s",
            host.host_code,
        )
