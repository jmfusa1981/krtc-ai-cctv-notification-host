import hashlib
import platform
import re
import socket
import time
from datetime import datetime, time as day_time, timedelta
from urllib.parse import urljoin

import requests
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.db import models, transaction
from django.db.models import Count
from django.utils import timezone

from apps.ai_bridge.models import InferenceConnectionState, InferenceHost
from apps.cameras.models import Camera
from apps.events.models import Event
from apps.notifications.models import SpeakerDevice
from apps.settings_app.models import StationLocalSettings

from .device_faults import recover_device_fault, report_device_fault
from .models import DeviceFaultLog, OccSyncLog, OccSyncState


OCC_URL_VALIDATOR = URLValidator(schemes=["http", "https"])


def _iso(value):
    return timezone.localtime(value).isoformat() if value else None


def _identity():
    local = StationLocalSettings.load()
    return {
        "station_code": settings.KRTC_STATION_CODE or local.station_code,
        "notification_host_code": settings.KRTC_NOTIFICATION_HOST_CODE,
    }


class OccSyncError(RuntimeError):
    pass


def _redact_error(value):
    text = str(value)
    token = settings.KRTC_OCC_API_TOKEN
    if token:
        text = text.replace(token, "[REDACTED]")
    text = re.sub(r"(?i)(token|authorization|api[-_ ]?key|password|secret)(\s*[:=]\s*)[^\s,;]+", r"\1\2[REDACTED]", text)
    return text[:500]


def _token_report():
    token = settings.KRTC_OCC_API_TOKEN or ""
    return {
        "token_length": len(token),
        "token_sha256_prefix": hashlib.sha256(token.encode("utf-8")).hexdigest()[:8] if token else "",
    }


def _normalize_occ_severity(value):
    """將 PAO 歷史嚴重程度轉成 OCC 正式列舉值。"""
    normalized = str(value or "").strip().lower()
    aliases = {
        "info": "info",
        "low": "info",
        "normal": "info",
        "warning": "warning",
        "warn": "warning",
        "medium": "warning",
        "critical": "critical",
        "high": "critical",
        "severe": "critical",
        "unknown": "unknown",
    }
    return aliases.get(normalized, "unknown")


def _normalize_occ_status(value):
    """將 PAO 處理狀態映射到 OCC 事件狀態，不改寫來源事件。"""
    normalized = str(value or "").strip().lower()
    aliases = {
        "new": "new",
        "processing": "acknowledged",
        "confirmed": "acknowledged",
        "acknowledged": "acknowledged",
        "dismissed": "closed",
        "closed": "closed",
        "unknown": "unknown",
    }
    return aliases.get(normalized, "unknown")


def _normalize_occ_url(value):
    """只傳送 OCC 契約接受的 HTTP/HTTPS URL，不改寫 PAO 原始值。"""
    normalized = str(value or "").strip()
    if not normalized or len(normalized) > 500:
        return ""
    try:
        OCC_URL_VALIDATOR(normalized)
    except ValidationError:
        return ""
    return normalized


def _public_response_body(response):
    try:
        value = response.json() if response.content else {}
    except ValueError:
        value = {"raw": _redact_error(getattr(response, "text", ""))}
    if isinstance(value, dict):
        return value
    return {"response": value}


def _host_status_for_occ(host, state=None, forced_status=None):
    if forced_status:
        return forced_status
    if host.status == InferenceHost.STATUS_ONLINE:
        if host.last_error_at and (not host.last_success_at or host.last_error_at > host.last_success_at):
            return "degraded"
        return "online"
    if host.status == InferenceHost.STATUS_ERROR:
        return "degraded"
    if host.status == InferenceHost.STATUS_OFFLINE:
        return "offline"
    if state and state.connected:
        return "online"
    return "offline"


def _ai_service_status_for_occ(host, state=None, forced_status=None):
    if forced_status == "online":
        return "healthy"
    if forced_status == "degraded":
        return "degraded"
    if forced_status == "offline":
        return "unavailable"
    if state and state.health_status in {"healthy", "ok"}:
        return "healthy"
    if state and state.health_status in {"degraded", "warning"}:
        return "degraded"
    if host.status == InferenceHost.STATUS_ONLINE:
        return "healthy"
    if host.status == InferenceHost.STATUS_ERROR:
        return "degraded"
    return "unavailable"


def _websocket_status_for_occ(state=None, forced_status=None):
    if forced_status == "online":
        return "connected"
    if forced_status in {"degraded", "offline"}:
        return "disconnected"
    if not state:
        return "unknown"
    if state.websocket_status in {"connected", "disconnected", "unknown"}:
        return state.websocket_status
    return "connected" if state.connected else "disconnected"


