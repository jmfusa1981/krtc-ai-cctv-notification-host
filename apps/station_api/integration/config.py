from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit

from django.conf import settings


@dataclass(frozen=True)
class OccIntegrationConfig:
    """集中解析 PAO 對 OCC 的唯讀環境設定。"""

    enabled: bool
    base_url: str
    station_code: str
    host_code: str
    shared_secret: str
    connect_timeout: float
    read_timeout: float
    heartbeat_interval: int

    @classmethod
    def from_settings(cls) -> "OccIntegrationConfig":
        """從 Django settings 建立不可變設定快照。"""

        return cls(
            enabled=bool(getattr(settings, "KRTC_OCC_SYNC_ENABLED", False)),
            base_url=str(getattr(settings, "KRTC_OCC_BASE_URL", "") or "").rstrip("/"),
            station_code=str(getattr(settings, "KRTC_STATION_CODE", "") or "").strip(),
            host_code=str(
                getattr(settings, "KRTC_NOTIFICATION_HOST_CODE", "") or ""
            ).strip(),
            shared_secret=str(
                getattr(settings, "KRTC_OCC_SHARED_SECRET", "") or ""
            ),
            connect_timeout=max(
                0.1,
                float(getattr(settings, "KRTC_OCC_CONNECT_TIMEOUT_SECONDS", 3)),
            ),
            read_timeout=max(
                0.1,
                float(getattr(settings, "KRTC_OCC_READ_TIMEOUT_SECONDS", 5)),
            ),
            heartbeat_interval=max(
                1,
                int(getattr(settings, "KRTC_HEARTBEAT_INTERVAL", 10)),
            ),
        )

    @property
    def configuration_errors(self) -> tuple[str, ...]:
        """回傳安全且不包含密鑰內容的設定缺漏。"""

        errors = []
        parsed = urlsplit(self.base_url)
        if parsed.scheme != "http" or not parsed.netloc:
            errors.append("occ_base_url")
        if not self.station_code:
            errors.append("station_code")
        if not self.host_code:
            errors.append("host_code")
        if not self.shared_secret:
            errors.append("shared_secret")
        return tuple(errors)

    @property
    def configured(self) -> bool:
        """指出所有送出 HMAC request 的必要設定是否完整。"""

        return not self.configuration_errors

    def public_dict(self) -> dict:
        """輸出診斷可用且不含 shared secret 的設定。"""

        return {
            "enabled": self.enabled,
            "configured": self.configured,
            "base_url": self.base_url,
            "station_code": self.station_code,
            "host_code": self.host_code,
            "connect_timeout_seconds": self.connect_timeout,
            "read_timeout_seconds": self.read_timeout,
            "heartbeat_interval_seconds": self.heartbeat_interval,
            "configuration_errors": list(self.configuration_errors),
        }
