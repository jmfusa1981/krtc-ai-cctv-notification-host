from __future__ import annotations

import time

from django.conf import settings
from django.utils import timezone

from apps.ai_bridge.models import InferenceHost
from apps.ai_bridge.services.health_state import HEALTHY, effective_inference_health
from apps.cameras.models import Camera
from apps.cameras.monitor_diagnostics import collect_mediamtx_path_readiness
from apps.notifications.models import SpeakerDevice

from .client import OccHttpClient, OccResult
from .config import OccIntegrationConfig
from .signing import generate_request_id
from .state import (
    record_attempt,
    record_configuration,
    record_failure,
    record_success,
)


PROCESS_STARTED_MONOTONIC = time.monotonic()


def _camera_summary() -> dict:
    """以 canonical Media Availability 統計 Camera，不讀 DB online 作真相。"""

    cameras = list(Camera.objects.filter(is_active=True).order_by("camera_code"))
    readiness = collect_mediamtx_path_readiness(cameras=cameras)
    details = readiness.get("path_details") or {}
    available = sum(
        1
        for camera in cameras
        if bool((details.get(camera.camera_code) or {}).get("media_ready"))
    )
    return {
        "total": len(cameras),
        "media_available": available,
        "media_unavailable": len(cameras) - available,
        "mediamtx_reachable": bool(readiness.get("reachable")),
    }


def _speaker_summary() -> dict:
    """摘要既有 Speaker probe 狀態，不觸發播放或 PJSIP。"""

    speakers = SpeakerDevice.objects.filter(is_active=True)
    total = speakers.count()
    available = speakers.filter(status=SpeakerDevice.STATUS_ONLINE).count()
    return {
        "total": total,
        "available": available,
        "unavailable": total - available,
    }


def _inference_summary() -> dict:
    """重用 inference effective health 計算，不啟動額外輪詢。"""

    hosts = list(
        InferenceHost.objects.filter(is_active=True)
        .select_related("connection_state")
        .order_by("host_code")
    )
    healthy = sum(
        1
        for host in hosts
        if effective_inference_health(host).effective_health == HEALTHY
    )
    return {
        "total": len(hosts),
        "healthy": healthy,
        "unhealthy": len(hosts) - healthy,
    }


def build_heartbeat_payload(
    config: OccIntegrationConfig | None = None,
    *,
    request_id: str | None = None,
    now=None,
    uptime_seconds: int | None = None,
) -> dict:
    """建立與傳輸分離、可重現測試的 Heartbeat payload。"""

    active_config = config or OccIntegrationConfig.from_settings()
    observed_at = now or timezone.now()
    uptime = (
        max(0, int(uptime_seconds))
        if uptime_seconds is not None
        else max(0, int(time.monotonic() - PROCESS_STARTED_MONOTONIC))
    )
    return {
        "schema_version": "1.0",
        "request_id": request_id or generate_request_id(),
        "station_code": active_config.station_code,
        "host_code": active_config.host_code,
        "timestamp": observed_at.isoformat(),
        "status": "online",
        "application_version": settings.KRTC_APP_VERSION,
        "uptime_seconds": uptime,
        "camera_summary": _camera_summary(),
        "speaker_summary": _speaker_summary(),
        "inference_summary": _inference_summary(),
    }


class HeartbeatSender:
    """協調 payload、HTTP transport 與本機 integration state。"""

    path = "/api/v1/heartbeat/"

    def __init__(self, config=None, client=None):
        self.config = config or OccIntegrationConfig.from_settings()
        self.client = client or OccHttpClient(config=self.config)

    def build_request(self, **kwargs) -> dict:
        """只建立 request，便於 diagnostics dry-run 與單元測試。"""

        return build_heartbeat_payload(self.config, **kwargs)

    @property
    def session(self):
        """保留 service 對獨立 HTTP session 的可觀測性。"""

        return self.client.session

    def send(self) -> OccResult:
        """送出一次 Heartbeat 並更新不含敏感資料的 runtime state。"""

        record_configuration(
            enabled=self.config.enabled,
            configured=self.config.configured,
        )
        if not self.config.enabled:
            return OccHttpClient._failure(
                "",
                "integration_disabled",
                "OCC integration is disabled.",
                False,
            )
        payload = self.build_request()
        record_attempt()
        result = self.client.post_json(self.path, payload)
        if result.success:
            record_success()
        else:
            safe_message = result.error.message
            if self.config.shared_secret:
                safe_message = safe_message.replace(
                    self.config.shared_secret,
                    "[REDACTED]",
                )
            record_failure(
                result.error.code,
                safe_message,
                reachable=result.http_status is not None,
            )
        return result

    def send_heartbeat(self) -> OccResult:
        """提供既有 dedicated service 使用的失敗即例外介面。"""

        result = self.send()
        if not result.success:
            raise RuntimeError(
                f"OCC HMAC heartbeat failed: {result.error.code}"
            )
        return result
