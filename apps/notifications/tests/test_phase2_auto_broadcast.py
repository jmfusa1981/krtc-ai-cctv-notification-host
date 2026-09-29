import shutil
import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase, override_settings

from apps.ai_bridge.models import AIModel
from apps.cameras.models import Camera
from apps.notifications.models import AudioFile, BroadcastRule, SpeakerDevice


class Phase2AutoBroadcastCommandTests(TestCase):
    def setUp(self):
        self.media_root = tempfile.mkdtemp(prefix="krtc_phase2_test_")
        self.override = override_settings(MEDIA_ROOT=self.media_root)
        self.override.enable()

        Camera.objects.create(
            camera_code="CAM-003",
            name="CAM-003",
            area="下行電扶梯區",
            rtsp_url="rtsp://127.0.0.1/cam003",
            is_active=True,
        )
        Camera.objects.create(
            camera_code="CAM-02",
            name="CAM-002",
            area="月台區",
            rtsp_url="rtsp://127.0.0.1/cam02",
            is_active=True,
        )
        SpeakerDevice.objects.create(
            speaker_code="SPK-003",
            name="Phase 2 Speaker",
            area="月台區",
            ip_address="192.0.2.3",
            status=SpeakerDevice.STATUS_OFFLINE,
            is_active=True,
        )
        AudioFile.objects.create(
            audio_code="AUD-LUGWHL",
            name="大型行李箱與輪椅",
            audio_type=AudioFile.AUDIO_TYPE_TEST,
            file=SimpleUploadedFile("phase2.wav", b"test-audio"),
            is_active=True,
        )

    def tearDown(self):
        self.override.disable()
        shutil.rmtree(self.media_root, ignore_errors=True)

    def test_dry_run_does_not_write(self):
        call_command("configure_phase2_auto_broadcast")
        self.assertEqual(BroadcastRule.objects.count(), 0)
        self.assertEqual(AIModel.objects.count(), 0)

    def test_apply_is_idempotent_and_uses_approved_mapping(self):
        call_command("configure_phase2_auto_broadcast", apply=True)
        call_command("configure_phase2_auto_broadcast", apply=True)
        call_command("configure_phase2_auto_broadcast", verify=True)

        self.assertEqual(BroadcastRule.objects.count(), 2)
        self.assertEqual(AIModel.objects.count(), 5)

        wheelchair = BroadcastRule.objects.get(
            rule_code="RULE-WHEELCHAIR-CAM02-SPK003"
        )
        self.assertEqual(wheelchair.event_type, "wheelchair_detected")
        self.assertEqual(wheelchair.camera.camera_code, "CAM-02")
        self.assertEqual(wheelchair.speaker.speaker_code, "SPK-003")
        self.assertEqual(wheelchair.audio_file.audio_code, "AUD-LUGWHL")

        luggage = BroadcastRule.objects.get(
            rule_code="RULE-LARGE-LUGGAGE-CAM003-SPK003"
        )
        self.assertEqual(luggage.event_type, "large_luggage_intrusion")
        self.assertEqual(luggage.camera.camera_code, "CAM-003")
        self.assertFalse(
            BroadcastRule.objects.filter(event_type="luggage_roll").exists()
        )
