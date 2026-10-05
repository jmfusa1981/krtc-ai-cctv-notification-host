from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.notifications.backends.pjsip import PjsipPreflightError
from apps.notifications.models import AudioFile, SpeakerDevice
from apps.notifications.pjsip_readiness import prepare_pjsip_readiness
from apps.notifications.runtime_config import get_broadcast_runtime_config


class Command(BaseCommand):
    help = "執行 PJSIP 播放前置檢查；只做 dry run，不會呼叫 Speaker。"

    def add_arguments(self, parser):
        parser.add_argument("--speaker", required=True, help="Speaker code")
        parser.add_argument("--audio", required=True, help="Audio code")
        parser.add_argument(
            "--slot",
            type=int,
            help="Zero-based local port slot; defaults to Speaker order.",
        )

    def handle(self, *args, **options):
        runtime_config = get_broadcast_runtime_config()
        self.stdout.write("PJSIP DRY RUN - no Speaker will be called")
        self.stdout.write(f"Environment: {runtime_config.environment}")
        self.stdout.write(f"Config Source: {runtime_config.source}")
        self.stdout.write(
            f"Operational Backend: {runtime_config.operational_backend}"
        )
        self.stdout.write(
            f"PJSUA Path: {runtime_config.pjsip_executable_path or '(empty)'}"
        )
        self.stdout.write(
            f"Executable Exists: {runtime_config.executable_exists}"
        )
        self.stdout.write(
            f"Local IP: {runtime_config.pjsip_local_ip or '(empty)'}"
        )
        self.stdout.write(
            "Advertise IP: "
            f"{runtime_config.pjsip_advertise_ip or '(empty)'}"
        )
        self.stdout.write(
            f"Configured SIP Port Base: "
            f"{runtime_config.pjsip_local_sip_port_base}"
        )
        self.stdout.write(
            f"Configured RTP Port Base: "
            f"{runtime_config.pjsip_local_rtp_port_base}"
        )
        self.stdout.write(
            f"Gain: {runtime_config.pjsip_audio_gain_percent:.1f}%"
        )

        speaker = SpeakerDevice.objects.filter(
            speaker_code=options["speaker"]
        ).first()
        self.stdout.write(f"Speaker Code: {options['speaker']}")
        self.stdout.write(
            f"Speaker IP: {speaker.ip_address if speaker else '(not found)'}"
        )
        self.stdout.write(
            "Resolved SIP URI: "
            f"{speaker.resolved_sip_uri if speaker else '(not found)'}"
        )
        self.stdout.write(
            f"Speaker Status: {speaker.status if speaker else '(not found)'}"
        )
        self.stdout.write(
            f"Speaker Active: {speaker.is_active if speaker else '(not found)'}"
        )
        self.stdout.write(
            "Speaker Deployment State: "
            f"{speaker.deployment_state if speaker else '(not found)'}"
        )

        audio_file = AudioFile.objects.filter(
            audio_code=options["audio"]
        ).first()
        self.stdout.write(f"Audio Code: {options['audio']}")
        self.stdout.write(
            f"Audio Path: {self._audio_path_or_status(audio_file)}"
        )
        self.stdout.write(
            "Duration: "
            f"{audio_file.duration_seconds if audio_file else '(not found)'}"
        )

        log_path = (
            Path(settings.PJSIP_LOG_DIR)
            / f"preflight_{options['speaker']}.log"
        )

        try:
            readiness = prepare_pjsip_readiness(
                speaker_code=options["speaker"],
                audio_code=options["audio"],
                log_path=log_path,
                slot=options["slot"],
                check_ports=True,
                runtime_config=runtime_config,
            )
        except PjsipPreflightError as exc:
            self.stdout.write(self.style.ERROR(f"Fail Reason: {exc}"))
            self.stdout.write(self.style.ERROR("Overall: PREFLIGHT FAIL"))
            raise CommandError(str(exc)) from exc

        plan = readiness.plan

        self.stdout.write(
            f"Validated Duration: {plan.audio_duration_seconds:.3f} seconds"
        )
        self.stdout.write(f"Local SIP Port: {plan.local_sip_port}")
        self.stdout.write(f"Local RTP Port: {plan.local_rtp_port}")
        self.stdout.write("Generated Command:")
        self.stdout.write(plan.command_text())
        self.stdout.write(self.style.SUCCESS("Overall: PREFLIGHT PASS"))

    @staticmethod
    def _audio_path_or_status(audio_file):
        if audio_file is None:
            return "(not found)"
        if not audio_file.file:
            return "(empty)"
        try:
            return audio_file.file.path
        except (ValueError, NotImplementedError):
            return "(unavailable)"
