from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.notifications.backends.pjsip import (
    PjsipPreflightError,
    build_pjsip_playback_plan,
)
from apps.notifications.models import AudioFile, SpeakerDevice
from apps.notifications.runtime_config import get_broadcast_runtime_config


class Command(BaseCommand):
    help = "Validate PJSIP playback inputs and print a dry-run command."

    def add_arguments(self, parser):
        parser.add_argument("--speaker", required=True, help="Speaker code")
        parser.add_argument("--audio", required=True, help="Audio code")
        parser.add_argument(
            "--slot",
            type=int,
            help="Zero-based local port slot; defaults to Speaker order.",
        )
        parser.add_argument(
            "--skip-port-check",
            action="store_true",
            help="Build the plan without binding the local UDP ports.",
        )

    def handle(self, *args, **options):
        speaker = self._get_speaker(options["speaker"])
        audio_file = self._get_audio(options["audio"])
        slot = options["slot"]
        if slot is None:
            slot = self._speaker_slot(speaker)
        if slot < 0:
            raise CommandError("--slot must be zero or greater.")

        runtime_config = get_broadcast_runtime_config()

        port_step = runtime_config.pjsip_port_step
        local_sip_port = (
            runtime_config.pjsip_local_sip_port_base
            + slot * port_step
        )
        local_rtp_port = (
            runtime_config.pjsip_local_rtp_port_base
            + slot * port_step
        )
        log_path = Path(settings.PJSIP_LOG_DIR) / f"preflight_{speaker.speaker_code}.log"

        try:
            audio_path = audio_file.file.path
        except (ValueError, NotImplementedError) as exc:
            raise CommandError(f"Audio file has no local path: {exc}") from exc

        try:
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
                log_level=settings.PJSIP_LOG_LEVEL,
                app_log_level=settings.PJSIP_APP_LOG_LEVEL,
                audio_gain_percent=runtime_config.pjsip_audio_gain_percent,
                check_ports=not options["skip_port_check"],
            )
        except PjsipPreflightError as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(self.style.WARNING("PJSIP DRY RUN - no Speaker was called"))
        self.stdout.write(f"Speaker: {speaker.speaker_code} - {speaker.name}")
        self.stdout.write(f"Target: {plan.target_uri}")
        self.stdout.write(f"Audio: {audio_file.audio_code} - {plan.audio_path}")
        self.stdout.write(f"Audio duration: {plan.audio_duration_seconds:.3f} seconds")
        self.stdout.write(f"Audio gain: {plan.audio_gain_percent:.1f}%")
        self.stdout.write(f"Local IP: {plan.local_ip}")
        self.stdout.write(f"Advertise IP: {plan.advertise_ip}")
        self.stdout.write(f"Local SIP port: {plan.local_sip_port}")
        self.stdout.write(f"Local RTP port: {plan.local_rtp_port}")
        self.stdout.write("Generated command:")
        self.stdout.write(plan.command_text())
        self.stdout.write(self.style.SUCCESS("Preflight passed. Command was not executed."))

    @staticmethod
    def _get_speaker(code):
        try:
            return SpeakerDevice.objects.get(speaker_code=code, is_active=True)
        except SpeakerDevice.DoesNotExist as exc:
            raise CommandError(f"Active SpeakerDevice not found: {code}") from exc

    @staticmethod
    def _get_audio(code):
        try:
            return AudioFile.objects.get(audio_code=code, is_active=True)
        except AudioFile.DoesNotExist as exc:
            raise CommandError(f"Active AudioFile not found: {code}") from exc

    @staticmethod
    def _speaker_slot(speaker):
        return SpeakerDevice.objects.filter(
            is_active=True,
            speaker_code__lt=speaker.speaker_code,
        ).count()

