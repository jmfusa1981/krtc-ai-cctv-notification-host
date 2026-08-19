from django.core.management.base import BaseCommand, CommandError

from apps.cameras.models import Camera
from apps.notifications.models import AudioFile, BroadcastRule, SpeakerDevice


class Command(BaseCommand):
    help = (
        "Validate or create one explicit AI event auto-broadcast rule. "
        "Dry-run is the default; pass --apply to write the rule."
    )

    def add_arguments(self, parser):
        parser.add_argument("--rule-code", required=True)
        parser.add_argument("--name", required=True)
        parser.add_argument(
            "--event-type",
            required=True,
            choices=[value for value, _label in BroadcastRule.EVENT_TYPE_CHOICES],
        )
        parser.add_argument(
            "--camera",
            help="Camera code. Omit only for a station-wide event-type rule.",
        )
        parser.add_argument(
            "--speaker",
            action="append",
            required=True,
            help="Speaker code. Repeat this option to target multiple speakers.",
        )
        parser.add_argument("--audio", required=True, help="Audio code.")
        parser.add_argument("--priority", type=int, default=100)
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Create or update the rule. Without this flag, no data is changed.",
        )

    def handle(self, *args, **options):
        camera = None
        camera_code = options.get("camera")
        if camera_code:
            camera = Camera.objects.filter(camera_code=camera_code).first()
            if camera is None:
                raise CommandError(f"Camera not found: {camera_code}")

        speaker_codes = list(dict.fromkeys(options["speaker"]))
        speakers = list(
            SpeakerDevice.objects.filter(
                speaker_code__in=speaker_codes,
                is_active=True,
            ).order_by("speaker_code")
        )
        found_codes = {speaker.speaker_code for speaker in speakers}
        missing_codes = [code for code in speaker_codes if code not in found_codes]
        if missing_codes:
            raise CommandError(f"Active Speaker not found: {', '.join(missing_codes)}")

        audio_code = options["audio"]
        audio_file = AudioFile.objects.filter(
            audio_code=audio_code,
            is_active=True,
        ).first()
        if audio_file is None:
            raise CommandError(f"Active AudioFile not found: {audio_code}")
        if not audio_file.file:
            raise CommandError(f"AudioFile has no file: {audio_code}")
        try:
            if not audio_file.file.storage.exists(audio_file.file.name):
                raise CommandError(f"Audio file is missing on disk: {audio_file.file.name}")
        except NotImplementedError:
            pass

        if options["priority"] < 0:
            raise CommandError("priority must be zero or greater.")

        values = {
            "name": options["name"],
            "event_type": options["event_type"],
            "camera": camera,
            "speaker": speakers[0],
            "audio_file": audio_file,
            "priority": options["priority"],
            "auto_broadcast": True,
            "is_active": True,
            "description": "Configured for formal AI event auto-broadcast testing.",
        }

        summary = (
            f"rule={options['rule_code']} event={options['event_type']} "
            f"camera={camera_code or 'ALL'} speakers={','.join(speaker_codes)} "
            f"audio={audio_code} priority={options['priority']}"
        )

        if not options["apply"]:
            self.stdout.write(self.style.WARNING(f"DRY RUN: {summary}"))
            self.stdout.write("No database changes were made. Add --apply to save.")
            return

        rule, created = BroadcastRule.objects.update_or_create(
            rule_code=options["rule_code"],
            defaults=values,
        )
        rule.speakers.set(speakers)
        action = "created" if created else "updated"
        self.stdout.write(self.style.SUCCESS(f"Rule {action}: {summary}"))
        self.stdout.write(f"database_id={rule.pk}")
