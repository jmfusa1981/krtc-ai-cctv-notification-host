from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.notifications.backends.pjsip import (
    PjsipPreflightError,
    build_pjsip_playback_plan,
    execute_pjsip_playback_plan,
)
from apps.notifications.models import AudioFile, SpeakerDevice


class Command(BaseCommand):
    help = "Run one explicitly confirmed PJSIP Speaker playback test."

    def add_arguments(self, parser):
        parser.add_argument("--speaker", required=True, help="Speaker code")
        parser.add_argument("--audio", required=True, help="Audio code")
        parser.add_argument("--execute", action="store_true")
        parser.add_argument(
            "--confirm-speaker",
            help="Must exactly match --speaker before a real call is allowed.",
        )

    def handle(self, *args, **options):
        speaker_code = options["speaker"]
        if not options["execute"]:
            raise CommandError("Real playback blocked: --execute is required.")
        if options["confirm_speaker"] != speaker_code:
            raise CommandError(
                "Real playback blocked: --confirm-speaker must exactly match --speaker."
            )

        speaker = self._get_speaker(speaker_code)
        audio_file = self._get_audio(options["audio"])
        slot = self._speaker_slot(speaker)
        port_step = int(settings.PJSIP_PORT_STEP)
        local_sip_port = int(settings.PJSIP_LOCAL_SIP_PORT_BASE) + slot * port_step
        local_rtp_port = int(settings.PJSIP_LOCAL_RTP_PORT_BASE) + slot * port_step
        log_path = Path(settings.PJSIP_LOG_DIR) / f"play_test_{speaker.speaker_code}.log"

        try:
            audio_path = audio_file.file.path
        except (ValueError, NotImplementedError) as exc:
            raise CommandError(f"Audio file has no local path: {exc}") from exc

        try:
            plan = build_pjsip_playback_plan(
                executable_path=settings.PJSIP_EXECUTABLE_PATH,
                audio_path=audio_path,
                log_path=log_path,
                speaker_ip=speaker.ip_address,
                sip_uri=speaker.resolved_sip_uri,
                local_ip=settings.PJSIP_LOCAL_IP,
                advertise_ip=settings.PJSIP_ADVERTISE_IP,
                local_sip_port=local_sip_port,
                local_rtp_port=local_rtp_port,
                disabled_codecs=settings.PJSIP_DISABLED_CODECS,
                log_level=settings.PJSIP_LOG_LEVEL,
                app_log_level=settings.PJSIP_APP_LOG_LEVEL,
                check_ports=True,
            )
        except PjsipPreflightError as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(self.style.WARNING("REAL PJSIP PLAYBACK TEST"))
        self.stdout.write(f"Speaker: {speaker.speaker_code} - {speaker.name}")
        self.stdout.write(f"Target: {plan.target_uri}")
        self.stdout.write(f"Audio: {audio_file.audio_code} ({plan.audio_duration_seconds:.3f}s)")
        self.stdout.write(f"Log: {plan.log_path}")

        try:
            result = execute_pjsip_playback_plan(
                plan,
                extra_wait_seconds=settings.PJSIP_EXTRA_WAIT_SECONDS,
            )
        except PjsipPreflightError as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(f"Confirmed: {result.confirmed}")
        self.stdout.write(f"PCMU media active: {result.media_active}")
        self.stdout.write(f"Disconnected normally: {result.disconnected}")
        self.stdout.write(f"PJSUA return code: {result.return_code}")

        if not result.success:
            raise CommandError(f"Playback failed: {result.message} Log: {result.log_path}")

        self.stdout.write(self.style.SUCCESS(result.message))

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

