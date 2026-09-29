from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.ai_bridge.models import AIModel
from apps.cameras.models import Camera
from apps.notifications.models import AudioFile, BroadcastRule, SpeakerDevice


AI_MODEL_DEFINITIONS = (
    ("LUGGAGE_ROLL_V001", "Luggage Roll Detection", "luggage_roll"),
    (
        "LARGE_LUGGAGE_INTRUSION_V001",
        "Large Luggage Intrusion Detection",
        "large_luggage_intrusion",
    ),
    ("WHEELCHAIR_DETECTED_V001", "Wheelchair Detection", "wheelchair_detected"),
    (
        "PASSENGER_LOITERING_V001",
        "Passenger Loitering Detection",
        "passenger_loitering",
    ),
    (
        "CROWD_COUNT_ABNORMAL_V001",
        "Crowd Count Abnormal Detection",
        "crowd_count_abnormal",
    ),
)

RULE_DEFINITIONS = (
    {
        "rule_code": "RULE-LARGE-LUGGAGE-CAM003-SPK003",
        "name": "CAM-003 大型行李進入區域自動廣播",
        "event_type": "large_luggage_intrusion",
        "camera_code": "CAM-003",
        "speaker_code": "SPK-003",
        "audio_code": "AUD-LUGWHL",
        "priority": 100,
    },
    {
        "rule_code": "RULE-WHEELCHAIR-CAM02-SPK003",
        "name": "CAM-02 輪椅偵測自動廣播",
        "event_type": "wheelchair_detected",
        "camera_code": "CAM-02",
        "speaker_code": "SPK-003",
        "audio_code": "AUD-LUGWHL",
        "priority": 100,
    },
)


class Command(BaseCommand):
    help = (
        "Validate, apply, or verify the approved Phase 2 auto-broadcast "
        "mapping. Dry-run is the default."
    )

    def add_arguments(self, parser):
        mode = parser.add_mutually_exclusive_group()
        mode.add_argument(
            "--apply",
            action="store_true",
            help="Create or update the approved AI model entries and rules.",
        )
        mode.add_argument(
            "--verify",
            action="store_true",
            help="Verify that the approved Phase 2 configuration is present.",
        )

    def handle(self, *args, **options):
        resolved_rules = self._resolve_dependencies()

        if options["verify"]:
            self._verify(resolved_rules)
            return

        self._print_plan(resolved_rules)
        if not options["apply"]:
            self.stdout.write(
                self.style.WARNING("DRY RUN: no database changes were made.")
            )
            return

        with transaction.atomic():
            for model_code, name, event_type in AI_MODEL_DEFINITIONS:
                AIModel.objects.update_or_create(
                    model_code=model_code,
                    defaults={
                        "name": name,
                        "version": "v1",
                        "event_type": event_type,
                        "is_active": True,
                        "description": (
                            "Phase 2 formal event-type registry entry. "
                            "Runtime endpoint remains managed by InferenceHost."
                        ),
                    },
                )

            for definition, camera, speaker, audio_file in resolved_rules:
                BroadcastRule.objects.update_or_create(
                    rule_code=definition["rule_code"],
                    defaults={
                        "name": definition["name"],
                        "event_type": definition["event_type"],
                        "camera": camera,
                        "speaker": speaker,
                        "audio_file": audio_file,
                        "priority": definition["priority"],
                        "auto_broadcast": True,
                        "is_active": True,
                        "description": (
                            "KRTC V4 Phase 2 approved mapping. "
                            "Configuration only; installation does not play audio."
                        ),
                    },
                )

        self._verify(resolved_rules)
        self.stdout.write(
            self.style.SUCCESS("Phase 2 auto-broadcast configuration applied.")
        )

    def _resolve_dependencies(self):
        resolved = []
        for definition in RULE_DEFINITIONS:
            camera = Camera.objects.filter(
                camera_code=definition["camera_code"],
                is_active=True,
            ).first()
            if camera is None:
                raise CommandError(
                    f"Active Camera not found: {definition['camera_code']}"
                )

            speaker = SpeakerDevice.objects.filter(
                speaker_code=definition["speaker_code"],
                is_active=True,
            ).first()
            if speaker is None:
                raise CommandError(
                    f"Active Speaker not found: {definition['speaker_code']}"
                )

            audio_file = AudioFile.objects.filter(
                audio_code=definition["audio_code"],
                is_active=True,
            ).first()
            if audio_file is None:
                raise CommandError(
                    f"Active AudioFile not found: {definition['audio_code']}"
                )
            if not audio_file.file:
                raise CommandError(
                    f"AudioFile has no file: {definition['audio_code']}"
                )
            try:
                if not audio_file.file.storage.exists(audio_file.file.name):
                    raise CommandError(
                        f"Audio file is missing on disk: {audio_file.file.name}"
                    )
            except NotImplementedError:
                pass

            resolved.append((definition, camera, speaker, audio_file))
        return resolved

    def _print_plan(self, resolved_rules):
        self.stdout.write("Approved Phase 2 mapping:")
        for definition, _camera, speaker, _audio_file in resolved_rules:
            self.stdout.write(
                "  "
                f"{definition['event_type']} -> {definition['camera_code']} "
                f"-> {definition['speaker_code']} -> {definition['audio_code']} "
                f"(speaker_status={speaker.status})"
            )
        self.stdout.write(
            "  luggage_roll: not configured (dedicated audio file is required)"
        )

    def _verify(self, resolved_rules):
        errors = []
        for definition, camera, speaker, audio_file in resolved_rules:
            rule = BroadcastRule.objects.filter(
                rule_code=definition["rule_code"]
            ).first()
            expected = {
                "event_type": definition["event_type"],
                "camera_id": camera.pk,
                "speaker_id": speaker.pk,
                "audio_file_id": audio_file.pk,
                "priority": definition["priority"],
                "auto_broadcast": True,
                "is_active": True,
            }
            if rule is None:
                errors.append(f"Missing rule: {definition['rule_code']}")
                continue
            for field, value in expected.items():
                if getattr(rule, field) != value:
                    errors.append(
                        f"{definition['rule_code']} has invalid {field}"
                    )

        for model_code, _name, event_type in AI_MODEL_DEFINITIONS:
            if not AIModel.objects.filter(
                model_code=model_code,
                event_type=event_type,
                is_active=True,
            ).exists():
                errors.append(f"Missing AI model registry entry: {model_code}")

        if BroadcastRule.objects.filter(
            event_type="luggage_roll",
            rule_code__in=[item["rule_code"] for item in RULE_DEFINITIONS],
        ).exists():
            errors.append("luggage_roll must not reuse a Phase 2 shared-audio rule")

        if errors:
            raise CommandError("; ".join(errors))
        self.stdout.write(
            self.style.SUCCESS(
                "Phase 2 verification passed: 2 rules and 5 AI model entries."
            )
        )
