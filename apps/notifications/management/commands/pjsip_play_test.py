from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.notifications.backends.pjsip import (
    PjsipPreflightError,
    execute_pjsip_playback_plan,
)
from apps.notifications.pjsip_readiness import prepare_pjsip_readiness


class Command(BaseCommand):
    help = "執行一次具雙重確認的 PJSIP Speaker 真實播放測試。"

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
                "Real playback blocked: --confirm-speaker must exactly "
                "match --speaker."
            )

        log_path = (
            Path(settings.PJSIP_LOG_DIR)
            / f"play_test_{speaker_code}.log"
        )
        try:
            readiness = prepare_pjsip_readiness(
                speaker_code=speaker_code,
                audio_code=options["audio"],
                log_path=log_path,
                check_ports=True,
            )
        except PjsipPreflightError as exc:
            raise CommandError(str(exc)) from exc

        speaker = readiness.speaker
        audio_file = readiness.audio_file
        plan = readiness.plan

        self.stdout.write(self.style.WARNING("REAL PJSIP PLAYBACK TEST"))
        self.stdout.write(f"Speaker: {speaker.speaker_code} - {speaker.name}")
        self.stdout.write(f"Target: {plan.target_uri}")
        self.stdout.write(
            f"Audio: {audio_file.audio_code} "
            f"({plan.audio_duration_seconds:.3f}s)"
        )
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
            raise CommandError(
                f"Playback failed: {result.message} Log: {result.log_path}"
            )

        self.stdout.write(self.style.SUCCESS(result.message))
