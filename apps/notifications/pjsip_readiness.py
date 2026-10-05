from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from django.conf import settings

from apps.notifications.backends.pjsip import (
    PjsipPlaybackPlan,
    PjsipPreflightError,
    build_pjsip_playback_plan,
)
from apps.notifications.models import AudioFile, SpeakerDevice
from apps.notifications.runtime_config import (
    BroadcastRuntimeConfig,
    get_broadcast_runtime_config,
)


@dataclass(frozen=True)
class PjsipReadiness:
    """封裝一次 PJSIP 播放前置檢查的有效輸入與播放計畫。"""

    runtime_config: BroadcastRuntimeConfig
    speaker: SpeakerDevice
    audio_file: AudioFile
    slot: int
    plan: PjsipPlaybackPlan


def prepare_pjsip_readiness(
    *,
    speaker_code: str,
    audio_code: str,
    log_path: Path,
    slot: int | None = None,
    check_ports: bool = True,
    audio_gain_percent: float | None = None,
    runtime_config: BroadcastRuntimeConfig | None = None,
) -> PjsipReadiness:
    """驗證真實播放必要條件，但不啟動 PJSUA 或呼叫 Speaker。"""

    runtime_config = runtime_config or get_broadcast_runtime_config()
    if runtime_config.operational_backend != "pjsip":
        raise PjsipPreflightError(
            "Operational backend must be pjsip for a real playback preflight. "
            f"Current backend: {runtime_config.operational_backend}."
        )

    speaker = _get_speaker(speaker_code)
    _validate_speaker(speaker)

    audio_file = _get_audio(audio_code)
    _validate_audio(audio_file)

    if slot is None:
        slot = SpeakerDevice.objects.filter(
            is_active=True,
            speaker_code__lt=speaker.speaker_code,
        ).count()
    if slot < 0:
        raise PjsipPreflightError("Speaker slot must be zero or greater.")

    port_step = runtime_config.pjsip_port_step
    local_sip_port = (
        runtime_config.pjsip_local_sip_port_base
        + slot * port_step
    )
    local_rtp_port = (
        runtime_config.pjsip_local_rtp_port_base
        + slot * port_step
    )

    try:
        audio_path = audio_file.file.path
    except (ValueError, NotImplementedError) as exc:
        raise PjsipPreflightError(
            f"AudioFile has no usable local path: {audio_code}: {exc}"
        ) from exc

    plan = build_pjsip_playback_plan(
        executable_path=runtime_config.pjsip_executable_path,
        audio_path=audio_path,
        log_path=log_path,
        speaker_ip=speaker.ip_address,
        sip_uri=speaker.resolved_sip_uri,
        local_ip=runtime_config.pjsip_local_ip,
        advertise_ip=runtime_config.pjsip_advertise_ip,
        local_sip_port=local_sip_port,
        local_rtp_port=local_rtp_port,
        disabled_codecs=settings.PJSIP_DISABLED_CODECS,
        preferred_codec=speaker.preferred_codec,
        log_level=settings.PJSIP_LOG_LEVEL,
        app_log_level=settings.PJSIP_APP_LOG_LEVEL,
        audio_gain_percent=(
            runtime_config.pjsip_audio_gain_percent
            if audio_gain_percent is None
            else audio_gain_percent
        ),
        check_ports=check_ports,
    )

    return PjsipReadiness(
        runtime_config=runtime_config,
        speaker=speaker,
        audio_file=audio_file,
        slot=slot,
        plan=plan,
    )


def _get_speaker(code: str) -> SpeakerDevice:
    try:
        return SpeakerDevice.objects.get(speaker_code=code)
    except SpeakerDevice.DoesNotExist as exc:
        raise PjsipPreflightError(
            f"SpeakerDevice not found: {code}."
        ) from exc


def _validate_speaker(speaker: SpeakerDevice) -> None:
    if not speaker.is_active:
        raise PjsipPreflightError(
            f"SpeakerDevice is inactive: {speaker.speaker_code}."
        )
    if speaker.deployment_state != SpeakerDevice.DEPLOYMENT_DEPLOYED:
        raise PjsipPreflightError(
            "SpeakerDevice must be in deployed state: "
            f"{speaker.speaker_code} is {speaker.deployment_state}."
        )
    if speaker.status != SpeakerDevice.STATUS_ONLINE:
        raise PjsipPreflightError(
            "SpeakerDevice must be online: "
            f"{speaker.speaker_code} is {speaker.status}."
        )


def _get_audio(code: str) -> AudioFile:
    try:
        return AudioFile.objects.get(audio_code=code)
    except AudioFile.DoesNotExist as exc:
        raise PjsipPreflightError(f"AudioFile not found: {code}.") from exc


def _validate_audio(audio_file: AudioFile) -> None:
    if not audio_file.is_active:
        raise PjsipPreflightError(
            f"AudioFile is inactive: {audio_file.audio_code}."
        )
    if not audio_file.file:
        raise PjsipPreflightError(
            f"AudioFile has no file: {audio_file.audio_code}."
        )
