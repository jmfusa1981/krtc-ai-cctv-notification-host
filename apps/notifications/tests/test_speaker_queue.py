import threading
import time
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

from django.test import TransactionTestCase, override_settings
from django.utils import timezone

from apps.notifications.models import AudioFile, BroadcastLog, BroadcastRule, SpeakerDevice
from apps.notifications.pjsip_readiness import prepare_pjsip_readiness
from apps.notifications.runtime_config import BroadcastRuntimeConfig
from apps.notifications.services import (
    build_broadcast_dedup_key,
    enqueue_broadcast_log,
    process_queued_broadcasts,
    process_single_broadcast_log,
    process_speaker_queue,
)


@override_settings(
    BROADCAST_PLAYBACK_MODE="simulation",
    BROADCAST_QUEUE_COOLDOWN_SECONDS=30,
    BROADCAST_QUEUE_TTL_SECONDS=120,
    BROADCAST_QUEUE_MAX_WORKERS=4,
)
class PerSpeakerBroadcastQueueTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        self.audio = AudioFile.objects.create(
            audio_code="AUD-QUEUE",
            name="Queue test audio",
            audio_type=AudioFile.AUDIO_TYPE_TEST,
            file="audio_files/queue-test.wav",
            is_active=True,
        )

    def create_speaker(self, code):
        return SpeakerDevice.objects.create(
            speaker_code=code,
            name=f"{code} test speaker",
            ip_address=f"192.0.2.{SpeakerDevice.objects.count() + 10}",
            status=SpeakerDevice.STATUS_ONLINE,
            deployment_state=SpeakerDevice.DEPLOYMENT_DEPLOYED,
            is_active=True,
        )

    def enqueue(self, speaker, *, priority=100, dedup_key=""):
        return enqueue_broadcast_log(
            speaker=speaker,
            audio_file=self.audio,
            queue_priority=priority,
            dedup_key=dedup_key,
            request_payload={
                "source": "queue_test",
                "speaker_code": speaker.speaker_code,
            },
        )

    @patch("apps.notifications.services.play_audio_to_speaker")
    def test_different_speakers_execute_concurrently(self, playback):
        speakers = [
            self.create_speaker("SPK-CONCURRENT-1"),
            self.create_speaker("SPK-CONCURRENT-2"),
        ]
        for speaker in speakers:
            self.enqueue(speaker)

        barrier = threading.Barrier(2, timeout=3)

        def play(**_kwargs):
            barrier.wait()
            return {"success": True, "message": "simulated success"}

        playback.side_effect = play
        summary = process_queued_broadcasts(
            speaker_ids=[speaker.pk for speaker in speakers],
            max_workers=2,
        )

        self.assertEqual(summary["success_count"], 2, summary)
        self.assertEqual(
            BroadcastLog.objects.filter(status=BroadcastLog.STATUS_SUCCESS).count(),
            2,
        )

    @patch("apps.notifications.services.play_audio_to_speaker")
    def test_busy_same_speaker_remains_queued(self, playback):
        speaker = self.create_speaker("SPK-SERIAL")
        playing_log = BroadcastLog.objects.create(
            speaker=speaker,
            audio_file=self.audio,
            status=BroadcastLog.STATUS_PLAYING,
        )
        queued_log, _created = self.enqueue(speaker)

        result = process_single_broadcast_log(queued_log)

        playback.assert_not_called()
        queued_log.refresh_from_db()
        self.assertEqual(result["status"], BroadcastLog.STATUS_QUEUED)
        self.assertEqual(queued_log.status, BroadcastLog.STATUS_QUEUED)

        playing_log.status = BroadcastLog.STATUS_SUCCESS
        playing_log.finished_at = timezone.now()
        playing_log.save(update_fields=["status", "finished_at", "updated_at"])
        playback.return_value = {
            "success": True,
            "message": "simulated success",
        }
        process_speaker_queue(speaker.pk)

        queued_log.refresh_from_db()
        self.assertEqual(queued_log.status, BroadcastLog.STATUS_SUCCESS)

    @patch("apps.notifications.services.play_audio_to_speaker")
    def test_lower_number_priority_executes_first(self, playback):
        speaker = self.create_speaker("SPK-PRIORITY")
        first_log, _created = self.enqueue(speaker, priority=50)
        priority_log, _created = self.enqueue(speaker, priority=10)
        playback_order = []

        def play(**kwargs):
            playback_order.append(kwargs["broadcast_log"].pk)
            return {"success": True, "message": "simulated success"}

        playback.side_effect = play
        process_speaker_queue(speaker.pk)

        self.assertEqual(playback_order, [priority_log.pk, first_log.pk])

    def test_equivalent_event_inside_cooldown_is_suppressed(self):
        speaker = self.create_speaker("SPK-DEDUP")
        dedup_key = build_broadcast_dedup_key(
            rule_id=7,
            speaker_id=speaker.pk,
            event_source="CAM-001",
            event_type="fall_detected",
        )

        first_log, first_queued = self.enqueue(speaker, dedup_key=dedup_key)
        second_log, second_queued = self.enqueue(speaker, dedup_key=dedup_key)

        self.assertTrue(first_queued)
        self.assertFalse(second_queued)
        self.assertEqual(first_log.status, BroadcastLog.STATUS_QUEUED)
        self.assertEqual(second_log.status, BroadcastLog.STATUS_SUPPRESSED)

    def test_same_event_for_different_speakers_is_not_suppressed(self):
        speakers = [
            self.create_speaker("SPK-DEDUP-A"),
            self.create_speaker("SPK-DEDUP-B"),
        ]
        queued = []
        for speaker in speakers:
            dedup_key = build_broadcast_dedup_key(
                rule_id=7,
                speaker_id=speaker.pk,
                event_source="CAM-001",
                event_type="fall_detected",
            )
            _log, was_queued = self.enqueue(speaker, dedup_key=dedup_key)
            queued.append(was_queued)

        self.assertEqual(queued, [True, True])

    @patch("apps.notifications.services.play_audio_to_speaker")
    def test_expired_job_does_not_call_playback(self, playback):
        speaker = self.create_speaker("SPK-TTL")
        log, _created = self.enqueue(speaker)
        BroadcastLog.objects.filter(pk=log.pk).update(
            expires_at=timezone.now() - timedelta(seconds=1)
        )

        process_speaker_queue(speaker.pk)

        playback.assert_not_called()
        log.refresh_from_db()
        self.assertEqual(log.status, BroadcastLog.STATUS_EXPIRED)

    @patch("apps.notifications.services.play_audio_to_speaker")
    def test_one_speaker_failure_does_not_block_another(self, playback):
        failed_speaker = self.create_speaker("SPK-FAIL")
        healthy_speaker = self.create_speaker("SPK-HEALTHY")
        failed_log, _created = self.enqueue(failed_speaker)
        healthy_log, _created = self.enqueue(healthy_speaker)

        def play(**kwargs):
            success = kwargs["speaker"].pk == healthy_speaker.pk
            return {"success": success, "message": "simulated result"}

        playback.side_effect = play
        process_queued_broadcasts(
            speaker_ids=[failed_speaker.pk, healthy_speaker.pk],
            max_workers=2,
        )

        failed_log.refresh_from_db()
        healthy_log.refresh_from_db()
        self.assertEqual(failed_log.status, BroadcastLog.STATUS_FAILED)
        self.assertEqual(healthy_log.status, BroadcastLog.STATUS_SUCCESS)

    def test_multi_speaker_rule_creates_independent_jobs(self):
        speakers = [
            self.create_speaker("SPK-MULTI-A"),
            self.create_speaker("SPK-MULTI-B"),
            self.create_speaker("SPK-MULTI-C"),
        ]
        rule = BroadcastRule.objects.create(
            rule_code="RULE-MULTI-QUEUE",
            name="Multi-speaker queue rule",
            event_type="fall_detected",
            audio_file=self.audio,
            priority=20,
            auto_broadcast=True,
            is_active=True,
        )
        rule.speakers.set(speakers)

        for speaker in rule.target_speakers_queryset(active_only=True):
            enqueue_broadcast_log(
                rule=rule,
                speaker=speaker,
                audio_file=self.audio,
                queue_priority=rule.priority,
            )

        self.assertEqual(
            BroadcastLog.objects.filter(
                rule=rule,
                status=BroadcastLog.STATUS_QUEUED,
            ).count(),
            3,
        )

    @patch("apps.notifications.pjsip_readiness.build_pjsip_playback_plan")
    def test_concurrent_speakers_receive_distinct_sip_and_rtp_ports(self, build_plan):
        speakers = [
            self.create_speaker("SPK-PORT-001"),
            self.create_speaker("SPK-PORT-002"),
        ]
        runtime_config = BroadcastRuntimeConfig(
            environment="production",
            operational_backend="pjsip",
            pjsip_executable_path="C:/fake/pjsua.exe",
            pjsip_local_ip="192.0.2.1",
            pjsip_advertise_ip="192.0.2.1",
            pjsip_local_sip_port_base=64882,
            pjsip_local_rtp_port_base=4004,
            pjsip_port_step=2,
            pjsip_audio_gain_percent=100,
            source="test",
        )
        build_plan.side_effect = lambda **kwargs: SimpleNamespace(**kwargs)

        readiness = [
            prepare_pjsip_readiness(
                speaker_code=speaker.speaker_code,
                audio_code=self.audio.audio_code,
                log_path=SimpleNamespace(),
                check_ports=False,
                runtime_config=runtime_config,
            )
            for speaker in speakers
        ]

        self.assertEqual(
            {item.plan.local_sip_port for item in readiness},
            {64882, 64884},
        )
        self.assertEqual(
            {item.plan.local_rtp_port for item in readiness},
            {4004, 4006},
        )

    @patch("apps.notifications.services.play_audio_to_speaker")
    def test_single_speaker_success_remains_compatible(self, playback):
        speaker = self.create_speaker("SPK-SINGLE")
        log, _created = self.enqueue(speaker)
        playback.return_value = {
            "success": True,
            "message": "simulated success",
        }

        result = process_single_broadcast_log(log)

        log.refresh_from_db()
        self.assertEqual(result["status"], BroadcastLog.STATUS_SUCCESS)
        self.assertEqual(log.status, BroadcastLog.STATUS_SUCCESS)

    @patch("apps.notifications.services.play_audio_to_speaker")
    def test_simulated_fifty_event_four_speaker_stress(self, playback):
        speakers = [self.create_speaker(f"SPK-STRESS-{index}") for index in range(4)]
        for index in range(50):
            speaker = speakers[index % len(speakers)]
            group = index % 8
            dedup_key = build_broadcast_dedup_key(
                rule_id=group,
                speaker_id=speaker.pk,
                event_source="CAM-STRESS",
                event_type="fall_detected",
            )
            self.enqueue(
                speaker,
                priority=10 if group >= 4 else 50,
                dedup_key=dedup_key,
            )

        active_by_speaker = {speaker.pk: 0 for speaker in speakers}
        max_by_speaker = {speaker.pk: 0 for speaker in speakers}
        execution_priorities = {speaker.pk: [] for speaker in speakers}
        state_lock = threading.Lock()
        start_barrier = threading.Barrier(4, timeout=3)
        first_calls = set()

        def play(**kwargs):
            log = kwargs["broadcast_log"]
            speaker_id = kwargs["speaker"].pk
            with state_lock:
                active_by_speaker[speaker_id] += 1
                max_by_speaker[speaker_id] = max(
                    max_by_speaker[speaker_id],
                    active_by_speaker[speaker_id],
                )
                execution_priorities[speaker_id].append(log.queue_priority)
                is_first = speaker_id not in first_calls
                first_calls.add(speaker_id)
            if is_first:
                start_barrier.wait()
            time.sleep(0.005)
            with state_lock:
                active_by_speaker[speaker_id] -= 1
            return {"success": True, "message": "simulated success"}

        playback.side_effect = play
        summary = process_queued_broadcasts(
            speaker_ids=[speaker.pk for speaker in speakers],
            max_workers=4,
        )

        self.assertEqual(summary["success_count"], 8, summary)
        self.assertEqual(
            BroadcastLog.objects.filter(status=BroadcastLog.STATUS_SUPPRESSED).count(),
            42,
        )
        self.assertEqual(
            BroadcastLog.objects.filter(status=BroadcastLog.STATUS_QUEUED).count(),
            0,
        )
        self.assertTrue(all(value == 1 for value in max_by_speaker.values()))
        for priorities in execution_priorities.values():
            self.assertEqual(priorities, sorted(priorities))
