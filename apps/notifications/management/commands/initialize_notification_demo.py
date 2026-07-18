from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.cameras.models import Camera
from apps.notifications.models import AudioFile, BroadcastRule, SpeakerDevice


SPEAKER_DEFINITIONS = (
    {
        "speaker_code": "SPK-001",
        "name": "月台區 A1 IP Speaker",
        "area": "月台區 A1",
        "ip_address": "192.168.6.120",
        "port": 5060,
        "protocol": "sip",
        "sip_uri": "sip:120@192.168.6.120:5060",
        "username": "",
        "password": "",
        "status": "online",
        "is_active": True,
    },
    {
        "speaker_code": "SPK-002",
        "name": "月台區 A2 IP Speaker",
        "area": "月台區 A2",
        "ip_address": "192.168.6.121",
        "port": 5060,
        "protocol": "sip",
        "sip_uri": "sip:121@192.168.6.121:5060",
        "username": "",
        "password": "",
        "status": "online",
        "is_active": True,
    },
)

AUDIO_CODES = ("AUD-TEST-001",)

RULE_DEFINITIONS = (
    {
        "rule_code": "RULE-FALL-001",
        "name": "CAM-001 跌倒事件自動廣播",
        "event_type": "fall_down",
        "camera_code": "CAM-001",
        "speaker_code": "SPK-001",
        "audio_code": "AUD-TEST-001",
        "priority": 10,
        "auto_broadcast": True,
        "is_active": True,
        "description": "CAM-001 Demo 跌倒事件自動廣播規則",
    },
    {
        "rule_code": "RULE-FALL-002",
        "name": "CAM-002 跌倒事件自動廣播",
        "event_type": "fall_down",
        "camera_code": "CAM-002",
        "speaker_code": "SPK-002",
        "audio_code": "AUD-TEST-001",
        "priority": 10,
        "auto_broadcast": True,
        "is_active": True,
        "description": "CAM-002 Demo 跌倒事件自動廣播規則",
    },
)


