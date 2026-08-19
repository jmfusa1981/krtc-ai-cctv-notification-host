from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from apps.notifications.models import AudioFile, BroadcastLog, SpeakerDevice
from apps.notifications.services import (
    play_audio_to_speaker,
    process_single_broadcast_log,
)


@override_settings(BROADCAST_PLAYBACK_MODE="pjsip")
class SpeakerPlaybackGuardTests(TestCase):
    def setUp(self):
        self.speaker = SpeakerDevice.objects.create(
            speaker_code="SPK-GUARD",
            name="Guard test speaker",
            ip_address="192.0.2.10",
            status=SpeakerDevice.STATUS_ONLINE,
            is_active=True,
        )
        self.audio = AudioFile.objects.create(
            audio_code="AUD-GUARD",
            name="Guard test audio",
            audio_type=AudioFile.AUDIO_TYPE_TEST,
            file=SimpleUploadedFile("guard.wav", b"test-audio"),
            is_active=True,
        )

    def _pending_log(self):
        return BroadcastLog.objects.create(
            speaker=self.speaker,
            audio_file=self.audio,
            status=BroadcastLog.STATUS_PENDING,
        )

    def _speaker(self, code):
        return SpeakerDevice.objects.create(
            speaker_code=code,
            name=f"{code} test speaker",
            ip_address="192.0.2.11",
            status=SpeakerDevice.STATUS_ONLINE,
            is_active=True,
        )

    @patch("apps.notifications.services.play_audio_to_speaker")
    def test_offline_speaker_fails_before_backend_invocation(self, playback):
        self.speaker.status = SpeakerDevice.STATUS_OFFLINE
        self.speaker.save(update_fields=["status"])

        result = process_single_broadcast_log(self._pending_log())

        playback.assert_not_called()
        self.assertEqual(result["status"], BroadcastLog.STATUS_FAILED)
        log = BroadcastLog.objects.latest("id")
        self.assertEqual(log.status, BroadcastLog.STATUS_FAILED)
        self.assertEqual(
            log.response_payload["reason"],
            "speaker_offline",
        )

    @patch("apps.notifications.services.play_audio_to_speaker")
    def test_inactive_speaker_fails_before_backend_invocation(self, playback):
        self.speaker.is_active = False
        self.speaker.save(update_fields=["is_active"])

        result = process_single_broadcast_log(self._pending_log())

        playback.assert_not_called()
        self.assertEqual(result["status"], BroadcastLog.STATUS_FAILED)
        log = BroadcastLog.objects.latest("id")
        self.assertEqual(
            log.response_payload["reason"],
            "speaker_inactive",
        )

    @patch("apps.notifications.services.play_audio_via_pjsip")
    def test_execution_boundary_rechecks_latest_speaker_status(self, pjsip):
        self.speaker.status = SpeakerDevice.STATUS_OFFLINE
        self.speaker.save(update_fields=["status"])
        stale_speaker = SpeakerDevice(
            pk=self.speaker.pk,
            speaker_code=self.speaker.speaker_code,
            name=self.speaker.name,
            ip_address=self.speaker.ip_address,
            status=SpeakerDevice.STATUS_ONLINE,
            is_active=True,
        )
        log = self._pending_log()

        result = play_audio_to_speaker(stale_speaker, self.audio, log)

        pjsip.assert_not_called()
        self.assertFalse(result["success"])
        self.assertEqual(result["reason"], "speaker_offline")

    @patch("apps.notifications.services.play_audio_to_speaker")
    def test_auto_playback_completion_clears_older_formal_inference_locks(self, playback):
        stale_speaker = self._speaker("SPK-STALE")
        stale_log = BroadcastLog.objects.create(
            speaker=stale_speaker,
            audio_file=self.audio,
            status=BroadcastLog.STATUS_PENDING,
            request_payload={"source": "formal_inference_host"},
        )
        live_log = BroadcastLog.objects.create(
            speaker=self._speaker("SPK-LIVE"),
            audio_file=self.audio,
            status=BroadcastLog.STATUS_PENDING,
            request_payload={"source": "live_microphone"},
        )
        current_log = self._pending_log()
        current_log.request_payload = {"source": "formal_inference_host"}
        current_log.save(update_fields=["request_payload"])
        playback.return_value = {
            "success": True,
            "message": "Playback completed successfully.",
        }

        result = process_single_broadcast_log(current_log)

        self.assertEqual(result["status"], BroadcastLog.STATUS_SUCCESS)
        self.assertEqual(result["auto_recovered_workflows"][0]["broadcast_log_id"], stale_log.id)
        stale_log.refresh_from_db()
        live_log.refresh_from_db()
        self.assertEqual(stale_log.status, BroadcastLog.STATUS_FAILED)
        self.assertEqual(live_log.status, BroadcastLog.STATUS_PENDING)
