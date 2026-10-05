from django.test import TestCase

from apps.cameras.models import Camera
from apps.events.views import find_broadcast_rules
from apps.notifications.models import AudioFile, BroadcastRule, SpeakerDevice


class FindBroadcastRulesTests(TestCase):
    def setUp(self):
        self.camera = Camera.objects.create(
            camera_code="CAM-LAB-001",
            name="Lab Camera 1",
            area="Lab",
        )
        self.other_camera = Camera.objects.create(
            camera_code="CAM-LAB-002",
            name="Lab Camera 2",
            area="Lab",
        )
        self.audio_file = AudioFile.objects.create(
            audio_code="TEST-RULE-MATCH",
            name="Rule matching test audio",
            audio_type=AudioFile.AUDIO_TYPE_TEST,
            file="audio_files/test_rule_match.wav",
        )
        self.active_speaker = SpeakerDevice.objects.create(
            speaker_code="SPK-TEST-ACTIVE",
            name="Active test speaker",
            ip_address="192.0.2.10",
            is_active=True,
        )
        self.inactive_speaker = SpeakerDevice.objects.create(
            speaker_code="SPK-TEST-INACTIVE",
            name="Inactive test speaker",
            ip_address="192.0.2.11",
            is_active=False,
        )

    def create_rule(
        self,
        rule_code,
        *,
        camera=None,
        is_active=True,
        auto_broadcast=True,
        speaker=None,
    ):
        rule = BroadcastRule.objects.create(
            rule_code=rule_code,
            name=rule_code,
            event_type=BroadcastRule.EVENT_ESCALATOR_FALL,
            camera=camera,
            audio_file=self.audio_file,
            is_active=is_active,
            auto_broadcast=auto_broadcast,
        )
        rule.speakers.add(speaker or self.active_speaker)
        return rule

    def matching_rule_codes(self):
        return list(
            find_broadcast_rules(
                BroadcastRule.EVENT_ESCALATOR_FALL,
                self.camera,
            ).values_list("rule_code", flat=True)
        )

    def test_camera_specific_rule_matches_same_camera(self):
        self.create_rule("RULE-SPECIFIC", camera=self.camera)

        self.assertEqual(self.matching_rule_codes(), ["RULE-SPECIFIC"])

    def test_generic_rule_matches_any_camera(self):
        self.create_rule("RULE-GENERIC", camera=None)

        self.assertEqual(self.matching_rule_codes(), ["RULE-GENERIC"])

    def test_rule_for_different_camera_does_not_match(self):
        self.create_rule("RULE-OTHER-CAMERA", camera=self.other_camera)

        self.assertEqual(self.matching_rule_codes(), [])

    def test_inactive_rule_does_not_match(self):
        self.create_rule("RULE-INACTIVE", is_active=False)

        self.assertEqual(self.matching_rule_codes(), [])

    def test_manual_rule_does_not_match(self):
        self.create_rule("RULE-MANUAL", auto_broadcast=False)

        self.assertEqual(self.matching_rule_codes(), [])

    def test_rule_without_active_speaker_does_not_match(self):
        self.create_rule(
            "RULE-INACTIVE-SPEAKER",
            speaker=self.inactive_speaker,
        )

        self.assertEqual(self.matching_rule_codes(), [])

    def test_legacy_rule_matches_canonical_event_type(self):
        rule = self.create_rule("RULE-LEGACY")
        rule.event_type = "escalator_fall"
        rule.save(update_fields=["event_type"])

        self.assertEqual(self.matching_rule_codes(), ["RULE-LEGACY"])
        self.assertEqual(rule.get_event_type_display(), "人員跌倒（歷史值）")