class Command(BaseCommand):
    help = (
        "Validate or initialize KRTC Demo speakers and broadcast rules. "
        "The command is dry-run unless --apply is supplied."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Create or update records. Without this flag no data is changed.",
        )

    def handle(self, *args, **options):
        apply_changes = options["apply"]
        self.stdout.write(
            self.style.WARNING(
                "APPLY MODE - database records may be updated."
                if apply_changes
                else "DRY RUN - no database records will be changed."
            )
        )

        cameras = self._load_cameras()
        audio_files = self._load_audio_files()

        if apply_changes:
            with transaction.atomic():
                speakers = self._apply_speakers()
                self._apply_rules(cameras, speakers, audio_files)
        else:
            speakers = self._inspect_speakers()
            self._inspect_rules(cameras, speakers, audio_files)

        self.stdout.write(
            self.style.SUCCESS(
                "Initialization completed successfully."
                if apply_changes
                else "Dry-run validation completed successfully."
            )
        )
        self.stdout.write("No Speaker playback was executed.")

    def _load_cameras(self):
        cameras = {}
        for code in {item["camera_code"] for item in RULE_DEFINITIONS}:
            try:
                camera = Camera.objects.get(camera_code=code)
            except Camera.DoesNotExist as exc:
                raise CommandError(f"Required Camera not found: {code}") from exc
            if not camera.is_active:
                raise CommandError(f"Required Camera is inactive: {code}")
            cameras[code] = camera
            self.stdout.write(f"[OK] Camera {code}: {camera.name}")
        return cameras

    def _load_audio_files(self):
        audio_files = {}
        for code in AUDIO_CODES:
            try:
                audio_file = AudioFile.objects.get(audio_code=code)
            except AudioFile.DoesNotExist as exc:
                raise CommandError(f"Required AudioFile not found: {code}") from exc

            if not audio_file.is_active:
                raise CommandError(f"Required AudioFile is inactive: {code}")
            try:
                path = Path(audio_file.file.path)
            except (ValueError, NotImplementedError) as exc:
                raise CommandError(
                    f"AudioFile has no usable local path: {code}: {exc}"
                ) from exc
            if not path.is_file():
                raise CommandError(f"Audio file does not exist: {code}: {path}")

            audio_files[code] = audio_file
            self.stdout.write(f"[OK] Audio {code}: {path}")
        return audio_files

    def _inspect_speakers(self):
        speakers = {}
        for definition in SPEAKER_DEFINITIONS:
            code = definition["speaker_code"]
            speaker = SpeakerDevice.objects.filter(speaker_code=code).first()
            if speaker is None:
                self.stdout.write(self.style.WARNING(f"[CREATE] Speaker {code}"))
                speakers[code] = None
                continue

            changed_fields = self._changed_fields(speaker, definition, {"speaker_code"})
            if changed_fields:
                self.stdout.write(
                    self.style.WARNING(
                        f"[UPDATE] Speaker {code}: {', '.join(changed_fields)}"
                    )
                )
            else:
                self.stdout.write(f"[UNCHANGED] Speaker {code}")
            speakers[code] = speaker
        return speakers

    def _apply_speakers(self):
        speakers = {}
        for definition in SPEAKER_DEFINITIONS:
            values = dict(definition)
            code = values.pop("speaker_code")
            speaker, created = SpeakerDevice.objects.update_or_create(
                speaker_code=code,
                defaults=values,
            )
            speakers[code] = speaker
            action = "CREATED" if created else "UPDATED"
            self.stdout.write(self.style.SUCCESS(f"[{action}] Speaker {code}"))
        return speakers

    def _inspect_rules(self, cameras, speakers, audio_files):
        for definition in RULE_DEFINITIONS:
            code = definition["rule_code"]
            rule = BroadcastRule.objects.filter(rule_code=code).first()
            if rule is None:
                self.stdout.write(self.style.WARNING(f"[CREATE] Rule {code}"))
                continue

            expected = self._rule_defaults(
                definition,
                cameras,
                speakers,
                audio_files,
                allow_unsaved=True,
            )
            changed_fields = []
            for field, expected_value in expected.items():
                if expected_value is None and field in {"speaker", "audio_file"}:
                    changed_fields.append(field)
                elif getattr(rule, field) != expected_value:
                    changed_fields.append(field)

            if changed_fields:
                self.stdout.write(
                    self.style.WARNING(
                        f"[UPDATE] Rule {code}: {', '.join(changed_fields)}"
                    )
                )
            else:
                self.stdout.write(f"[UNCHANGED] Rule {code}")

    def _apply_rules(self, cameras, speakers, audio_files):
        for definition in RULE_DEFINITIONS:
            code = definition["rule_code"]
            defaults = self._rule_defaults(
                definition,
                cameras,
                speakers,
                audio_files,
            )
            _, created = BroadcastRule.objects.update_or_create(
                rule_code=code,
                defaults=defaults,
            )
            action = "CREATED" if created else "UPDATED"
            self.stdout.write(self.style.SUCCESS(f"[{action}] Rule {code}"))

    @staticmethod
    def _rule_defaults(
        definition,
        cameras,
        speakers,
        audio_files,
        allow_unsaved=False,
    ):
        speaker = speakers.get(definition["speaker_code"])
        if speaker is None and not allow_unsaved:
            raise CommandError(
                f"Speaker unavailable for Rule {definition['rule_code']}: "
                f"{definition['speaker_code']}"
            )
        return {
            "name": definition["name"],
            "event_type": definition["event_type"],
            "camera": cameras[definition["camera_code"]],
            "speaker": speaker,
            "audio_file": audio_files[definition["audio_code"]],
            "priority": definition["priority"],
            "auto_broadcast": definition["auto_broadcast"],
            "is_active": definition["is_active"],
            "description": definition["description"],
        }

    @staticmethod
    def _changed_fields(instance, definition, excluded_fields):
        return [
            field
            for field, expected in definition.items()
            if field not in excluded_fields and getattr(instance, field) != expected
        ]