from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from django.conf import settings
from django.db import OperationalError, ProgrammingError


@dataclass(frozen=True)
class BroadcastRuntimeConfig:
    """Resolved IP Speaker / PJSIP runtime configuration."""

    environment: str
    operational_backend: str

    pjsip_executable_path: str
    pjsip_local_ip: str
    pjsip_advertise_ip: str

    pjsip_local_sip_port_base: int
    pjsip_local_rtp_port_base: int
    pjsip_port_step: int
    pjsip_audio_gain_percent: float

    source: str

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def executable_exists(self) -> bool:
        if not self.pjsip_executable_path:
            return False

        return Path(self.pjsip_executable_path).is_file()

    @property
    def is_pjsip_configured(self) -> bool:
        return bool(
            self.pjsip_executable_path
            and self.pjsip_local_ip
            and self.pjsip_advertise_ip
        )


def _setting(name: str, default=None):
    return getattr(settings, name, default)


def _settings_fallback() -> BroadcastRuntimeConfig:
    """Build runtime configuration from Django settings / .env."""

    is_production = bool(
        _setting("KRTC_PRODUCTION", False)
    )

    configured_mode = str(
        _setting(
            "BROADCAST_PLAYBACK_MODE",
            "simulation",
        )
        or "simulation"
    ).strip().lower()

    # Production operational broadcast is always PJSIP.
    #
    # Development keeps the existing configured mode so simulation remains
    # available for development and engineering workflow validation.
    operational_backend = (
        "pjsip"
        if is_production
        else configured_mode
    )

    local_ip = str(
        _setting("PJSIP_LOCAL_IP", "")
        or ""
    ).strip()

    advertise_ip = str(
        _setting(
            "PJSIP_ADVERTISE_IP",
            local_ip,
        )
        or local_ip
    ).strip()

    return BroadcastRuntimeConfig(
        environment=(
            "production"
            if is_production
            else "development"
        ),
        operational_backend=operational_backend,
        pjsip_executable_path=str(
            _setting(
                "PJSIP_EXECUTABLE_PATH",
                "",
            )
            or ""
        ).strip(),
        pjsip_local_ip=local_ip,
        pjsip_advertise_ip=advertise_ip,
        pjsip_local_sip_port_base=int(
            _setting(
                "PJSIP_LOCAL_SIP_PORT_BASE",
                64882,
            )
        ),
        pjsip_local_rtp_port_base=int(
            _setting(
                "PJSIP_LOCAL_RTP_PORT_BASE",
                4004,
            )
        ),
        pjsip_port_step=int(
            _setting(
                "PJSIP_PORT_STEP",
                2,
            )
        ),
        pjsip_audio_gain_percent=float(
            _setting(
                "PJSIP_AUDIO_GAIN_PERCENT",
                100,
            )
        ),
        source="django-settings",
    )


def get_broadcast_runtime_config() -> BroadcastRuntimeConfig:
    """Return effective broadcast runtime configuration.

    Resolution policy:

    1. Django settings / .env always provide a safe fallback.
    2. BroadcastEngineeringSettings overrides mutable PJSIP values when
       the singleton exists and the individual value is configured.
    3. Production operational backend is always PJSIP.
    4. Database unavailability must not break Django startup, migrations,
       management commands, or unrelated Windows services.
    """

    fallback = _settings_fallback()

    try:
        from apps.settings_app.models import BroadcastEngineeringSettings

        engineering = (
            BroadcastEngineeringSettings.objects
            .filter(
                pk=BroadcastEngineeringSettings.SINGLETON_PK
            )
            .first()
        )

    except (OperationalError, ProgrammingError):
        return fallback

    if engineering is None:
        return fallback

    executable_path = (
        str(engineering.pjsip_executable_path or "").strip()
        or fallback.pjsip_executable_path
    )

    local_ip = (
        str(engineering.pjsip_local_ip or "").strip()
        or fallback.pjsip_local_ip
    )

    advertise_ip = (
        str(engineering.pjsip_advertise_ip or "").strip()
        or fallback.pjsip_advertise_ip
        or local_ip
    )

    return BroadcastRuntimeConfig(
        environment=fallback.environment,
        operational_backend=(
            "pjsip"
            if fallback.is_production
            else fallback.operational_backend
        ),
        pjsip_executable_path=executable_path,
        pjsip_local_ip=local_ip,
        pjsip_advertise_ip=advertise_ip,
        pjsip_local_sip_port_base=int(
            engineering.pjsip_local_sip_port_base
        ),
        pjsip_local_rtp_port_base=int(
            engineering.pjsip_local_rtp_port_base
        ),
        pjsip_port_step=int(
            engineering.pjsip_port_step
        ),
        pjsip_audio_gain_percent=float(
            engineering.pjsip_audio_gain_percent
        ),
        source="broadcast-engineering-settings",
    )