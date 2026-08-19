from __future__ import annotations

import asyncio
import json
import logging
from datetime import timedelta
from typing import Any

from django.db import close_old_connections
from django.utils import timezone

from apps.ai_bridge.models import InferenceConnectionState, InferenceHost
from apps.ai_bridge.services.event_importer import EventImporter, ImportItemResult
from apps.ai_bridge.services.inference_client import InferenceClient

logger = logging.getLogger(__name__)


def parse_formal_event(raw: str) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("invalid_json") from exc
    if not isinstance(value, dict):
        raise ValueError("event_not_object")
    return value


class InferenceWebSocketReceiver:
    def __init__(self, *, inference_host: InferenceHost) -> None:
        self.host = inference_host
        self.client = InferenceClient(inference_host.normalized_base_url, inference_host.timeout_seconds)
        self.importer = EventImporter(client=self.client, inference_host=inference_host)
        self.ws_url = inference_host.websocket_url or inference_host.normalized_base_url.replace("http", "ws", 1) + "/ws/alerts"

    async def run_forever(self, stop_event: asyncio.Event | None = None) -> None:
        import websockets
        delays = (1, 2, 5, 10, 30)
        attempt = 0
        while not (stop_event and stop_event.is_set()):
            try:
                async with websockets.connect(self.ws_url, open_timeout=self.host.timeout_seconds,
                                              max_size=1024 * 1024, ping_interval=20, ping_timeout=20) as ws:
                    await asyncio.to_thread(self._mark_connected)
                    await asyncio.to_thread(self.catch_up)
                    attempt = 0
                    async for raw in ws:
                        if stop_event and stop_event.is_set():
                            break
                        if isinstance(raw, bytes):
                            logger.warning("Ignoring binary frame from %s", self.host.host_code)
                            continue
                        await self.handle_message(raw)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                await asyncio.to_thread(self._mark_disconnected, exc)
                await asyncio.sleep(delays[min(attempt, len(delays) - 1)])
                attempt += 1

    async def handle_message(self, raw: str) -> ImportItemResult | None:
        try:
            payload = parse_formal_event(raw)
            result = await asyncio.to_thread(self._import, payload, "websocket", True)
            await asyncio.to_thread(self._record_result, result, payload)
            return result
        except ValueError as exc:
            await asyncio.to_thread(self._record_error, exc)
            return None

    def catch_up(self) -> int:
        state, _ = InferenceConnectionState.objects.get_or_create(inference_host=self.host)
        until = timezone.now()
        since = (state.last_successful_event_at - timedelta(seconds=5)) if state.last_successful_event_at else (until - timedelta(minutes=5))
        imported, offset, limit = 0, 0, 500
        while True:
            items = self.client.get_events(since=since.isoformat(), until=until.isoformat(), limit=limit, offset=offset).get("items", [])
            ordered = sorted(items, key=lambda item: (str(item.get("timestamp") or ""), str(item.get("id") or "")))
            for payload in ordered:
                result = self._import(payload, "catchup", True)
                imported += int(result.status == "imported")
                self._record_result(result, payload)
            if len(items) < limit:
                break
            offset += limit
        state.last_catchup_at = timezone.now()
        state.save(update_fields=["last_catchup_at", "updated_at"])
        return imported

    def _import(self, payload, mode, allow_broadcast):
        close_old_connections()
        try:
            return self.importer.import_payload(payload, ingestion_mode=mode, allow_broadcast=allow_broadcast)
        finally:
            close_old_connections()

    def _record_result(self, result, payload):
        now = timezone.now()
        values = {"connected": True, "websocket_status": "connected", "last_message_at": now, "last_error": ""}
        if result.status == "imported":
            values["last_event_at"] = now
            from django.utils.dateparse import parse_datetime
            occurred = parse_datetime(str(payload.get("timestamp") or ""))
            if occurred:
                values["last_successful_event_at"] = occurred
            values["last_source_event_id"] = str(payload.get("id") or "")
        InferenceConnectionState.objects.update_or_create(inference_host=self.host, defaults=values)

    def _mark_connected(self):
        now = timezone.now()
        InferenceConnectionState.objects.update_or_create(inference_host=self.host, defaults={
            "connected": True, "websocket_status": "connected", "last_connected_at": now, "last_error": ""})

    def _mark_disconnected(self, exc):
        state, _ = InferenceConnectionState.objects.get_or_create(inference_host=self.host)
        state.connected = False
        state.websocket_status = "disconnected"
        state.last_disconnected_at = timezone.now()
        state.reconnect_count += 1
        state.last_error = str(exc)[:1000]
        state.save()

    def _record_error(self, exc):
        InferenceConnectionState.objects.update_or_create(inference_host=self.host, defaults={
            "last_message_at": timezone.now(), "last_error": str(exc)[:1000]})