class OccSyncClient:
    """Fail-isolated, cursor-based PAO reporter for the OCC API."""

    def __init__(self, session=None, sleep=time.sleep):
        self.session = session or requests.Session()
        self.sleep = sleep

    def _url(self, path):
        return urljoin(f"{settings.KRTC_MAINTENANCE_API_BASE_URL}/", path.lstrip("/"))

    def _post(self, kind, path, payload, item_count=0, retries=3, extra_headers=None):
        endpoint = self._url(path)
        log = OccSyncLog.objects.create(kind=kind, status="failed", endpoint=endpoint, item_count=item_count)
        headers = {
            "X-KRTC-API-Key": settings.KRTC_OCC_API_TOKEN,
            "Content-Type": "application/json",
            "X-KRTC-Station-Code": _identity()["station_code"],
            "X-KRTC-Notification-Host-Code": _identity()["notification_host_code"],
        }
        if extra_headers:
            headers.update(extra_headers)
        last_error = ""
        for attempt in range(retries):
            try:
                response = self.session.post(
                    endpoint,
                    json=payload,
                    headers=headers,
                    timeout=settings.KRTC_REQUEST_TIMEOUT,
                    verify=settings.KRTC_OCC_VERIFY_TLS,
                )
                if response.status_code >= 500:
                    raise OccSyncError(f"OCC server returned {response.status_code}")
                if response.status_code >= 400:
                    log.http_status = response.status_code
                    response_body = _redact_error(getattr(response, "text", ""))
                    detail = f": {response_body}" if response_body else ""
                    raise OccSyncError(f"OCC rejected request with {response.status_code}{detail}")
                summary = _public_response_body(response)
                if not isinstance(summary, dict):
                    summary = {"response_type": type(summary).__name__}
                log.status = "success"
                log.http_status = response.status_code
                log.response_summary = {key: summary[key] for key in ("status", "accepted", "duplicate") if key in summary}
                log.finished_at = timezone.now()
                log.save(update_fields=["status", "http_status", "response_summary", "finished_at"])
                self._mark_success()
                return {
                    "http_status": response.status_code,
                    "response_body": summary,
                    "endpoint": endpoint,
                }
            except (requests.RequestException, ValueError, OccSyncError) as exc:
                last_error = _redact_error(exc)
                if attempt + 1 < retries:
                    self.sleep((1, 2, 5)[attempt])
        log.error = last_error
        log.finished_at = timezone.now()
        log.save(update_fields=["http_status", "error", "finished_at"])
        self._mark_failure(last_error)
        raise OccSyncError(last_error)

    @staticmethod
    def _mark_success():
        state = OccSyncState.load()
        state.last_success_at = timezone.now()
        state.consecutive_failures = 0
        state.last_error = ""
        state.save(update_fields=["last_success_at", "consecutive_failures", "last_error"])

        try:
            recover_device_fault(
                device_type=DeviceFaultLog.DEVICE_OCC_NETWORK,
                device_code=settings.KRTC_NOTIFICATION_HOST_CODE or "PAO",
                fault_code="OCC_SYNC_UNAVAILABLE",
            )
        except Exception:
            pass

    @staticmethod
    def _mark_failure(error):
        state = OccSyncState.load()
        state.consecutive_failures += 1
        state.last_error = error[:500]
        state.save(update_fields=["consecutive_failures", "last_error"])

        if state.consecutive_failures >= 3:
            try:
                report_device_fault(
                    device_type=DeviceFaultLog.DEVICE_OCC_NETWORK,
                    device_code=settings.KRTC_NOTIFICATION_HOST_CODE or "PAO",
                    device_name="PAO to OCC synchronization",
                    area="PAO/OCC",
                    fault_code="OCC_SYNC_UNAVAILABLE",
                    fault_description=error[:500],
                    severity=DeviceFaultLog.SEVERITY_WARNING,
                )
            except Exception:
                pass

    def send_heartbeat(self, forced_host_status=None):
        now = timezone.now()
        local = StationLocalSettings.load()
        state = OccSyncState.load()
        sequence = state.heartbeat_sequence
        payload = {
            "schema_version": "1.1",
            **_identity(),
            "sequence": sequence,
            "sent_at": _iso(now),
            "notification_host": {
                "host_code": settings.KRTC_NOTIFICATION_HOST_CODE,
                "hostname": socket.gethostname(),
                "ip_address": settings.KRTC_NOTIFICATION_HOST_IP,
                "status": "online",
                "application_version": settings.KRTC_APP_VERSION,
                "os": platform.system() or "Windows",
            },
            "inference_hosts": [
                self._heartbeat_inference_host(item, forced_host_status)
                for item in InferenceHost.objects.filter(is_active=True).order_by("host_code")
            ],
        }
        result = self._post(
            "heartbeat",
            settings.KRTC_OCC_HEARTBEAT_PATH,
            payload,
            extra_headers={"Idempotency-Key": f'{payload["notification_host_code"]}-{sequence}'},
        )
        with transaction.atomic():
            locked = OccSyncState.objects.select_for_update().get(pk=state.pk)
            locked.last_heartbeat_at = now
            locked.heartbeat_sequence = max(locked.heartbeat_sequence, sequence + 1)
            locked.save(update_fields=["last_heartbeat_at", "heartbeat_sequence"])
        return {
            "sent_at": payload["sent_at"],
            "sequence": sequence,
            "http_status": result.get("http_status"),
            "response_body": result.get("response_body"),
            "payload": payload,
            **_token_report(),
        }

    @staticmethod
    def _heartbeat_inference_host(host, forced_host_status=None):
        state = InferenceConnectionState.objects.filter(inference_host=host).first()
        last_event = Event.objects.filter(inference_host_code=host.host_code).order_by("-detected_at").first()
        last_event_at = (state.last_event_at if state else None) or (last_event.detected_at if last_event else None)
        return {
            "inference_host_code": host.host_code,
            "name": host.name,
            "ip_address": str(host.ip_address or ""),
            "port": host.port,
            "api_base_url": host.normalized_base_url,
            "host_status": _host_status_for_occ(host, state, forced_host_status),
            "ai_service_status": _ai_service_status_for_occ(host, state, forced_host_status),
            "websocket_status": _websocket_status_for_occ(state, forced_host_status),
            "application_version": host.application_version or "1.2.0",
            "last_seen_at": _iso(host.last_success_at),
            "last_event_at": _iso(last_event_at),
        }

    def send_device_status(self):
        payload = {
            **_identity(),
            "reported_at": _iso(timezone.now()),
            "inference_hosts": list(InferenceHost.objects.values("host_code", "status", "is_active", "last_success_at", "last_error_at")),
            "cameras": list(
                Camera.objects.values(
                    "camera_code",
                    "name",
                    "area",
                    "status",
                    "is_active",
                    "last_checked_at",
                )
            ),
            "speakers": list(
                SpeakerDevice.objects.values(
                    "speaker_code",
                    "name",
                    "area",
                    "ip_address",
                    "status",
                    "is_active",
                    "last_checked_at",
                )
            ),
        }
        for group in ("inference_hosts", "cameras", "speakers"):
            for item in payload[group]:
                for key, value in tuple(item.items()):
                    if isinstance(value, datetime):
                        item[key] = _iso(value)
        count = sum(len(payload[key]) for key in ("inference_hosts", "cameras", "speakers"))
        return self._post("devices", settings.KRTC_OCC_DEVICE_STATUS_PATH, payload, count)

    def send_pending_events(self):
        state = OccSyncState.load()
        batch_size = settings.KRTC_OCC_EVENT_BATCH_SIZE
        host_rows = list(
            InferenceHost.objects.filter(is_active=True).values(
                "host_code",
                "base_url",
            )
        )
        host_codes = {str(row["host_code"]).strip() for row in host_rows}
        host_code_by_url = {
            str(row["base_url"] or "").strip().rstrip("/"): str(
                row["host_code"]
            ).strip()
            for row in host_rows
            if str(row["base_url"] or "").strip()
        }
        events = []
        items = []
        rejected_events = []
        batch_identities = set()
        queryset = (
            Event.objects.select_related("camera")
            .filter(occ_sync_status__in=["pending", "failed"])
            .order_by("id")
        )
        for event in queryset.iterator(chunk_size=max(batch_size, 100)):
            item, rejection_reason = self._event_for_occ(
                event,
                host_codes=host_codes,
                host_code_by_url=host_code_by_url,
            )
            if rejection_reason:
                event.occ_sync_status = "rejected"
                event.occ_sync_attempts += 1
                event.occ_last_attempt_at = timezone.now()
                event.occ_last_error = rejection_reason[:500]
                rejected_events.append(event)
                continue
            identity = (item["source_host_code"], item["source_event_id"])
            if identity in batch_identities:
                continue
            batch_identities.add(identity)
            events.append(event)
            items.append(item)
            if len(events) >= batch_size:
                break
        if rejected_events:
            Event.objects.bulk_update(
                rejected_events,
                [
                    "occ_sync_status",
                    "occ_sync_attempts",
                    "occ_last_attempt_at",
                    "occ_last_error",
                ],
                batch_size=max(batch_size, 100),
            )
        if not events:
            status_value = (
                "no_sendable_events"
                if rejected_events
                else "no_pending_events"
            )
            return {
                "status": status_value,
                "count": 0,
                "rejected_count": len(rejected_events),
            }
        payload = {**_identity(), "reported_at": _iso(timezone.now()), "events": items}
        now = timezone.now()
        Event.objects.filter(pk__in=[event.pk for event in events]).update(occ_sync_attempts=models.F("occ_sync_attempts") + 1, occ_last_attempt_at=now)
        try:
            self._post("events", settings.KRTC_OCC_EVENTS_PATH, payload, len(items))
        except OccSyncError as exc:
            Event.objects.filter(pk__in=[event.pk for event in events]).update(occ_sync_status="failed", occ_last_error=str(exc)[:500])
            raise
        Event.objects.filter(pk__in=[event.pk for event in events]).update(occ_sync_status="synced", occ_synced_at=timezone.now(), occ_last_error="")
        with transaction.atomic():
            locked = OccSyncState.objects.select_for_update().get(pk=state.pk)
            locked.last_event_id = max(locked.last_event_id, events[-1].id)
            locked.save(update_fields=["last_event_id"])
        return {
            "status": "sent",
            "count": len(items),
            "rejected_count": len(rejected_events),
            "last_event_id": events[-1].id,
        }

    @staticmethod
    def _event_for_occ(event, host_codes, host_code_by_url):
        """建立可驗證的 OCC payload；無法證明 Identity 時明確隔離。"""
        inference_code = str(event.inference_host_code or "").strip()
        source_value = str(event.source_host or "").strip()
        source_code = ""
        if inference_code in host_codes:
            source_code = inference_code
        elif source_value in host_codes:
            source_code = source_value
        else:
            source_code = host_code_by_url.get(source_value.rstrip("/"), "")
        if not source_code:
            return None, "OCC_EVENT_IDENTITY_MISSING: 無法確認來源推論主機代碼。"

        source_event_id = str(event.source_event_id or "").strip()
        if not source_event_id:
            return None, "OCC_EVENT_IDENTITY_MISSING: 缺少來源事件 ID。"

        event_code = str(event.event_code or "").strip()
        event_type = str(event.event_type or "").strip()
        if not event_code and not event_type:
            return None, "OCC_EVENT_TYPE_MISSING: 缺少事件代碼與事件類型。"

        confidence = event.confidence
        if confidence is not None and not 0 <= confidence <= 1:
            confidence = None
        snapshot_url = _normalize_occ_url(event.snapshot_url)
        video_url = _normalize_occ_url(event.video_url)
        return {
            "pao_event_id": event.id,
            "source_host": source_code,
            "source_host_code": source_code,
            "source_event_id": source_event_id,
            "camera_code": event.camera_code
            or (event.camera.camera_code if event.camera else ""),
            "event_id": event.event_id,
            "inference_host_code": source_code,
            "event_code": event_code,
            "mapping_status": event.mapping_status,
            "video_url": video_url,
            "event_type": event_type,
            "severity": _normalize_occ_severity(event.severity),
            "status": _normalize_occ_status(event.status),
            "confidence": confidence,
            "notification_content": event.description or "",
            "detected_at": _iso(event.detected_at),
            "source_updated_at": _iso(event.updated_at),
            "snapshot_url": snapshot_url,
        }, ""

    def send_daily_sync(self, target_date=None):
        target_date = target_date or (timezone.localdate() - timedelta(days=1))
        tz = timezone.get_current_timezone()
        start = timezone.make_aware(datetime.combine(target_date, day_time.min), tz)
        end = start + timedelta(days=1)
        local = StationLocalSettings.load()
        event_rows = list(Event.objects.filter(detected_at__gte=start, detected_at__lt=end).values("event_type").annotate(count=Count("id")).order_by("event_type"))
        payload = {
            **_identity(),
            "summary_date": target_date.isoformat(),
            "generated_at": _iso(timezone.now()),
            "config_version": str(local.config_version),
            "application_version": settings.KRTC_APP_VERSION,
            "broadcast_mode": settings.BROADCAST_PLAYBACK_MODE,
            "event_summary": {row["event_type"]: row["count"] for row in event_rows},
            "event_total": sum(row["count"] for row in event_rows),
            "device_counts": {
                "inference_hosts": InferenceHost.objects.count(),
                "cameras": Camera.objects.count(),
                "speakers": SpeakerDevice.objects.count(),
            },
        }
        payload["idempotency_key"] = hashlib.sha256(
            f'{payload["station_code"]}:{payload["notification_host_code"]}:{target_date.isoformat()}'.encode()
        ).hexdigest()
        result = self._post("daily", settings.KRTC_OCC_DAILY_SYNC_PATH, payload, payload["event_total"])
        state = OccSyncState.load()
        state.last_daily_sync_at = timezone.now()
        state.save(update_fields=["last_daily_sync_at"])
        return result


def daily_sync_due(now=None):
    now = timezone.localtime(now or timezone.now())
    state = OccSyncState.load()
    if now.hour < settings.KRTC_OCC_DAILY_SYNC_HOUR:
        return False
    return not state.last_daily_sync_at or timezone.localtime(state.last_daily_sync_at).date() < now.date()
